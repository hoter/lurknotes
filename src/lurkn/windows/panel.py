"""The deck's panel window: fan and note pages share one 380 px surface."""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Gdk, Gtk

from .. import strings
from ..notes import Note
from ..ui.fan import FanPage
from ..ui.note import NotePage
from ..ui.status import KIND_ERROR, StatusBanner

WIDTH = 380


class PanelWindow(Gtk.Window):
    def __init__(
        self,
        application: Gtk.Application,
        *,
        height: int,
        on_open: Callable[[str], None],
        on_close: Callable[[], None],
        on_new: Callable[[], None],
        on_cycle: Callable[[int], None],
        on_escape: Callable[[], bool],
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(application=application, title=strings.FAN_TITLE)
        self.on_escape = on_escape
        self.on_cycle = on_cycle
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WIDTH, height)
        self.add_css_class("lurk")
        self.add_css_class("panel")

        self.fan = FanPage(on_open, on_new)
        self.note = NotePage(on_close, on_open, on_changed)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.add_named(self.fan, "fan")
        self.stack.add_named(self.note, "note")
        self.stack.set_visible_child_name("fan")

        # The status banner sits above both pages: recovery warnings and
        # "Save failed" must be visible in the fan and in the editor.
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.status = StatusBanner()
        outer.append(self.status)
        outer.append(self.stack)
        self.set_child(outer)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

    def show_fan(self, notes: Sequence[Note]) -> None:
        self.set_title(strings.FAN_TITLE)
        self.fan.set_notes(notes)
        self.stack.set_visible_child_name("fan")

    def show_note(self, note: Note, notes: Sequence[Note]) -> None:
        self.set_title(strings.NOTE_TITLE)
        self.fan.set_notes(notes)
        self.note.set_notes(notes, note.id)
        self.note.load(note)
        self.stack.set_visible_child_name("note")

    def refresh_notes(self, notes: Sequence[Note], active_id: str | None) -> None:
        self.fan.set_notes(notes)
        self.note.set_notes(notes, active_id)

    def show_save_failed(self, failed: bool) -> None:
        if failed:
            self.status.show(strings.SAVE_FAILED_RETRYING, kind=KIND_ERROR)
        else:
            self.status.clear()

    def show_status(self, message: str, **kwargs) -> None:
        self.status.show(message, **kwargs)

    def clear_status(self) -> None:
        self.status.clear()

    def status_snapshot(self) -> dict:
        return self.status.snapshot()

    def set_read_only(self, read_only: bool) -> None:
        self.note.text_view.set_editable(not read_only)

    def focus_editor(self) -> None:
        self.note.focus_editor()

    def tab_centers(self) -> list[list[float]]:
        # Window coordinates: the status banner may push the fan down.
        return self.fan.tab_centers(relative_to=self)

    def rail_centers(self) -> list[list[float]]:
        return self.note.rail_centers()

    def active_index(self) -> int:
        return self.note.active_index()

    def new_button_center(self) -> list[float] | None:
        return self.fan.new_button_center()

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            return self.on_escape()
        # Spec §7.3: Ctrl+Tab / Ctrl+Shift+Tab cycle notes. GTK reports
        # Shift+Tab as ISO_Left_Tab, so both keyvals mean "previous".
        if state & Gdk.ModifierType.CONTROL_MASK and keyval in (
            Gdk.KEY_Tab,
            Gdk.KEY_KP_Tab,
            Gdk.KEY_ISO_Left_Tab,
        ):
            previous = bool(state & Gdk.ModifierType.SHIFT_MASK) or (
                keyval == Gdk.KEY_ISO_Left_Tab
            )
            self.on_cycle(-1 if previous else 1)
            return True
        return False
