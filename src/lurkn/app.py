"""Gtk.Application wiring for LurkNotes.

LurkNotes is intentionally an X11 client under XWayland: Mutter 46 does not
implement layer-shell, and only EWMH lets a window sit at the edge, above other
windows, outside the dock and on every workspace (spec §9.1).

The deck state machine is explicit: ``strip`` -> ``fan`` -> ``open``, with
peek as a read-only pane inside the fan. The pure machine (hover
delays, peek, collapse) lives in :mod:`lurkn.deck`; this module maps its states
onto GTK widgets and X11 hints, owns the one-slot memory undo behind
Ctrl+Backspace, and the All Notes window. Drag reorder belongs to ticket 06.

``LURKNOTES_APP_ID``
    Override the D-Bus application id. Smoke tests use a unique id so a
    concurrent run cannot hand its launch to this instance and inspect the
    wrong windows.
``LURKNOTES_TEST_DUMP``
    Write a JSON snapshot of the deck to this path after mapping and after
    opening a note. Includes fan tab centres so the smoke test can click one
    through X11.
``LURKNOTES_TEST_TYPE``
    Append this text to the open note shortly after it opens, as if typed.
``LURKNOTES_TEST_CONTROL``
    Register the ``control`` GAction the smoke test uses when another agent's
    ABOVE window owns the screen edge. Off in production: no extra action and
    no polling.
``LURKNOTES_TEST_OPEN_ALL``
    Open All Notes once the deck is mapped. Kept for the ticket 07 smoke; the
    real path is now ``lurknotes all``.
``LURKNOTES_TEST_PIN_DECK``
    Do not collapse the fan when the pointer leaves. Smokes for other tickets
    pin the deck so an unrelated pointer warp cannot hide the panel mid-test.
``LURKNOTES_TEST_REFUSE_FOCUS``
    Pretend activation was refused so the live smoke can prove the "Click to
    type" hint and the first-click grant on a machine where ``present()``
    normally succeeds.
``LURKNOTES_TEST_NO_HOVER``
    Ignore pointer-enter events. Lets the integration smoke prove that a bare
    ``lurknotes`` expands the fan itself, on a desktop where other agents move
    the shared pointer.
``LURKNOTES_TEST_UNDO_MS``
    Shorten the 10 s undo window. Production always uses 10 000 ms.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk

from . import autostart as autostart_file
from . import strings
from .cli import CliError, Command, parse
from .deck import (
    STATE_FAN,
    STATE_OPEN,
    STATE_STRIP,
    DeckMachine,
)
from .events import DeckChanged
from .focus import FocusGuard
from .notes import (
    Note,
    add_at_top,
    cycle_id,
    discard_all_untouched,
    discard_if_untouched,
    find_note,
    index_of,
    session_untouched_note,
)
from .onboarding import mark_onboarded, needs_onboarding
from .retry import Retrier
from .store import (
    LOAD_CORRUPT,
    LOAD_RECOVERED,
    LOAD_UNSUPPORTED,
    LoadResult,
    OverwriteBlocked,
    ReadOnlyError,
    Store,
    StoreError,
)
from .ui import install as install_theme
from .windows.all_notes import AllNotesWindow
from .windows.panel import WIDTH as PANEL_WIDTH
from .windows.panel import PanelWindow
from .windows.strip import WIDTH as STRIP_WIDTH
from .windows.strip import StripWindow
from .x11 import Rect, X11, centered_position, panel_rect, strip_rect

APP_ID = os.environ.get("LURKNOTES_APP_ID") or "dev.lurknotes.LurkNotes"

SAVE_DEBOUNCE_MS = 400
UNDO_TIMEOUT_MS = 10_000  # spec §4.5, §7.1

# Spec §13: a regular window starts below the GNOME top bar. Only used when
# Gdk.Monitor.get_workarea is unavailable.
_TOP_BAR_HEIGHT = 32


def _undo_timeout_ms() -> int:
    """The undo window, shortened only by the explicit smoke-test hook."""
    raw = os.environ.get("LURKNOTES_TEST_UNDO_MS")
    if not raw:
        return UNDO_TIMEOUT_MS
    try:
        value = int(raw)
    except ValueError:
        return UNDO_TIMEOUT_MS
    return value if value > 0 else UNDO_TIMEOUT_MS


@dataclass
class DeletedNote:
    """One deleted note plus everything undo needs to put it back.

    ``session_member`` is captured at delete time: an undone untouched note
    must still follow ticket 03's "discard when the session created it" rule.
    """

    note: Note
    index: int
    session_member: bool


class UndoController:
    """Exactly one pending delete, with a single timer.

    ``start`` finalises any previous payload (spec §10: a second delete fixes
    the first) and restarts the countdown. The payload is memory-only; nothing
    here is persisted and a restart therefore cannot undo anything.
    """

    def __init__(
        self,
        *,
        timeout_ms: int,
        schedule: Callable[[int, Callable[[], bool]], object],
        cancel: Callable[[object], None],
        on_expire: Callable[[], None] | None = None,
    ) -> None:
        self._timeout_ms = timeout_ms
        self._schedule = schedule
        self._cancel = cancel
        self._on_expire = on_expire
        self._handle: object | None = None
        self.pending: DeletedNote | None = None

    def start(self, deleted: DeletedNote) -> None:
        self.finalize()
        self.pending = deleted
        self._handle = self._schedule(self._timeout_ms, self._expire)

    def take(self) -> DeletedNote | None:
        """Hand the payload back once and cancel its timer."""
        if self.pending is None:
            return None
        self._cancel_timer()
        deleted, self.pending = self.pending, None
        return deleted

    def finalize(self) -> None:
        """Drop the payload; after this it can no longer be undone."""
        self._cancel_timer()
        self.pending = None

    def _cancel_timer(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        self._cancel(handle)

    def _expire(self) -> bool:
        self._handle = None
        self.pending = None
        if self._on_expire is not None:
            self._on_expire()
        return False


def _logical_workarea(monitor: Gdk.Monitor) -> Rect:
    get_workarea = getattr(monitor, "get_workarea", None)
    if get_workarea is not None:
        area = get_workarea()
        if area.width > 0 and area.height > 0:
            return Rect(area.x, area.y, area.width, area.height)

    geometry = monitor.get_geometry()
    return Rect(
        geometry.x,
        geometry.y,
        geometry.width,
        max(0, geometry.height - _TOP_BAR_HEIGHT),
    )


class LurkNotesApp(Gtk.Application):
    def __init__(
        self,
        x11: X11 | None = None,
        store: Store | None = None,
    ) -> None:
        super().__init__(
            application_id=APP_ID,
            # spec §9.3 / PLATFORM §5: argv is delivered to do_command_line,
            # including on a cold start, and do_activate never fires.
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.x11 = x11
        self.store = store or Store()
        self.notes: list[Note] = []
        # Untouched-note deletion requires knowing which notes this process
        # created. A loaded empty note has the same timestamps as a fresh one,
        # so timestamps alone must never decide it (spec §5.4).
        self.session_ids: set[str] = set()
        self.shutdown_done = False
        self.current_id: str | None = None
        # Hover/peek/collapse live in a pure, timer-injected machine (ticket
        # 04). The app maps its states onto widgets and X11 hints.
        self.deck = DeckMachine(
            self._schedule_timer,
            self._cancel_timer,
            on_panel_shown=self._show_panel,
            on_panel_hidden=self._hide_panel,
            on_peek=self._show_peek,
            on_unpeek=self._hide_peek,
        )
        self.save_source = 0
        self.read_only = False
        self.overwrite_blocked = False
        self.unsaved = False
        self._load_result: LoadResult | None = None
        self._load_error: str | None = None
        self.strip: StripWindow | None = None
        self.panel: PanelWindow | None = None
        self.all_notes: AllNotesWindow | None = None
        self._all_notes_placed = False
        self._all_notes_place_tries = 0
        # Ticket 07: read-only views (All Notes) subscribe here instead of
        # polling. Every mutation path calls ``deck_changed()``; ticket 06
        # (reorder) must do the same when it lands.
        self.deck_changed_event = DeckChanged()
        self._workarea: Rect | None = None
        self._retrier = Retrier(
            self._retry_save,
            schedule=GLib.timeout_add,
            cancel=GLib.source_remove,
        )
        self._undo = UndoController(
            timeout_ms=_undo_timeout_ms(),
            schedule=GLib.timeout_add,
            cancel=GLib.source_remove,
            on_expire=self._on_undo_expired,
        )
        self._test_dump_path = os.environ.get("LURKNOTES_TEST_DUMP")
        self._test_type = os.environ.get("LURKNOTES_TEST_TYPE")
        self._test_typed = False
        self._test_open_all = os.environ.get("LURKNOTES_TEST_OPEN_ALL") == "1"
        self._pin_deck = os.environ.get("LURKNOTES_TEST_PIN_DECK") == "1"
        # Prove that the bare command expands the fan by itself, with the
        # pointer path disabled, on a desktop where concurrent agents move
        # the shared pointer.
        self._test_no_hover = os.environ.get("LURKNOTES_TEST_NO_HOVER") == "1"
        self._last_command = ""
        # Simulate a shell that refuses activation; the live smoke uses this
        # to prove the "Click to type" path on a machine where present()
        # normally succeeds (PLATFORM §4).
        self._test_refuse_focus = (
            os.environ.get("LURKNOTES_TEST_REFUSE_FOCUS") == "1"
        )
        # Ticket 09: first-launch onboarding and the 150 ms focus decision.
        self._onboarding_pending = needs_onboarding()
        self._focus_guard: FocusGuard | None = None
        self._all_notes_focus_guard: FocusGuard | None = None

    @property
    def state(self) -> str:
        return self.deck.state

    def _schedule_timer(self, delay_ms: int, callback) -> int:
        def fire() -> bool:
            callback()
            return GLib.SOURCE_REMOVE

        return GLib.timeout_add(delay_ms, fire)

    def _cancel_timer(self, source: int) -> None:
        GLib.source_remove(source)

    # -- lifecycle -----------------------------------------------------

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        display = Gdk.Display.get_default()
        if display is not None:
            install_theme(display)
        # Spec §5.2 saves on exit; Ctrl+Q and the All Notes quit item (ticket
        # 07) both go through this action, so the shutdown cleanup runs too.
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        # Smoke-only control channel for a shared, busy X session. It is not
        # registered unless LURKNOTES_TEST_CONTROL is set, so production has
        # no extra action and no polling.
        if os.environ.get("LURKNOTES_TEST_CONTROL"):
            control = Gio.SimpleAction.new("control", GLib.VariantType.new("s"))
            control.connect("activate", self._on_test_control)
            self.add_action(control)
        self._load_notes()

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Handle every invocation, cold or warm (spec §9.3).

        ``HANDLES_COMMAND_LINE`` is what gives single-instance behaviour: a
        second process' argv is delivered here synchronously and its exit code
        is this method's return value (PLATFORM §5). ``do_activate`` never
        runs, so a cold start must build the deck from this path too.
        """
        argv = command_line.get_arguments()
        try:
            command = parse(list(argv[1:]))
        except CliError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        if command.help:
            print(strings.USAGE)
            return 0
        if command.install_autostart:
            return self._install_autostart()

        if self.strip is None:
            self._build_deck()
        self._dispatch(command)
        return 0

    def _install_autostart(self) -> int:
        try:
            written = autostart_file.install(
                launcher=autostart_file.launcher_path()
            )
        except OSError as exc:
            print(
                strings.AUTOSTART_INSTALL_FAILED.format(message=str(exc)),
                file=sys.stderr,
            )
            return 1
        print(strings.AUTOSTART_INSTALLED.format(path=written))
        return 0

    def _dispatch(self, command: Command) -> None:
        if command.autostart:
            # Session startup: just the strip. No fan, no present(), no focus.
            self._last_command = "autostart"
            self.strip.set_visible(True)
            return
        self._last_command = command.action or "expand"
        if command.action == "new":
            self.command_new()
        elif command.action == "all":
            self.command_all()
        else:
            self.expand_deck()

    def do_activate(self) -> None:
        # Unreachable with HANDLES_COMMAND_LINE, kept as the plain-activation
        # fallback so the app still has a sane surface if launched without argv.
        if self.strip is None:
            self._build_deck()
        self.expand_deck()

    def do_shutdown(self) -> None:
        # Ticket 03: flush, drop untouched session notes, save once. Ticket 08:
        # no retry timer may outlive the main loop. Ticket 04: same for hover
        # timers.
        self.deck.stop()
        self._shutdown_deck()
        panel_guard = getattr(self, "_focus_guard", None)
        if panel_guard is not None:
            panel_guard.clear()
        all_notes_guard = getattr(self, "_all_notes_focus_guard", None)
        if all_notes_guard is not None:
            all_notes_guard.clear()
        self.deck_changed_event.clear()
        self._retrier.stop()
        if self.x11 is not None:
            self.x11.close()
            self.x11 = None
        Gtk.Application.do_shutdown(self)

    def _on_quit(self, *_args) -> None:
        self.quit()

    def _on_test_control(self, _action, parameter) -> None:
        """Drive deck interactions when another test covers the screen.

        Only registered with ``LURKNOTES_TEST_CONTROL``. It calls the same
        handlers the X11 pointer would (motion controllers, button ``clicked``
        signals), so the state machine and widgets are exercised even when a
        concurrent agent's ABOVE window owns the pixels at the screen edge.
        """
        command = parameter.get_string() if parameter is not None else ""
        if command == "strip":
            self._on_deck_enter()
        elif command == "leave":
            self._on_deck_leave()
        elif command.startswith("tab:"):
            self._on_tab_enter(command[4:])
        elif command.startswith("untab:"):
            self._on_tab_leave(command[6:])
        elif command == "header":
            if self.panel is not None:
                self.panel.activate_collapse()
        elif command.startswith("tabclick:"):
            if self.panel is not None:
                self.panel.activate_tab(command[9:])
        elif command.startswith("scroll:"):
            if self.panel is not None:
                self.panel.scroll_by(float(command[7:]))
        elif command.startswith("open:"):
            self.open_note(command[5:])
        elif command == "close":
            self.close_note()
        elif command == "undo":
            self.undo_delete()
        else:
            print(f"lurknotes: unknown test control {command!r}", file=sys.stderr)

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        """A WM close is a normal shutdown, not one lost window (spec §5.2).

        Without this, closing the panel through the WM leaves the strip alive
        and the process running with half a deck. Returning True keeps the
        widget intact until ``do_shutdown`` has flushed and saved; GTK
        destroys the windows right after.
        """
        self.quit()
        return True

    def _shutdown_deck(self) -> None:
        """Flush, drop untouched session notes, save (spec §5.2, §5.4).

        An untouched note must not reach the next launch: on disk it would
        come back as a *loaded* empty note and live forever. The flush runs
        first, because typed text is what makes a note non-untouched. Loaded
        empty notes are never in ``session_ids`` and therefore survive.
        """
        if self.shutdown_done:
            return
        self.shutdown_done = True
        # Undo is memory-only and must not outlive the window: the deleted
        # note is already absent from the file, so dropping the payload here
        # is the whole finalisation.
        self._undo.finalize()
        self._flush_current()
        removed = discard_all_untouched(self.notes, self.session_ids)
        self.current_id = None
        if removed:
            self._save_notes()

    # -- data ----------------------------------------------------------

    def _load_notes(self) -> None:
        self._load_result = None
        self._load_error = None
        try:
            result = self.store.load()
        except (StoreError, OSError) as exc:
            # Reading failed (permissions, I/O): work in memory, never write
            # over a file we could not inspect.
            self.read_only = True
            self.notes = []
            self._load_error = str(exc)
            print(strings.ERROR.format(message=str(exc)), file=sys.stderr)
            return

        self._load_result = result
        self.notes = result.notes
        self.read_only = result.read_only
        self.overwrite_blocked = result.overwrite_blocked
        if result.save_error is not None:
            # Recovered notes are in memory but the write failed; keep the
            # deck usable and let the retry timer persist it.
            self.unsaved = True
        if result.detail:
            print(strings.ERROR.format(message=result.detail), file=sys.stderr)
        if result.save_error is not None:
            print(
                strings.ERROR.format(
                    message=f"cannot persist recovered notes: {result.save_error}"
                ),
                file=sys.stderr,
            )

    def _save_notes(self) -> bool:
        if self.read_only or self.overwrite_blocked:
            # Read-only files and unconfirmed corrupt files must never be
            # written by debounce, close, or shutdown.
            return False
        try:
            self.store.save(self.notes)
        except (OverwriteBlocked, ReadOnlyError) as exc:
            # The store's own safety gate disagreed with the app state; adopt
            # it rather than retrying a forbidden write.
            self.read_only = isinstance(exc, ReadOnlyError)
            self.overwrite_blocked = isinstance(exc, OverwriteBlocked)
            print(strings.ERROR.format(message=str(exc)), file=sys.stderr)
            return False
        except (OSError, StoreError) as exc:
            self.unsaved = True
            if self.panel is not None:
                self.panel.show_save_failed(True)
            print(strings.ERROR.format(message=str(exc)), file=sys.stderr)
            self._retrier.failed()
            self._schedule_test_dump()
            return False
        self.unsaved = False
        if self.panel is not None:
            self.panel.show_save_failed(False)
        self._retrier.succeeded()
        self._schedule_test_dump()
        return True

    def _retry_save(self) -> None:
        # The retrier schedules only while ``unsaved`` is true; a successful
        # attempt clears it, a failing one schedules the next backoff.
        self._save_notes()

    def _show_storage_status(self) -> None:
        if self.panel is None:
            return
        result = self._load_result
        if result is None:
            if self._load_error is not None:
                self.panel.show_status(
                    strings.STORAGE_READ_FAILED.format(detail=self._load_error)
                )
            return

        if result.status == LOAD_RECOVERED:
            if result.save_error is not None:
                self.panel.show_status(strings.STORAGE_RECOVERY_NOT_SAVED)
                self._retrier.failed()
                return
            corrupt = (
                result.corrupt_path.name
                if result.corrupt_path is not None
                else "notes.corrupt-<timestamp>.json"
            )
            self.panel.show_status(
                strings.STORAGE_RECOVERED.format(
                    count=len(result.notes), corrupt=corrupt
                ),
                kind="warning",
                dismissible=True,
            )
        elif result.status == LOAD_CORRUPT:
            self.panel.show_status(
                strings.STORAGE_CORRUPT,
                action_label=strings.STATUS_CONTINUE,
                on_action=self._confirm_overwrite,
            )
        elif result.status == LOAD_UNSUPPORTED:
            self.panel.show_status(
                strings.STORAGE_UNSUPPORTED,
                kind="warning",
                dismissible=True,
            )

    def _confirm_overwrite(self) -> None:
        if not self.store.confirm_overwrite():
            return
        self.overwrite_blocked = False
        print(
            strings.ERROR.format(
                message="user confirmed replacing the corrupt notes file"
            ),
            file=sys.stderr,
        )
        self._schedule_test_dump()

    # -- deck ----------------------------------------------------------

    def _build_deck(self) -> None:
        display = Gdk.Display.get_default()
        monitor = display.get_monitors().get_item(0)
        self._workarea = _logical_workarea(monitor)

        self.strip = StripWindow(self, self._workarea.height)
        self.panel = PanelWindow(
            self,
            height=self._workarea.height,
            on_open=self.open_note,
            on_close=self.close_note,
            on_new=self.new_note,
            on_cycle=self.cycle_note,
            on_escape=self.on_escape,
            on_changed=self.on_text_changed,
            on_collapse=self.collapse_deck,
            on_hover_tab=self._on_tab_enter,
            on_leave_tab=self._on_tab_leave,
            on_scrolled=lambda: self._schedule_test_dump(delay=30),
            on_delete=self.delete_current,
            on_undo=self.undo_delete,
            on_focus_click=self._grant_panel_focus,
        )
        self._focus_guard = FocusGuard(
            self._schedule_timer,
            self._cancel_timer,
            is_focused=self._panel_focus_for_guard,
            on_missing=self._on_panel_focus_missing,
        )
        self.panel.connect("notify::is-active", self._on_panel_active_changed)
        self.panel.show_fan(self.notes)
        self.panel.set_read_only(self.read_only)
        self._show_storage_status()

        # Hover is tracked at the window edges, not per tab: leaving the strip
        # for the panel is one continuous "inside the deck" stay, and only
        # leaving the panel starts the collapse timer.
        self.strip.add_controller(
            self._motion_controller(self._on_deck_enter, self._on_deck_leave)
        )
        self.panel.add_controller(
            self._motion_controller(self._on_deck_enter, self._on_deck_leave)
        )

        # Realize, then mark the windows as non-focusing *before* mapping them.
        # A window that maps with input=True would yank keyboard focus from
        # whatever the user is typing in.
        for window in (self.strip, self.panel):
            window.realize()
            xid = self._xid(window)
            if xid is None:
                raise RuntimeError("window was not realized")
            self.x11.set_deck_hints(xid)
            self.x11.set_input(xid, False)
            self.x11.set_no_focus(xid)

        self.strip.connect("map", self._on_strip_map)
        self.panel.connect("map", self._on_panel_map)
        for window in (self.strip, self.panel):
            window.connect("close-request", self._on_close_request)
        # Spec §3/§6.1: rest is the strip. The fan is mapped by the hover
        # machine, never at startup.
        self.strip.set_visible(True)
        self.panel.set_visible(False)
        self._schedule_test_dump(delay=100)
        if self._test_open_all:
            GLib.timeout_add(250, self._open_all_notes_for_test)

    def _motion_controller(self, on_enter, on_leave) -> Gtk.EventControllerMotion:
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda _controller, _x, _y: on_enter())
        motion.connect("leave", lambda _controller: on_leave())
        return motion

    def _on_deck_enter(self) -> None:
        if getattr(self, "_test_no_hover", False):
            return
        self.deck.hover_enter()

    def _on_deck_leave(self) -> None:
        if self._pin_deck:
            return
        # Ticket 05: while an undo is available, unmapping the fan would take
        # the toast and its Undo button with it. Hide the peek, stay mapped.
        self.deck.hover_leave(allow_collapse=self._undo.pending is None)

    def _on_tab_enter(self, note_id: str) -> None:
        self.deck.hover_tab(note_id)

    def _on_tab_leave(self, note_id: str) -> None:
        self.deck.hover_tab_leave(note_id)

    def _open_all_notes_for_test(self) -> bool:
        self.show_all_notes()
        return False

    def show_all_notes(self) -> None:
        """Show (or raise) the All Notes window; ticket 09's ``all`` uses this."""
        if self.strip is None:
            self._build_deck()
        if self.all_notes is None:
            self.all_notes = AllNotesWindow(
                self,
                notes_provider=self.notes_for_view,
                on_open=self.open_note,
                events=self.deck_changed_event,
                on_refresh=lambda: self._schedule_test_dump(delay=80),
            )
            self.all_notes.connect("map", self._on_all_notes_map)
        self.all_notes.refresh()
        self.all_notes.present()
        self.all_notes.focus_search()
        self._watch_all_notes_focus()
        self._schedule_test_dump(delay=100)

    def _on_all_notes_map(self, *_args) -> None:
        # GNOME places a plain X11 window at the workarea corner. Spec §6 says
        # All Notes opens centred; wait for GTK's shadow extents, then move it.
        if not self._all_notes_placed:
            # Centre immediately with the extents known at map time; a later
            # pass corrects for CSD shadows once GTK publishes them.
            self._place_all_notes()
            GLib.timeout_add(50, self._place_all_notes)

    def _place_all_notes(self) -> bool:
        if (
            self.all_notes is None
            or self.x11 is None
            or self._workarea is None
        ):
            return False
        surface = self.all_notes.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        width = self.all_notes.get_width()
        height = self.all_notes.get_height()
        if width <= 0 or height <= 0:
            return False
        extents = self.x11.frame_extents(xid)
        x, y = centered_position(
            self._workarea,
            surface.get_scale(),
            width,
            height,
            extents,
        )
        self.x11.move(xid, x, y)
        if extents == (0, 0, 0, 0) and self._all_notes_place_tries < 5:
            # GTK may set _GTK_FRAME_EXTENTS a frame after the map; correct
            # the centre when it does. The first pass already put the window
            # at the workarea centre, so the smoke never sees the WM default.
            self._all_notes_place_tries += 1
            GLib.timeout_add(50, self._place_all_notes)
        else:
            self._all_notes_placed = True
        return False

    def notes_for_view(self) -> list[Note]:
        """The deck as read-only views must see it (All Notes, spec §4.3).

        The open note's text comes straight from the editor buffer, so what is
        being typed appears in All Notes before the 400 ms autosave runs. All
        other notes are the app's own objects; views never mutate them.
        """
        live_id = (
            self.current_id
            if self.state == STATE_OPEN and self.panel is not None
            else None
        )
        if live_id is None:
            return list(self.notes)
        live_text = self.panel.note.text()
        now = time.time()
        snapshot: list[Note] = []
        for note in self.notes:
            if note.id == live_id and live_text != note.text:
                snapshot.append(
                    Note(
                        id=note.id,
                        text=live_text,
                        created=note.created,
                        updated=now,
                    )
                )
            else:
                snapshot.append(note)
        return snapshot

    def deck_changed(self) -> None:
        """Tell read-only views that the deck changed.

        Called from every mutation path in this module (text, create, delete,
        undo). Ticket 06's reorder must call this after it touches
        ``self.notes`` so All Notes stays in sync without a reopen.
        """
        self.deck_changed_event.notify()
        self._schedule_test_dump(delay=100)

    def _xid(self, window: Gtk.Window) -> int | None:
        surface = window.get_surface()
        if surface is None:
            return None
        return GdkX11.X11Surface.get_xid(surface)

    def _on_strip_map(self, *_args) -> None:
        # Mutter applies its own state and WM_HINTS when the window maps, so
        # the hints set before mapping are not enough. Re-assert them after
        # the window is viewable, then settle the exact X11 rect.
        self._settle_strip()
        GLib.timeout_add(50, self._settle_strip)

    def _on_panel_map(self, *_args) -> None:
        # Every hover remap drops _NET_WM_STATE, _NET_WM_DESKTOP, WM_HINTS and
        # the position (PLATFORM §2). Re-applying here — not only at startup —
        # is what keeps the fan above, sticky and input-less after a collapse.
        self._settle_panel()
        GLib.timeout_add(50, self._settle_panel)
        self._schedule_test_dump(delay=60)

    def _show_panel(self) -> None:
        """Map the fan without focus: never ``present()`` for hover (§7.4)."""
        if self.panel is None:
            return
        self.panel.set_visible(True)
        self._maybe_show_onboarding()
        self._schedule_test_dump(delay=30)

    def _hide_panel(self) -> None:
        if self.panel is None:
            return
        if self._focus_guard is not None:
            self._focus_guard.clear()
        self._set_focus_hint(False)
        self.panel.set_visible(False)
        self._schedule_test_dump(delay=30)

    def _show_peek(self, note_id: str) -> None:
        if self.panel is None or self.state != STATE_FAN:
            return
        note = find_note(self.notes, note_id)
        if note is None:
            return
        self.panel.show_peek(note_id, note.preview())
        self._schedule_test_dump(delay=30)

    def _hide_peek(self) -> None:
        if self.panel is not None:
            self.panel.hide_peek()
        self._schedule_test_dump(delay=20)

    def _settle_strip(self) -> bool:
        if self.strip is None or self.x11 is None:
            return False
        xid = self._xid(self.strip)
        if xid is None:
            return False
        self.x11.set_deck_hints(xid)
        self.x11.set_input(xid, False)
        self.x11.set_no_focus(xid)
        self._place_strip()
        return False

    def _settle_panel(self) -> bool:
        if self.panel is None or self.x11 is None:
            return False
        xid = self._xid(self.panel)
        if xid is None:
            return False
        self.x11.set_deck_hints(xid)
        self.x11.set_input(xid, self.state == STATE_OPEN)
        if self.state != STATE_OPEN:
            self.x11.set_no_focus(xid)
        self._place_panel()
        return False

    def _place_strip(self) -> bool:
        if self.strip is None or self.x11 is None or self._workarea is None:
            return False
        surface = self.strip.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        rect = strip_rect(self._workarea, surface.get_scale(), STRIP_WIDTH)
        self.x11.move_resize(xid, rect)
        return False

    def _place_panel(self) -> bool:
        if self.panel is None or self.x11 is None or self._workarea is None:
            return False
        surface = self.panel.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        rect = panel_rect(
            self._workarea,
            surface.get_scale(),
            PANEL_WIDTH,
            STRIP_WIDTH,
        )
        self.x11.move_resize(xid, rect)
        return False

    # -- navigation ----------------------------------------------------

    def expand_deck(self) -> None:
        """Show the fan now, without a hover delay (spec §9.3).

        No focus is requested: this path is also the bare ``lurknotes``
        invocation, where the user may just be looking at the deck.
        """
        if self.strip is None:
            self._build_deck()
        if self.deck.state == STATE_STRIP:
            self.deck.expand_now()
        if self.panel is not None and self.deck.panel_visible:
            # expand_now's callback maps it; an already-open note keeps it.
            self.panel.set_visible(True)
            self._maybe_show_onboarding()
        self._schedule_test_dump(delay=30)

    def command_new(self) -> bool:
        """``lurknotes new``: create and open a note, or reuse the untouched one.

        Ticket 08 gate: a read-only or unconfirmed-corrupt deck must surface
        its banner instead of silently doing nothing. ``all`` still works.
        """
        if self.read_only or self.overwrite_blocked:
            self.expand_deck()
            self._show_storage_status()
            return False

        current = self.current_id if self.state == STATE_OPEN else None
        reusable = session_untouched_note(
            self.notes, current, self.session_ids
        )
        if reusable is not None:
            # A second hotkey press while the blank note is already open must
            # focus that note, not stack another Untitled (spec §9.3).
            self.open_note(reusable.id)
            return True
        self.new_note()
        return True

    def command_all(self) -> None:
        self.show_all_notes()

    def new_note(self) -> None:
        """Create a note at the top of the deck and open it (spec §4.1)."""
        if self.read_only or self.overwrite_blocked:
            # Read-only and unconfirmed-corrupt files cannot accept new notes:
            # anything created now could never be saved. Surface the existing
            # ticket 08 banner instead of silently doing nothing.
            self._show_storage_status()
            return
        self._leave_current()
        note = Note.create()
        add_at_top(self.notes, note)
        self.session_ids.add(note.id)
        # Ordering is the array, so a crash before typing must not lose the
        # new note's place at the top.
        self._save_notes()
        self.open_note(note.id)
        self.deck_changed()

    def open_note(self, note_id: str) -> None:
        note = find_note(self.notes, note_id)
        if note is None:
            return
        if self.current_id == note.id and self.state == STATE_OPEN:
            self._activate_panel()
            return

        # Spec §5.2: switching notes writes the note being left; §5.4: an
        # untouched note from this session disappears instead of being kept.
        self._leave_current()
        self.current_id = note.id
        self.deck.open(note.id)
        # All Notes can open a note while the deck rests as a strip; the
        # editor must map that hidden panel before present() focuses it.
        if self.panel is not None:
            self.panel.set_visible(True)
            self._maybe_show_onboarding()
        self.panel.show_note(note, self.notes)
        self._activate_panel()
        self._schedule_test_dump()
        if self._test_type:
            GLib.timeout_add(600, self._maybe_test_type)

    def close_note(self) -> None:
        if self.state != STATE_OPEN:
            return
        self._leave_current()
        self.deck.close()

        if self._focus_guard is not None:
            self._focus_guard.clear()
        self._set_focus_hint(False)
        xid = self._xid(self.panel) if self.panel is not None else None
        if xid is not None and self.x11 is not None:
            self.x11.set_input(xid, False)
            self.x11.set_no_focus(xid)
        if self.panel is not None:
            self.panel.show_fan(self.notes)
        self._schedule_test_dump()

    def collapse_deck(self) -> None:
        """Collapse fan -> strip from the header ``×`` (no focus needed).

        The machine refuses in ``open``: an open note is never discarded by a
        hover path or a stray click on a header that is not even showing. An
        undo toast pins the panel too: its Undo button must stay clickable.
        """
        if self._undo.pending is not None:
            return
        if self.deck.collapse():
            if self._focus_guard is not None:
                self._focus_guard.clear()
            self._set_focus_hint(False)
            self._schedule_test_dump(delay=30)

    def _pointer_over_deck(self) -> bool:
        """Is the pointer still inside the strip+panel rectangle?"""
        if self.x11 is None or self._workarea is None or self.panel is None:
            return True
        pointer = self.x11.pointer()
        surface = self.panel.get_surface()
        if pointer is None or surface is None:
            return True
        scale = surface.get_scale()
        workarea = self._workarea
        right = round((workarea.x + workarea.width) * scale)
        left = right - round((PANEL_WIDTH + STRIP_WIDTH) * scale)
        top = round(workarea.y * scale)
        bottom = round((workarea.y + workarea.height) * scale)
        return left <= pointer[0] < right and top <= pointer[1] < bottom

    def _panel_has_focus(self) -> bool:
        """Authoritative focus check; ``is_active()`` lies after unmap."""
        if self.panel is None or self.x11 is None:
            return False
        xid = self._xid(self.panel)
        return xid is not None and self.x11.has_focus(xid)

    # -- focus policy (spec §9.5) -------------------------------------

    def _watch_panel_focus(self) -> None:
        """Check 150 ms after activation; show the hint if focus was refused."""
        guard = getattr(self, "_focus_guard", None)
        if guard is None or getattr(self, "x11", None) is None:
            return
        self._set_focus_hint(False)
        guard.watch()

    def _panel_focus_for_guard(self) -> bool:
        if getattr(self, "_test_refuse_focus", False):
            return False
        return self._panel_has_focus()

    def _on_panel_focus_missing(self) -> None:
        # Only an editor needs a keyboard: a blocked `new` leaves the fan up,
        # where no typing target exists.
        if (
            self.panel is None
            or not self.panel.get_visible()
            or self.state != STATE_OPEN
        ):
            return
        self._set_focus_hint(True)
        self._schedule_test_dump(delay=30)

    def _on_panel_active_changed(self, *_args) -> None:
        """Clear the hint when focus arrives a little later than 150 ms."""
        if self.panel is None or self.x11 is None:
            return
        if getattr(self, "_test_refuse_focus", False):
            return
        if not self.panel.is_active():
            return
        if not self._panel_has_focus():
            return
        if self._focus_guard is not None:
            self._focus_guard.focus_arrived()
        self._set_focus_hint(False)
        self._schedule_test_dump(delay=30)

    def _grant_panel_focus(self) -> None:
        """First click on an unfocused editor: take input and focus the caret."""
        if self.panel is None:
            return
        if self._focus_guard is not None:
            self._focus_guard.clear()
        self._set_focus_hint(False)
        xid = self._xid(self.panel)
        if xid is not None and self.x11 is not None:
            self.x11.set_input(xid, True)
            self.x11.allow_focus(xid)
        self.panel.present()
        self.panel.focus_editor()
        self._schedule_test_dump(delay=30)

    def _set_focus_hint(self, visible: bool) -> None:
        show = getattr(self.panel, "show_focus_hint", None)
        if show is not None:
            show(visible)

    def _watch_all_notes_focus(self) -> None:
        if self.all_notes is None or self.x11 is None:
            return
        if self._all_notes_focus_guard is None:
            self._all_notes_focus_guard = FocusGuard(
                self._schedule_timer,
                self._cancel_timer,
                is_focused=self._all_notes_has_focus,
                on_missing=self._on_all_notes_focus_missing,
            )
        self._all_notes_focus_guard.watch()

    def _all_notes_has_focus(self) -> bool:
        if self.all_notes is None or self.x11 is None:
            return False
        if getattr(self, "_test_refuse_focus", False):
            return False
        xid = self._xid(self.all_notes)
        return xid is not None and self.x11.has_focus(xid)

    def _on_all_notes_focus_missing(self) -> None:
        # A normal window takes focus on click by itself; retry the activation
        # once rather than pretending an edge panel is on screen.
        if self.all_notes is None or not self.all_notes.get_visible():
            return
        self.all_notes.present()
        self.all_notes.focus_search()
        self._schedule_test_dump(delay=30)

    def _maybe_show_onboarding(self) -> None:
        """Show the one-time hotkey hint the first time the deck is visible."""
        if not getattr(self, "_onboarding_pending", False):
            return
        if self.panel is None or not self.panel.get_visible():
            return
        show = getattr(self.panel, "show_onboarding", None)
        if show is None:
            return
        self._onboarding_pending = False
        show()
        # Best effort: a read-only data dir still gets the hint this run.
        mark_onboarded()
        self._schedule_test_dump(delay=30)

    def cycle_note(self, step: int) -> None:
        """Open the note *step* places away, wrapping (spec §7.3)."""
        target_id = cycle_id(self.notes, self.current_id, step)
        if target_id is not None:
            self.open_note(target_id)

    # -- delete / undo -------------------------------------------------

    def delete_current(self) -> bool:
        """Ctrl+Backspace: delete the open note and write the file at once.

        The payload handed to the undo slot is the live :class:`Note`, so id,
        created/updated and the untouched-session property survive an undo
        unchanged. Read-only decks still delete in memory: ``_save_notes``
        refuses the write and leaves ticket 08's banner alone.
        """
        if self.state != STATE_OPEN or self.current_id is None:
            return False
        note = find_note(self.notes, self.current_id)
        if note is None:
            return False

        # Capture text still waiting for the 400 ms debounce, but do not save
        # it separately: the deletion save below writes the deck once.
        self._flush_current(save=False)
        index = index_of(self.notes, note.id)

        self.notes.remove(note)
        self.current_id = None
        self._save_notes()
        self.deck_changed()
        self._undo.start(
            DeletedNote(
                note=note,
                index=index,
                session_member=note.id in self.session_ids,
            )
        )
        if self.panel is not None:
            self.panel.show_toast()

        if self.notes:
            # The note that took the freed place (or the new last one) keeps
            # the panel in the open state, ready for the next thought.
            self.open_note(self.notes[min(index, len(self.notes) - 1)].id)
        else:
            # Spec §4.6: an empty deck shows the fan's empty state. The panel
            # stays mapped, so the toast above it remains clickable; the deck
            # machine goes open -> fan and the fan is input-less again.
            self.deck.close()
            xid = self._xid(self.panel) if self.panel is not None else None
            if xid is not None and self.x11 is not None:
                self.x11.set_input(xid, False)
                self.x11.set_no_focus(xid)
            if self.panel is not None:
                self.panel.show_fan(self.notes)
            self._schedule_test_dump()
        return True

    def undo_delete(self) -> bool:
        """Ctrl+Z / Undo: put the pending note back and reopen it.

        This is an ordinary save followed by an ordinary open: the restored
        note lands at its original array index and the state machine goes
        back to ``open``. No note is resurrected once the timer expired.
        """
        deleted = self._undo.take()
        if deleted is None:
            return False
        if self.panel is not None:
            self.panel.hide_toast()

        index = max(0, min(deleted.index, len(self.notes)))
        self.notes.insert(index, deleted.note)
        if deleted.session_member:
            # Membership may already be there; keeping it explicit is what
            # makes an undone untouched note discardable again (spec §5.4).
            self.session_ids.add(deleted.note.id)
        self._save_notes()
        self.deck_changed()
        self.open_note(deleted.note.id)
        return True

    def _on_undo_expired(self) -> None:
        if self.panel is not None:
            self.panel.hide_toast()
        # Nothing is pinning the fan any more. If the pointer is already
        # gone, the next leave event will never come, so collapse now.
        if self.state == STATE_FAN and not self._pointer_over_deck():
            self.deck.collapse()
        self._schedule_test_dump(delay=30)

    def _leave_current(self) -> None:
        """Flush and, when appropriate, drop the note being left."""
        previous_id = self.current_id
        if previous_id is None:
            return
        self._flush_current()
        removed = discard_if_untouched(
            self.notes, previous_id, self.session_ids
        )
        if removed is not None:
            # Spec §5.4: the deletion is written at once, not debounced.
            self._save_notes()
            self.deck_changed()
        self.current_id = None

    def on_escape(self) -> bool:
        # Spec §7.3: Esc closes the note when the panel has focus; a second
        # Esc collapses the fan, and only while the panel really holds focus.
        if self.state == STATE_OPEN:
            self.close_note()
            return True
        if self.state == STATE_FAN and self._panel_has_focus():
            self.collapse_deck()
            return True
        return False

    def _activate_panel(self) -> None:
        if self.panel is None:
            return
        xid = self._xid(self.panel)
        if xid is not None and self.x11 is not None:
            self.x11.set_input(xid, True)
            self.x11.allow_focus(xid)
        self.panel.present()
        self.panel.focus_editor()
        # Spec §9.5: present() is a request. Decide 150 ms later whether the
        # panel actually got the keyboard; otherwise show "Click to type".
        self._watch_panel_focus()

    # -- editing -------------------------------------------------------

    def on_text_changed(self) -> None:
        if self.current_id is None:
            return
        self._cancel_save_timer()
        self.save_source = GLib.timeout_add(
            SAVE_DEBOUNCE_MS, self._on_save_timeout
        )
        # All Notes reads the live editor buffer through ``notes_for_view``,
        # so it sees the keystroke before the autosave timer fires.
        self.deck_changed()

    def _on_save_timeout(self) -> bool:
        self.save_source = 0
        self._flush_current()
        return False

    def _cancel_save_timer(self) -> None:
        if self.save_source:
            GLib.source_remove(self.save_source)
            self.save_source = 0

    def _flush_current(self, *, save: bool = True) -> None:
        self._cancel_save_timer()
        if self.current_id is None or self.panel is None:
            return
        note = find_note(self.notes, self.current_id)
        if note is None:
            return
        text = self.panel.note.text()
        changed = text != note.text
        if changed:
            note.text = text
            note.updated = time.time()
            self.panel.refresh_notes(self.notes, note.id)
            self.deck_changed()
        # A previous failure leaves the deck dirty even when the text has not
        # changed since: close and shutdown must retry before giving up.
        # Delete passes save=False because it writes the already-shortened
        # deck immediately after this snapshot.
        if save and (changed or self.unsaved):
            self._save_notes()

    # -- test hooks ----------------------------------------------------

    def _schedule_test_dump(self, delay: int = 150) -> None:
        if self._test_dump_path:
            GLib.timeout_add(delay, self._write_test_dump)

    def _write_test_dump(self) -> bool:
        if not self._test_dump_path or self.panel is None:
            return False

        state = self.state
        is_open = state == STATE_OPEN
        is_fan = state == STATE_FAN
        peek = self.panel.peek_snapshot()
        peek["center"] = self.panel.peek_center() if is_fan else None
        snapshot = {
            "state": state,
            "current_id": self.current_id,
            "ids": [note.id for note in self.notes],
            "titles": [note.title() for note in self.notes],
            "tab_centers": (
                self.panel.tab_centers() if is_fan else []
            ),
            "tab_heights": self.panel.tab_heights() if is_fan else [],
            "new_button_center": (
                self.panel.new_button_center() if is_fan else None
            ),
            "collapse_button_center": (
                self.panel.collapse_button_center() if is_fan else None
            ),
            "scroll_value": self.panel.scroll_value(),
            "peek": peek,
            "rail_centers": (
                self.panel.rail_centers() if is_open else []
            ),
            "active_index": (
                self.panel.active_index() if is_open else -1
            ),
            "text": self.panel.note.text() if is_open else None,
            "cursor_offset": (
                self.panel.note.cursor_offset() if is_open else None
            ),
            "cursor_at_end": self.panel.note.cursor_at_end() if is_open else None,
            "rail_width": self.panel.note.rail_width() if is_open else None,
            "typed": self._test_typed,
            "read_only": self.read_only,
            "overwrite_blocked": self.overwrite_blocked,
            "unsaved": self.unsaved,
            "status": self.panel.status_snapshot(),
            "all_notes": (
                self.all_notes.snapshot()
                if self.all_notes is not None
                else None
            ),
            "toast": self.panel.toast_snapshot(),
            "undo_pending": self._undo.pending is not None,
            "panel_focused": self._panel_has_focus(),
            "focus_hint": self.panel.focus_hint_snapshot(),
            "onboarding": self.panel.onboarding_snapshot(),
            "last_command": getattr(self, "_last_command", ""),
        }
        target = Path(self._test_dump_path)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_text(json.dumps(snapshot), encoding="utf-8")
            os.replace(temporary, target)
        except OSError:
            pass
        return False

    def _maybe_test_type(self) -> bool:
        if not self._test_type or self._test_typed or self.state != STATE_OPEN:
            return False
        self._test_typed = True
        self.panel.note.insert_at_cursor(self._test_type)
        self._schedule_test_dump(delay=30)
        return False
