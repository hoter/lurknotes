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
from .notes import Note, find_note
from .store import Store, StoreError, UnsupportedVersion
from .ui import install as install_theme
from .windows.panel import WIDTH as PANEL_WIDTH
from .windows.panel import PanelWindow
from .windows.strip import WIDTH as STRIP_WIDTH
from .windows.strip import StripWindow
from .x11 import Rect, X11, panel_rect, strip_rect

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
        self.state = STATE_STRIP
        self.current_id: str | None = None
        self.save_source = 0
        self.read_only = False
        self.strip: StripWindow | None = None
        self.panel: PanelWindow | None = None
        self._workarea: Rect | None = None
        self._test_dump_path = os.environ.get("LURKNOTES_TEST_DUMP")
        self._test_type = os.environ.get("LURKNOTES_TEST_TYPE")
        self._test_typed = False

    # -- lifecycle -----------------------------------------------------

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        display = Gdk.Display.get_default()
        if display is not None:
            install_theme(display)
        self._load_notes()

    def do_activate(self) -> None:
        if self.strip is None:
            self._build_deck()
        else:
            self.strip.set_visible(True)
            if self.panel is not None:
                self.panel.set_visible(True)

    def do_shutdown(self) -> None:
        self._flush_current()
        if self.x11 is not None:
            self.x11.close()
            self.x11 = None
        Gtk.Application.do_shutdown(self)

    # -- data ----------------------------------------------------------

    def _load_notes(self) -> None:
        try:
            self.notes = self.store.load()
        except UnsupportedVersion as exc:
            # Read-only, never overwrite: the full recovery UI is ticket 08.
            self.read_only = True
            self.notes = []
            print(strings.ERROR.format(message=str(exc)), file=sys.stderr)
        except (StoreError, OSError) as exc:
            self.read_only = True
            self.notes = []
            print(strings.ERROR.format(message=str(exc)), file=sys.stderr)

    def _save_notes(self) -> bool:
        if self.read_only:
            return False
        try:
            self.store.save(self.notes)
        except (OSError, StoreError) as exc:
            # Retry policy and recovery modes are ticket 08; do not crash now.
            if self.panel is not None:
                self.panel.show_save_failed(True)
            print(strings.ERROR.format(message=str(exc)), file=sys.stderr)
            return False
        if self.panel is not None:
            self.panel.show_save_failed(False)
        self._schedule_test_dump()
        return True

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
            on_escape=self.on_escape,
            on_changed=self.on_text_changed,
        )
        self.panel.show_fan(self.notes)

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
        self.strip.set_visible(True)
        self.panel.set_visible(True)
        self.state = STATE_FAN

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

    def open_note(self, note_id: str) -> None:
        note = find_note(self.notes, note_id)
        if note is None:
            return
        if self.current_id == note.id and self.state == STATE_OPEN:
            self._activate_panel()
            return

        # Spec §5.2: switching notes writes the note being left.
        self._flush_current()
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
        self._flush_current()
        self.current_id = None
        self.state = STATE_FAN

        xid = self._xid(self.panel) if self.panel is not None else None
        if xid is not None and self.x11 is not None:
            self.x11.set_input(xid, False)
            self.x11.set_no_focus(xid)
        if self.panel is not None:
            self.panel.show_fan(self.notes)
        self._schedule_test_dump()

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
        if text == note.text:
            return
        note.text = text
        note.updated = time.time()
        self.panel.refresh_notes(self.notes, note.id)
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
            "titles": [note.title() or strings.UNTITLED for note in self.notes],
            "tab_centers": (
                self.panel.tab_centers() if state == STATE_FAN else []
            ),
            "text": self.panel.note.text() if is_open else None,
            "cursor_at_end": self.panel.note.cursor_at_end() if is_open else None,
            "rail_width": self.panel.note.rail_width() if is_open else None,
            "typed": self._test_typed,
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
