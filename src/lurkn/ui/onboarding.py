"""One-time hotkey onboarding banner (spec §4.6, §9.2).

Non-modal: it sits above the fan/editor with a dismiss button and never blocks
typing or hover. The app writes the ``onboarded`` marker when this widget is
first shown, not at process start, so a strip-only autostart does not consume
the hint before the user has seen the deck.
"""

from __future__ import annotations

from gi.repository import Gtk

from .. import strings


class OnboardingHint(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("onboarding")
        self.set_visible(False)
        # A fixed height keeps GTK from oscillating between the wrapped
        # label's height-for-width and its natural minimum (which floods the
        # console with "minimum height ... for width" criticals).
        self.set_size_request(-1, 64)

        text = Gtk.Label(label=strings.ONBOARDING_TEXT)
        text.set_xalign(0.0)
        text.set_wrap(True)
        text.set_hexpand(True)
        text.add_css_class("onboarding-text")
        self.text = text
        self.append(text)

        dismiss = Gtk.Button(label=strings.ONBOARDING_DISMISS)
        dismiss.add_css_class("onboarding-dismiss")
        dismiss.set_valign(Gtk.Align.CENTER)
        dismiss.connect("clicked", lambda _button: self.set_visible(False))
        self.dismiss = dismiss
        self.append(dismiss)

    def center(self, relative_to: Gtk.Widget) -> list[float] | None:
        found, bounds = self.compute_bounds(relative_to)
        if not found:
            return None
        return [
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
        ]

    def dismiss_center(self, relative_to: Gtk.Widget) -> list[float] | None:
        found, bounds = self.dismiss.compute_bounds(relative_to)
        if not found:
            return None
        return [
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
        ]

    def snapshot(self, relative_to: Gtk.Widget) -> dict:
        return {
            "visible": self.get_visible(),
            "text": self.text.get_text(),
            "center": self.center(relative_to) if self.get_visible() else None,
            "dismiss_center": (
                self.dismiss_center(relative_to) if self.get_visible() else None
            ),
        }
