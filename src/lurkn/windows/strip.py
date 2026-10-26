"""The strip: a narrow undecorated window parked at the edge of the screen."""

from __future__ import annotations

from gi.repository import Gdk, Gtk

from .. import strings

# Spec §6: 10 logical px wide.
WIDTH = 10

_CSS = ".strip { background-color: #24242c; }"


class StripWindow(Gtk.Window):
    """The always-visible handle the pointer grabs to unfold the deck."""

    def __init__(self, application: Gtk.Application, height: int) -> None:
        super().__init__(application=application, title=strings.STRIP_TITLE)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WIDTH, height)
        self.add_css_class("strip")

        box = Gtk.Box()
        box.add_css_class("strip")
        self.set_child(box)

        self._install_css()

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_string(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
