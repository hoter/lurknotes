"""Gtk.Application wiring for LurkNotes.

LurkNotes is intentionally an X11 client under XWayland: Mutter 46 does not
implement layer-shell, and only EWMH lets a window sit at the edge, above other
windows, outside the dock and on every workspace (spec §9.1).
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk

from .windows.strip import WIDTH as STRIP_WIDTH
from .windows.strip import StripWindow
from .x11 import Rect, X11, strip_rect

APP_ID = "dev.lurknotes.LurkNotes"

# Spec §13: a regular window starts below the GNOME top bar. Only used when
# Gdk.Monitor.get_workarea is unavailable.
_TOP_BAR_HEIGHT = 32


def _logical_workarea(monitor: Gdk.Monitor) -> Rect:
    get_workarea = getattr(monitor, "get_workarea", None)
    if get_workarea is not None:
        area = get_workarea()
        if area.width > 0 and area.height > 0:
            return Rect(area.x, area.y, area.width, area.height)

    geometry = monitor.get_geometry()
    return Rect(
        geometry.x,
        geometry.y,
        geometry.width,
        max(0, geometry.height - _TOP_BAR_HEIGHT),
    )


class LurkNotesApp(Gtk.Application):
    def __init__(self, action: str = "", x11: X11 | None = None) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        # new|all are accepted now and wired to deck actions in a later ticket.
        self.action = action
        self.x11 = x11
        self.strip: StripWindow | None = None
        self._workarea: Rect | None = None

    # -- lifecycle -----------------------------------------------------

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)

    def do_activate(self) -> None:
        if self.strip is None:
            self._build_strip()
        else:
            self.strip.set_visible(True)

    def do_shutdown(self) -> None:
        if self.x11 is not None:
            self.x11.close()
            self.x11 = None
        Gtk.Application.do_shutdown(self)

    # -- strip ---------------------------------------------------------

    def _build_strip(self) -> None:
        display = Gdk.Display.get_default()
        monitor = display.get_monitors().get_item(0)
        self._workarea = _logical_workarea(monitor)

        self.strip = StripWindow(self, self._workarea.height)

        # Realize, then mark the window as non-focusing *before* mapping it.
        # A window that maps with input=True would yank keyboard focus from
        # whatever the user is typing in.
        self.strip.realize()
        surface = self.strip.get_surface()
        if surface is None:
            raise RuntimeError("strip window was not realized")
        xid = GdkX11.X11Surface.get_xid(surface)
        self.x11.set_deck_hints(xid)
        self.x11.set_input(xid, False)
        self.x11.set_no_focus(xid)

        self.strip.connect("map", self._on_strip_map)
        self.strip.set_visible(True)

    def _on_strip_map(self, *_args) -> None:
        # Mutter applies its own state and WM_HINTS when the window maps, so
        # the hints set before mapping are not enough. Re-assert them after
        # the window is viewable, then settle the exact X11 rect.
        GLib.timeout_add(50, self._settle_strip)

    def _settle_strip(self) -> bool:
        if self.strip is None or self.x11 is None:
            return False
        surface = self.strip.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        self.x11.set_deck_hints(xid)
        self.x11.set_input(xid, False)
        self.x11.set_no_focus(xid)
        self._place_strip()
        return False

    def _place_strip(self) -> bool:
        if self.strip is None or self.x11 is None or self._workarea is None:
            return False
        surface = self.strip.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        rect = strip_rect(self._workarea, surface.get_scale(), STRIP_WIDTH)
        self.x11.move_resize(xid, rect)
        return False
