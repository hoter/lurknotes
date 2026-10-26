"""The strip: a narrow undecorated window parked at the edge of the screen.

It stays a thin wrapper on purpose: hover controllers, X11 hints and exact
placement are deck-wide policies owned by the app/placement helper, so putting
them here would only hide that coupling.
"""

from __future__ import annotations

from gi.repository import Gtk

from .. import strings

# Spec §6: 10 logical px wide.
WIDTH = 10


class StripWindow(Gtk.Window):
    """The always-visible strip the pointer grabs to unfold the deck."""

    def __init__(self, application: Gtk.Application, height: int) -> None:
        super().__init__(application=application, title=strings.STRIP_TITLE)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WIDTH, height)
        self.add_css_class("strip")

        box = Gtk.Box()
        box.add_css_class("strip")
        self.set_child(box)
