"""The peek: a read-only preview beside the hovered tab (spec §6.2).

A separate no-focus window instead of a ``Gtk.Popover``: popovers take
keyboard focus when they map (verified on this machine), which would break the
"hover never steals focus" rule. This window uses the same no-focus map as the
fan — ``_NET_WM_USER_TIME = 0`` + ``set_visible(True)``, never ``present()`` —
and is placed to the left of the deck so it never changes tab geometry.
"""

from __future__ import annotations

from typing import Sequence

from gi.repository import Gtk, Pango

from .. import strings

WIDTH = 300
LINE_HEIGHT = 18
PADDING = 24


class PeekWindow(Gtk.Window):
    """A small dark card with up to six body lines."""

    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application, title=strings.PEEK_TITLE)
        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("lurk")
        self.add_css_class("peek-window")
        self.lines: list[str] = []

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.add_css_class("peek-card")
        card.set_size_request(WIDTH, -1)
        self.card = card
        self.set_child(card)

    def show_lines(self, lines: Sequence[str]) -> None:
        while (child := self.card.get_first_child()) is not None:
            self.card.remove(child)
        self.lines = list(lines)
        for line in lines:
            label = Gtk.Label(label=line)
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.add_css_class("peek-line")
            self.card.append(label)

    def estimated_height(self) -> int:
        return PADDING + LINE_HEIGHT * max(1, len(self.lines))
