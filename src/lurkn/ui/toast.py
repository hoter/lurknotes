"""The delete-undo toast (spec §4.5, §6.3).

It is an overlay child of the panel window, not of the fan or note page, so
rebuilding the tabs for an autosave cannot remove it. The app owns the timer;
this widget only shows the message, the Undo button and its geometry.
"""

from __future__ import annotations

from typing import Callable

from gi.repository import Gtk

from .. import strings


class UndoToast(Gtk.Box):
    """Centered at the bottom of the panel with the Undo button."""

    def __init__(self, on_undo: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.add_css_class("undo-toast")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_margin_bottom(12)
        self.set_visible(False)

        self.label = Gtk.Label(label=strings.UNDO_TOAST)
        self.label.add_css_class("undo-text")
        self.append(self.label)

        self.button = Gtk.Button(label=strings.UNDO)
        self.button.add_css_class("undo-button")
        self.button.set_tooltip_text(strings.UNDO_HINT)
        self.button.connect("clicked", lambda _button: on_undo())
        self.append(self.button)

    def reveal(self) -> None:
        self.set_visible(True)

    def conceal(self) -> None:
        self.set_visible(False)

    def snapshot(self, relative_to: Gtk.Widget | None = None) -> dict:
        """Test hook for ``LURKNOTES_TEST_DUMP``: visibility and click target."""
        root = relative_to if relative_to is not None else self.get_root()
        bounds = None
        button_center = None
        if self.get_visible() and root is not None:
            found, rect = self.compute_bounds(root)
            if found:
                bounds = [
                    rect.get_x(),
                    rect.get_y(),
                    rect.get_width(),
                    rect.get_height(),
                ]
            found, rect = self.button.compute_bounds(root)
            if found:
                button_center = [
                    rect.get_x() + rect.get_width() / 2,
                    rect.get_y() + rect.get_height() / 2,
                ]
        return {
            "visible": self.get_visible(),
            "label": self.label.get_text(),
            "bounds": bounds,
            "button_center": button_center,
        }
