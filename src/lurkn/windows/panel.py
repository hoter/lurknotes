"""The deck's panel window: fan and note pages share one 380 px surface."""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Gdk, Gtk

from .. import strings
from ..notes import Note
from ..ui.fan import FanPage
from ..ui.note import NotePage
from ..ui.status import KIND_ERROR, StatusBanner
from ..ui.toast import UndoToast

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
        on_collapse: Callable[[], None],
        on_hover_tab: Callable[[str], None],
        on_leave_tab: Callable[[str], None],
        on_scrolled: Callable[[], None],
        on_delete: Callable[[], bool],
        on_undo: Callable[[], bool],
        on_reorder: Callable[[str, int], None],
        on_drag_begin: Callable[[str], None],
        on_drag_update: Callable[[], None],
        on_drag_end: Callable[[], None],
    ) -> None:
        super().__init__(application=application, title=strings.FAN_TITLE)
        self.on_escape = on_escape
        self.on_cycle = on_cycle
        self.on_delete = on_delete
        self.on_undo = on_undo
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WIDTH, height)
        self.add_css_class("lurk")
        self.add_css_class("panel")

        self.fan = FanPage(
            on_open=on_open,
            on_new=on_new,
            on_collapse=on_collapse,
            on_hover_tab=on_hover_tab,
            on_leave_tab=on_leave_tab,
            on_reorder=on_reorder,
            on_scrolled=on_scrolled,
            on_drag_begin=on_drag_begin,
            on_drag_update=on_drag_update,
            on_drag_end=on_drag_end,
        )
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

        # The toast overlays the whole panel, so it stays put in the fan and
        # in the editor and survives any fan/rail rebuild on autosave.
        self.toast = UndoToast(self._on_undo_clicked)
        overlay = Gtk.Overlay()
        overlay.set_child(outer)
        overlay.add_overlay(self.toast)
        self.set_child(overlay)

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

    def show_toast(self) -> None:
        self.toast.reveal()

    def hide_toast(self) -> None:
        self.toast.conceal()

    def toast_snapshot(self) -> dict:
        return self.toast.snapshot()

    def _on_undo_clicked(self) -> None:
        self.on_undo()

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

    def collapse_button_center(self) -> list[float] | None:
        return self.fan.collapse_button_center()

    def tab_center(self, note_id: str) -> list[float] | None:
        return self.fan.tab_center(note_id, relative_to=self)

    def show_peek(self, note_id: str, lines: Sequence[str]) -> None:
        self.fan.show_peek(note_id, lines)

    def hide_peek(self) -> None:
        self.fan.hide_peek()

    def peek_snapshot(self) -> dict:
        return self.fan.peek_snapshot()

    def peek_center(self) -> list[float] | None:
        return self.fan.peek_center(relative_to=self)

    def tab_heights(self) -> list[int]:
        return self.fan.tab_heights()

    def tab_ids(self) -> list[str]:
        return self.fan.tab_ids()

    def tab_titles(self) -> list[str]:
        return self.fan.tab_titles()

    def tab_cursors(self) -> list[str | None]:
        return self.fan.tab_cursors()

    def drag_snapshot(self) -> dict:
        return self.fan.drag_snapshot()

    def rail_titles(self) -> list[str]:
        return self.note.rail_titles()

    def scroll_value(self) -> float:
        return self.fan.scroll_value()

    def scroll_by(self, delta: float) -> None:
        self.fan.scroll_by(delta)

    def activate_tab(self, note_id: str) -> None:
        self.fan.activate_tab(note_id)

    def activate_collapse(self) -> None:
        self.fan.activate_collapse()

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        control = bool(state & Gdk.ModifierType.CONTROL_MASK)
        # Spec §7.3: capture phase suppresses the TextView's own Ctrl+Backspace
        # word deletion and its default Ctrl+Z handling.
        if control and keyval == Gdk.KEY_BackSpace:
            return self.on_delete()
        if control and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            return self.on_undo()
        if keyval == Gdk.KEY_Escape:
            return self.on_escape()
        # Spec §7.3: Ctrl+Tab / Ctrl+Shift+Tab cycle notes. GTK reports
        # Shift+Tab as ISO_Left_Tab, so both keyvals mean "previous".
        if control and keyval in (
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
