"""The note panel: a 112 px tab rail plus the plain-text editor (spec §6.3)."""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Gtk, Pango

from .. import strings
from ..notes import Note

RAIL_WIDTH = 112


class NotePage(Gtk.Box):
    """Editor page. The app owns the buffer's persistence, not this widget."""

    def __init__(
        self,
        on_close: Callable[[], None],
        on_open: Callable[[str], None],
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._on_open = on_open
        self._on_changed = on_changed
        self._loading = False
        self.add_css_class("note-page")

        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        rail.add_css_class("rail")
        rail.set_size_request(RAIL_WIDTH, -1)
        rail.set_vexpand(True)
        self.rail = rail

        close = Gtk.Button(label=strings.CLOSE)
        close.set_tooltip_text(strings.CLOSE_NOTE)
        close.set_halign(Gtk.Align.START)
        close.set_margin_start(6)
        close.set_margin_end(6)
        close.connect("clicked", lambda _button: on_close())
        rail.append(close)

        self.rail_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.rail_rows.set_margin_start(6)
        self.rail_rows.set_margin_end(6)
        rail_scroller = Gtk.ScrolledWindow()
        rail_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        rail_scroller.set_vexpand(True)
        rail_scroller.set_child(self.rail_rows)
        rail.append(rail_scroller)
        self.append(rail)

        editor_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        editor_column.add_css_class("editor-column")
        editor_column.set_hexpand(True)

        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_left_margin(14)
        self.text_view.set_right_margin(14)
        self.text_view.set_top_margin(12)
        self.text_view.set_bottom_margin(12)
        self.text_view.add_css_class("editor")
        self.buffer = self.text_view.get_buffer()
        self.buffer.connect("changed", self._on_buffer_changed)

        text_scroller = Gtk.ScrolledWindow()
        text_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_scroller.set_hexpand(True)
        text_scroller.set_vexpand(True)
        text_scroller.set_child(self.text_view)
        editor_column.append(text_scroller)
        self.append(editor_column)

    def set_notes(self, notes: Sequence[Note], active_id: str | None) -> None:
        while (child := self.rail_rows.get_first_child()) is not None:
            self.rail_rows.remove(child)

        for note in notes:
            button = Gtk.Button()
            if note.id == active_id:
                button.add_css_class("active")
            label = Gtk.Label(label=note.title())
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            button.set_child(label)
            button.connect(
                "clicked", lambda _button, note_id=note.id: self._on_open(note_id)
            )
            self.rail_rows.append(button)

    def load(self, note: Note) -> None:
        self._loading = True
        try:
            self.buffer.set_text(note.text)
            if note.text:
                # Spec §8: an existing note opens with the caret at the end. A
                # plain place_cursor leaves a long note scrolled to the top.
                self.buffer.place_cursor(self.buffer.get_end_iter())
                self.text_view.scroll_to_mark(
                    self.buffer.get_insert(), 0.0, False, 0.0, 0.0
                )
            else:
                # Spec §8: a new note opens with the caret in the empty field.
                self.buffer.place_cursor(self.buffer.get_start_iter())
        finally:
            self._loading = False

    def insert_at_cursor(self, text: str) -> None:
        """Insert text as if typed; the changed signal starts autosave."""
        insert = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        self.buffer.insert(insert, text)
        self.buffer.place_cursor(self.buffer.get_end_iter())

    def text(self) -> str:
        return self.buffer.get_text(
            self.buffer.get_start_iter(), self.buffer.get_end_iter(), False
        )

    def rail_width(self) -> int:
        return self.rail.get_width()

    def rail_centers(self) -> list[list[float]]:
        """Note-tab centres in panel coordinates; used by the smoke test."""
        centers: list[list[float]] = []
        child = self.rail_rows.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                found, bounds = child.compute_bounds(self)
                if found:
                    centers.append(
                        [
                            bounds.get_x() + bounds.get_width() / 2,
                            bounds.get_y() + bounds.get_height() / 2,
                        ]
                    )
            child = child.get_next_sibling()
        return centers

    def active_index(self) -> int:
        """Rail row of the highlighted tab, or -1 (spec §6.3).

        Highlighting is keyed by note id, not by title, so duplicate titles
        can never move the marker to the wrong row.
        """
        index = 0
        child = self.rail_rows.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                if child.has_css_class("active"):
                    return index
                index += 1
            child = child.get_next_sibling()
        return -1

    def cursor_offset(self) -> int:
        return self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()

    def cursor_at_end(self) -> bool:
        return self.cursor_offset() == self.buffer.get_char_count()

    def focus_editor(self) -> None:
        self.text_view.grab_focus()

    def _on_buffer_changed(self, _buffer: Gtk.TextBuffer) -> None:
        if not self._loading:
            self._on_changed()
