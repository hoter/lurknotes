"""Gtk.Application wiring for LurkNotes.

LurkNotes is intentionally an X11 client under XWayland: Mutter 46 does not
implement layer-shell, and only EWMH lets a window sit at the edge, above other
windows, outside the dock and on every workspace (spec §9.1).

The deck state machine is explicit: ``strip`` -> ``fan`` -> ``open``, with
peek as a read-only pane inside the fan. The pure machine (hover
delays, peek, collapse) lives in :mod:`lurkn.deck`; this module maps its states
onto GTK widgets and X11 hints. The one-slot memory undo behind Ctrl+Backspace
lives in :mod:`lurkn.undo`; drag reorder belongs to ticket 06.

``LURKNOTES_APP_ID``
    Override the D-Bus application id. Smoke tests use a unique id so a
    concurrent run cannot hand its launch to this instance and inspect the
    wrong windows.

Test-only hooks (dump, control action, deterministic typing, pin/refuse/no
hover, shortened undo) live in :mod:`lurkn.testhooks` and are documented there.
They are env-gated and absent from production behaviour.
"""

from __future__ import annotations

import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk

from . import autostart as autostart_file
from . import storage_ui
from . import strings
from . import testhooks
from .cli import CliError, Command, parse
from .deck import (
    STATE_FAN,
    STATE_OPEN,
    STATE_STRIP,
    DeckMachine,
)
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
    LoadResult,
    OverwriteBlocked,
    ReadOnlyError,
    Store,
    StoreError,
)
from .testhooks import TestHooks
from .ui import install as install_theme
from .undo import DeletedNote, UndoController
from .windows.panel import WIDTH as PANEL_WIDTH
from .windows.panel import PanelWindow
from .windows.placement import Placement, logical_workarea
from .windows.strip import WIDTH as STRIP_WIDTH
from .windows.strip import StripWindow
from .x11 import Rect, X11

APP_ID = os.environ.get("LURKNOTES_APP_ID") or "dev.lurknotes.LurkNotes"

SAVE_DEBOUNCE_MS = 400

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
        self._placement = Placement(self)
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
        self._workarea: Rect | None = None
        self._retrier = Retrier(
            self._retry_save,
            schedule=GLib.timeout_add,
            cancel=GLib.source_remove,
        )
        self._undo = UndoController(
            timeout_ms=testhooks.undo_timeout_ms(),
            schedule=GLib.timeout_add,
            cancel=GLib.source_remove,
            on_expire=self._on_undo_expired,
        )
        self._hooks = TestHooks(self)
        self._last_command = ""
        # Ticket 09: first-launch onboarding and the 150 ms focus decision.
        self._onboarding_pending = needs_onboarding()
        self._focus_guard: FocusGuard | None = None

    @property
    def state(self) -> str:
        return self.deck.state

    @property
    def dragging(self) -> bool:
        return self.deck.dragging

    def drag_snapshot(self) -> dict:
        """Observable drag state for views/tests (ticket 10 reads the dump)."""
        if self.panel is None:
            return {
                "pressed": False,
                "active": False,
                "note_id": None,
                "source_index": -1,
                "target_index": None,
                "raised": False,
                "cursor": None,
            }
        return self.panel.drag_snapshot()

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
        # Spec §5.2 saves on exit; Ctrl+Q and the fan's quit button both go
        # through this action, so the shutdown cleanup runs too.
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        # Smoke-only control channel, env-gated in lurkn.testhooks.
        self._hooks.install_control_action()
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
        self._retrier.stop()
        if self.x11 is not None:
            self.x11.close()
            self.x11 = None
        Gtk.Application.do_shutdown(self)

    def _on_quit(self, *_args) -> None:
        self.quit()

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
            self._hooks.schedule_dump()
            return False
        self.unsaved = False
        if self.panel is not None:
            self.panel.show_save_failed(False)
        self._retrier.succeeded()
        self._hooks.schedule_dump()
        return True

    def _retry_save(self) -> None:
        # The retrier schedules only while ``unsaved`` is true; a successful
        # attempt clears it, a failing one schedules the next backoff.
        self._save_notes()

    # -- deck ----------------------------------------------------------

    def _build_deck(self) -> None:
        display = Gdk.Display.get_default()
        monitor = display.get_monitors().get_item(0)
        self._workarea = logical_workarea(monitor)

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
            on_quit=self._on_quit,
            on_search_focus=self._grant_search_focus,
            on_search_changed=lambda: self._hooks.schedule_dump(delay=30),
            on_hover_tab=self._on_tab_enter,
            on_leave_tab=self._on_tab_leave,
            on_scrolled=lambda: self._hooks.schedule_dump(delay=30),
            on_delete=self.delete_current,
            on_undo=self.undo_delete,
            on_reorder=self.reorder_note,
            on_drag_begin=self._on_drag_start,
            on_drag_update=self._on_drag_update,
            on_drag_end=self._on_drag_end,
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
        storage_ui.show_storage_status(self)

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
        self._hooks.schedule_dump(delay=100)

    def _motion_controller(self, on_enter, on_leave) -> Gtk.EventControllerMotion:
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda _controller, _x, _y: on_enter())
        motion.connect("leave", lambda _controller: on_leave())
        return motion

    def _on_deck_enter(self) -> None:
        if self._hooks.no_hover:
            return
        self.deck.hover_enter()

    def _on_deck_leave(self) -> None:
        if self._hooks.pin_deck:
            return
        # The strip and the panel are separate X windows. Crossing from one
        # into the other can deliver the enter of the new window *before* the
        # leave of the old one; treating that leave as "the pointer is gone"
        # schedules a collapse that nothing cancels, so the fan folds by
        # itself ~400 ms after the pointer moved onto it. Ask the server where
        # the pointer really is and cancel instead.
        #
        # Only while the fan is up: collapsing unmaps the panel with the
        # pointer still over its old rect, and that leave must stay a leave
        # (re-entering there would schedule an unwanted 120 ms re-expand).
        if self.state == STATE_FAN and self._pointer_over_deck():
            self.deck.hover_enter()
            return
        # Ticket 05: while an undo is available, unmapping the fan would take
        # the toast and its Undo button with it. Hide the peek, stay mapped.
        self.deck.hover_leave(allow_collapse=self._undo.pending is None)

    def _on_tab_enter(self, note_id: str) -> None:
        self.deck.hover_tab(note_id)
        # Test observability for the 150 ms crossing gap: the dump must show
        # that the previous peek stayed visible until the new one replaced it.
        self._hooks.schedule_dump(delay=20)

    def _on_tab_leave(self, note_id: str) -> None:
        self.deck.hover_tab_leave(note_id)

    def _on_drag_start(self, note_id: str) -> None:
        """The press crossed 5 px: this is a reorder, not a click.

        The state machine hides the in-fan peek and suppresses the hover-leave
        collapse for the rest of the gesture, so moving the pointer off the
        deck to aim cannot take the fan away.
        """
        self.deck.drag_begin()
        if self.panel is not None:
            self.panel.hide_peek()
        self._hooks.schedule_dump(delay=20)

    def _on_drag_update(self) -> None:
        # The target row changes while the pointer moves; the smoke test reads
        # it from the dump before releasing.
        self._hooks.schedule_dump(delay=20)

    def _on_drag_end(self) -> None:
        self.deck.drag_end()
        if not self._pointer_over_deck():
            # Released outside the deck: the reorder was cancelled by the fan,
            # and the pointer already left long ago, so start the normal
            # collapse countdown here (an undo toast still pins the panel).
            self.deck.hover_leave(allow_collapse=self._undo.pending is None)
        self._hooks.schedule_dump(delay=20)

    def deck_changed(self) -> None:
        """Refresh the smoke dump after a mutation.

        Called from every mutation path in this module (text, create, delete,
        undo, reorder) so the test snapshot never lags the deck.
        """
        self._hooks.schedule_dump(delay=100)

    def reorder_note(self, note_id: str, target_index: int) -> bool:
        """Move *note_id* to *target_index* and persist immediately (spec §4.4).

        The deck's order is the array itself (spec §5.1), so the whole operation
        is one pop and one insert. A target equal to the current index is a
        no-op: no save, no view rebuild, no event. Out-of-range targets clamp to
        the deck.

        Read-only and unconfirmed-corrupt decks still reorder in memory;
        ``_save_notes`` refuses the write and ticket 08's retry/banner rules
        keep applying. Widgets are rebuilt after the gesture has ended, never
        in the middle of it.
        """
        index = index_of(self.notes, note_id)
        if index == -1:
            return False
        target = max(0, min(int(target_index), len(self.notes) - 1))
        if target == index:
            return False

        note = self.notes.pop(index)
        self.notes.insert(target, note)
        self._save_notes()
        self.deck_changed()
        if self.panel is not None:
            # Same array order in the fan and the panel rail. Safe here only
            # because the drag callback schedules this after drag-end.
            self.panel.refresh_notes(self.notes, self.current_id)
        return True

    def _xid(self, window: Gtk.Window) -> int | None:
        surface = window.get_surface()
        if surface is None:
            return None
        return GdkX11.X11Surface.get_xid(surface)

    def _on_strip_map(self, *_args) -> None:
        # Mutter applies its own state and WM_HINTS when the window maps, so
        # the hints set before mapping are not enough. Re-assert them after
        # the window is viewable, then settle the exact X11 rect.
        self._placement.settle_strip()
        GLib.timeout_add(50, self._placement.settle_strip)

    def _on_panel_map(self, *_args) -> None:
        # Every hover remap drops _NET_WM_STATE, _NET_WM_DESKTOP, WM_HINTS and
        # the position (PLATFORM §2). Re-applying here — not only at startup —
        # is what keeps the fan above, sticky and input-less after a collapse.
        self._placement.settle_panel()
        GLib.timeout_add(50, self._placement.settle_panel)
        self._hooks.schedule_dump(delay=60)

    def _show_panel(self) -> None:
        """Map the fan without focus: never ``present()`` for hover (§7.4)."""
        if self.panel is None:
            return
        self.panel.set_visible(True)
        self._maybe_show_onboarding()
        self._hooks.schedule_dump(delay=30)

    def _hide_panel(self) -> None:
        if self.panel is None:
            return
        if self._focus_guard is not None:
            self._focus_guard.clear()
        self._set_focus_hint(False)
        # The search belongs to one visible fan: collapsing clears it so the
        # next hover starts with the whole deck.
        self.panel.reset_search()
        # Focus may have been granted to the search box. Hand the window back
        # to input-less before it unmaps, so the next hover map cannot steal
        # the keyboard (spec §9.1).
        xid = self._xid(self.panel)
        if xid is not None and self.x11 is not None:
            self.x11.set_input(xid, False)
            self.x11.set_no_focus(xid)
        self.panel.set_visible(False)
        self._hooks.schedule_dump(delay=30)

    def _show_peek(self, note_id: str) -> None:
        if self.panel is None or self.state != STATE_FAN:
            return
        note = find_note(self.notes, note_id)
        if note is None:
            return
        self.panel.show_peek(note_id, note.preview())
        self._hooks.schedule_dump(delay=30)

    def _hide_peek(self) -> None:
        if self.panel is not None:
            self.panel.hide_peek()
        self._hooks.schedule_dump(delay=20)

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
        self._hooks.schedule_dump(delay=30)

    def command_new(self) -> bool:
        """``lurknotes new``: create and open a note, or reuse the untouched one.

        Ticket 08 gate: a read-only or unconfirmed-corrupt deck must surface
        its banner instead of silently doing nothing. ``all`` still works.
        """
        if self.read_only or self.overwrite_blocked:
            self.expand_deck()
            storage_ui.show_storage_status(self)
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

    def new_note(self) -> None:
        """Create a note at the top of the deck and open it (spec §4.1)."""
        if self.read_only or self.overwrite_blocked:
            # Read-only and unconfirmed-corrupt files cannot accept new notes:
            # anything created now could never be saved. Surface the existing
            # ticket 08 banner instead of silently doing nothing.
            storage_ui.show_storage_status(self)
            return
        self._leave_current()
        note = Note.create()
        add_at_top(self.notes, note)
        self.session_ids.add(note.id)
        # Creation is in memory only (spec §5.2): the note is written by the
        # 400 ms debounce, a switch, close or shutdown. A crash right after
        # `lurknotes new` must not leave a permanent empty note behind.
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
        # The editor must map the panel before present() focuses it, even if
        # the deck was resting as a strip.
        if self.panel is not None:
            self.panel.set_visible(True)
            self._maybe_show_onboarding()
        self.panel.show_note(note, self.notes)
        self._activate_panel()
        self._hooks.schedule_dump()
        if self._hooks.type_text:
            GLib.timeout_add(600, self._hooks.maybe_type)

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
        self._hooks.schedule_dump()

    def collapse_deck(self) -> None:
        """Collapse fan -> strip from the header ``»`` (no focus needed).

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
            self._hooks.schedule_dump(delay=30)

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
        if self._hooks.refuse_focus:
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
        self._hooks.schedule_dump(delay=30)

    def _on_panel_active_changed(self, *_args) -> None:
        """Clear the hint when focus arrives a little later than 150 ms."""
        if self.panel is None or self.x11 is None:
            return
        if self._hooks.refuse_focus:
            return
        if not self.panel.is_active():
            return
        if not self._panel_has_focus():
            return
        if self._focus_guard is not None:
            self._focus_guard.focus_arrived()
        self._set_focus_hint(False)
        self._hooks.schedule_dump(delay=30)

    def _grant_search_focus(self) -> bool:
        """Click / Ctrl+F in the fan: take input and focus the search box.

        The fan maps input-less for hover (spec §9.1), so typing into the
        search box is possible only after this explicit grant. ``Ctrl+F`` is
        handled only where the deck already has the keyboard; an open note
        keeps its editor focused and the hidden fan never steals the key.
        """
        if self.panel is None or self.state == STATE_OPEN:
            return False
        if self._focus_guard is not None:
            self._focus_guard.clear()
        self._set_focus_hint(False)
        xid = self._xid(self.panel)
        if xid is not None and self.x11 is not None:
            self.x11.set_input(xid, True)
            self.x11.allow_focus(xid)
        self.panel.present()
        self.panel.focus_search()
        self._hooks.schedule_dump(delay=30)
        return True

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
        self._hooks.schedule_dump(delay=30)

    def _set_focus_hint(self, visible: bool) -> None:
        show = getattr(self.panel, "show_focus_hint", None)
        if show is not None:
            show(visible)

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
        self._hooks.schedule_dump(delay=30)

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
            self._hooks.schedule_dump()
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
        self._hooks.schedule_dump(delay=30)

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
