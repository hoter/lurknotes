"""The visible "Click to type" hint shown when focus was refused (spec §9.5).

A ``Gtk.Button`` on purpose: the first click on an unfocused, input-less panel
must both take keyboard focus and be discoverable. The app grants focus in the
button handler.
"""

from __future__ import annotations

from typing import Callable

from gi.repository import Gtk

from .. import strings


class FocusHint(Gtk.Button):
    def __init__(self, on_click: Callable[[], None]) -> None:
        super().__init__(label=strings.CLICK_TO_TYPE)
        self.add_css_class("focus-hint")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.START)
        self.set_margin_top(12)
        self.set_visible(False)
        self._on_click = on_click
        self.connect("clicked", self._on_clicked)

    def _on_clicked(self, _button: Gtk.Button) -> None:
        self._on_click()

    def center(self, relative_to: Gtk.Widget) -> list[float] | None:
        found, bounds = self.compute_bounds(relative_to)
        if not found:
            return None
        return [
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
        ]

    def snapshot(self, relative_to: Gtk.Widget) -> dict:
        return {
            "visible": self.get_visible(),
            "text": self.get_label(),
            "center": self.center(relative_to) if self.get_visible() else None,
        }
