"""The fan: tabs for every note, in array order (spec §6.2)."""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Gtk, Pango

from .. import strings
from ..notes import Note


class FanPage(Gtk.Box):
    """Read-only list of note tabs. Clicking a tab opens its note."""

    def __init__(self, on_open: Callable[[str], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_open = on_open
        self.add_css_class("fan")
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(10)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label=strings.NOTES_HEADER)
        title.set_xalign(0)
        title.set_hexpand(True)
        title.add_css_class("header")
        header.append(title)
        self.append(header)

        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.set_child(self.rows)
        self.append(scroller)

    def set_notes(self, notes: Sequence[Note]) -> None:
        while (child := self.rows.get_first_child()) is not None:
            self.rows.remove(child)

        if not notes:
            empty = Gtk.Label(label=strings.NO_NOTES)
            empty.set_xalign(0)
            empty.add_css_class("empty")
            self.rows.append(empty)
            return

        for note in notes:
            button = Gtk.Button()
            button.add_css_class("tab")
            label = Gtk.Label(label=note.title() or strings.UNTITLED)
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            button.set_child(label)
            button.connect(
                "clicked", lambda _button, note_id=note.id: self._on_open(note_id)
            )
            self.rows.append(button)

    def tab_centers(self) -> list[list[float]]:
        """Tab centres in this page's logical coordinates; used by the smoke test."""
        centers: list[list[float]] = []
        child = self.rows.get_first_child()
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
