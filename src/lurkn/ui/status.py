"""Non-modal storage status banner (spec §5.3, §10).

The banner lives at the top of the deck panel, above both the fan and the note
editor, so a recovery warning or "Save failed" is visible wherever the user is.
It never blocks startup and never opens a modal dialog.
"""

from __future__ import annotations

from typing import Callable

from gi.repository import Gtk

from .. import strings

KIND_ERROR = "error"
KIND_WARNING = "warning"


class StatusBanner(Gtk.Box):
    """One line of status text plus an optional action and dismiss button."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("status-banner")
        self.set_visible(False)
        self._kind = ""
        self._message = ""
        self._action: Callable[[], None] | None = None

        self.label = Gtk.Label()
        self.label.set_wrap(True)
        self.label.set_xalign(0.0)
        self.label.set_hexpand(True)
        self.label.add_css_class("status-text")
        self.append(self.label)

        self.action_button = Gtk.Button()
        self.action_button.set_visible(False)
        self.action_button.add_css_class("status-action")
        self.action_button.connect("clicked", self._on_action_clicked)
        self.append(self.action_button)

        self.close_button = Gtk.Button(label=strings.CLOSE)
        self.close_button.set_tooltip_text(strings.STATUS_DISMISS)
        self.close_button.set_visible(False)
        self.close_button.add_css_class("status-close")
        self.close_button.connect("clicked", lambda _button: self.clear())
        self.append(self.close_button)

    def show(
        self,
        message: str,
        *,
        kind: str = KIND_ERROR,
        action_label: str | None = None,
        on_action: Callable[[], None] | None = None,
        dismissible: bool = False,
    ) -> None:
        self._kind = kind
        self._message = message
        self._action = on_action
        self.label.set_text(message)
        self.remove_css_class("status-error")
        self.remove_css_class("status-warning")
        self.add_css_class("status-error" if kind == KIND_ERROR else "status-warning")

        if action_label is None:
            self.action_button.set_visible(False)
        else:
            self.action_button.set_label(action_label)
            self.action_button.set_visible(True)
        self.close_button.set_visible(dismissible)
        self.set_visible(True)

    def clear(self) -> None:
        self._kind = ""
        self._message = ""
        self._action = None
        self.label.set_text("")
        self.action_button.set_visible(False)
        self.close_button.set_visible(False)
        self.set_visible(False)

    def snapshot(self) -> dict:
        """Test hook for ``LURKNOTES_TEST_DUMP``."""
        action_center = None
        if self.action_button.get_visible():
            root = self.get_root()
            if root is not None:
                found, bounds = self.action_button.compute_bounds(root)
                if found:
                    action_center = [
                        bounds.get_x() + bounds.get_width() / 2,
                        bounds.get_y() + bounds.get_height() / 2,
                    ]
        return {
            "visible": self.get_visible(),
            "kind": self._kind,
            "message": self._message,
            "action": self.action_button.get_visible(),
            "action_label": (
                self.action_button.get_label()
                if self.action_button.get_visible()
                else ""
            ),
            "action_center": action_center,
            "dismissible": self.close_button.get_visible(),
        }

    def _on_action_clicked(self, _button: Gtk.Button) -> None:
        action, self._action = self._action, None
        self.clear()
        if action is not None:
            action()
