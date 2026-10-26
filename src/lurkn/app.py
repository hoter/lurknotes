"""Gtk.Application wiring for LurkNotes.

LurkNotes is intentionally an X11 client under XWayland: Mutter 46 does not
implement layer-shell, and only EWMH lets a window sit at the edge, above other
windows, outside the dock and on every workspace (spec §9.1).

The deck state machine is explicit: ``strip`` -> ``fan`` -> ``open``. Hover
timings, peek, drag reorder, delete/undo and All Notes belong to later tickets;
this module already owns the transitions that survive all of them.

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
``LURKNOTES_TEST_OPEN_ALL``
    Open All Notes once the deck is mapped. Ticket 09 will replace this with
    ``lurknotes all``; until then it lets the All Notes smoke test run.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk

from . import strings
from .events import DeckChanged
from .notes import (
    Note,
    add_at_top,
    cycle_id,
    discard_all_untouched,
    discard_if_untouched,
    find_note,
)
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

STATE_STRIP = "strip"
STATE_FAN = "fan"
STATE_OPEN = "open"

SAVE_DEBOUNCE_MS = 400

# Spec §13: a regular window starts below the GNOME top bar. Only used when
# Gdk.Monitor.get_workarea is unavailable.
_TOP_BAR_HEIGHT = 32


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
        action: str = "",
        x11: X11 | None = None,
        store: Store | None = None,
    ) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        # new|all are accepted now and wired to deck actions in a later ticket.
        self.action = action
        self.x11 = x11
        self.store = store or Store()
        self.notes: list[Note] = []
        # Untouched-note deletion requires knowing which notes this process
        # created. A loaded empty note has the same timestamps as a fresh one,
        # so timestamps alone must never decide it (spec §5.4).
        self.session_ids: set[str] = set()
        self.shutdown_done = False
        self.state = STATE_STRIP
        self.current_id: str | None = None
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
        # polling. Tickets 05 (delete/undo) and 06 (reorder) call
        # ``deck_changed()`` from their mutation paths too.
        self.deck_changed_event = DeckChanged()
        self._workarea: Rect | None = None
        self._retrier = Retrier(
            self._retry_save,
            schedule=GLib.timeout_add,
            cancel=GLib.source_remove,
        )
        self._test_dump_path = os.environ.get("LURKNOTES_TEST_DUMP")
        self._test_type = os.environ.get("LURKNOTES_TEST_TYPE")
        self._test_typed = False
        self._test_open_all = os.environ.get("LURKNOTES_TEST_OPEN_ALL") == "1"

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
        self._load_notes()

    def do_activate(self) -> None:
        if self.strip is None:
            self._build_deck()
        else:
            self.strip.set_visible(True)
            if self.panel is not None:
                self.panel.set_visible(True)

    def do_shutdown(self) -> None:
        # Ticket 03: flush, drop untouched session notes, save once. Ticket 08:
        # no retry timer may outlive the main loop.
        self._shutdown_deck()
        self.deck_changed_event.clear()
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
        )
        self.panel.show_fan(self.notes)
        self.panel.set_read_only(self.read_only)
        self._show_storage_status()

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
        self.strip.set_visible(True)
        self.panel.set_visible(True)
        self.state = STATE_FAN
        if self._test_open_all:
            GLib.timeout_add(250, self._open_all_notes_for_test)

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
        self._schedule_test_dump(delay=100)

    def _on_all_notes_map(self, *_args) -> None:
        # GNOME places a plain X11 window at the workarea corner. Spec §6 says
        # All Notes opens centred; wait for GTK's shadow extents, then move it.
        if not self._all_notes_placed:
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
        if extents == (0, 0, 0, 0) and self._all_notes_place_tries < 5:
            # GTK may set _GTK_FRAME_EXTENTS a frame after the map.
            self._all_notes_place_tries += 1
            GLib.timeout_add(50, self._place_all_notes)
            return False
        x, y = centered_position(
            self._workarea,
            surface.get_scale(),
            width,
            height,
            extents,
        )
        self.x11.move(xid, x, y)
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

        Called from every mutation path in this module. Ticket 05's delete and
        ticket 06's reorder must call this after they touch ``self.notes`` so
        All Notes stays in sync without a reopen.
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
        GLib.timeout_add(50, self._settle_strip)

    def _on_panel_map(self, *_args) -> None:
        GLib.timeout_add(50, self._settle_panel)
        self._schedule_test_dump(delay=250)

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

    def new_note(self) -> None:
        """Create a note at the top of the deck and open it (spec §4.1)."""
        if self.read_only or self.overwrite_blocked:
            # Read-only and unconfirmed-corrupt files cannot accept new notes:
            # anything created now could never be saved.
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
        self.state = STATE_OPEN
        self.panel.show_note(note, self.notes)
        self._activate_panel()
        self._schedule_test_dump()
        if self._test_type:
            GLib.timeout_add(600, self._maybe_test_type)

    def close_note(self) -> None:
        if self.state != STATE_OPEN:
            return
        self._leave_current()
        self.state = STATE_FAN

        xid = self._xid(self.panel) if self.panel is not None else None
        if xid is not None and self.x11 is not None:
            self.x11.set_input(xid, False)
            self.x11.set_no_focus(xid)
        if self.panel is not None:
            self.panel.show_fan(self.notes)
        self._schedule_test_dump()

    def cycle_note(self, step: int) -> None:
        """Open the note *step* places away, wrapping (spec §7.3)."""
        target_id = cycle_id(self.notes, self.current_id, step)
        if target_id is not None:
            self.open_note(target_id)

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
        # Spec §7.3: Esc closes the note when the panel has focus. Collapsing
        # fan -> strip arrives with the hover lifecycle ticket.
        if self.state == STATE_OPEN:
            self.close_note()
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

    def _flush_current(self) -> None:
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
        if changed or self.unsaved:
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
        snapshot = {
            "state": state,
            "current_id": self.current_id,
            "ids": [note.id for note in self.notes],
            "titles": [note.title() for note in self.notes],
            "tab_centers": (
                self.panel.tab_centers() if state == STATE_FAN else []
            ),
            "new_button_center": (
                self.panel.new_button_center() if state == STATE_FAN else None
            ),
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
