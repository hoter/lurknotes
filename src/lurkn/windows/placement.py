"""Strip/panel placement and the post-map X11 settle pass.

Mutter applies its own state and WM hints when an X11 window maps, so the
hints set before mapping are not enough (PLATFORM §2). This helper owns the
"re-assert hints, then move to the exact physical rectangle" step for both
deck windows, keeping that mechanical code out of the application wiring.

``Placement`` is constructed with the app and reads its ``strip``, ``panel``,
``x11``, ``workarea`` and ``state`` at call time; it keeps no window state of
its own.
"""

from __future__ import annotations

from gi.repository import Gdk, GdkX11

from ..deck import STATE_OPEN
from ..x11 import Rect, panel_rect, strip_rect
from .panel import WIDTH as PANEL_WIDTH
from .strip import WIDTH as STRIP_WIDTH

# Spec §13: a regular window starts below the GNOME top bar. Only used when
# Gdk.Monitor.get_workarea is unavailable.
_TOP_BAR_HEIGHT = 32


def logical_workarea(monitor: Gdk.Monitor) -> Rect:
    """The monitor workarea in logical pixels, minus the top bar if needed."""
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


class Placement:
    """Place the strip and panel and re-apply their X11 hints after a map."""

    def __init__(self, app) -> None:
        self.app = app

    def settle_strip(self) -> bool:
        app = self.app
        if app.strip is None or app.x11 is None:
            return False
        xid = _xid(app.strip)
        if xid is None:
            return False
        app.x11.set_deck_hints(xid)
        app.x11.set_input(xid, False)
        app.x11.set_no_focus(xid)
        self.place_strip()
        return False

    def settle_panel(self) -> bool:
        app = self.app
        if app.panel is None or app.x11 is None:
            return False
        xid = _xid(app.panel)
        if xid is None:
            return False
        app.x11.set_deck_hints(xid)
        app.x11.set_input(xid, app.state == STATE_OPEN)
        if app.state != STATE_OPEN:
            app.x11.set_no_focus(xid)
        self.place_panel()
        return False

    def place_strip(self) -> bool:
        app = self.app
        if app.strip is None or app.x11 is None or app._workarea is None:
            return False
        surface = app.strip.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        rect = strip_rect(app._workarea, surface.get_scale(), STRIP_WIDTH)
        app.x11.move_resize(xid, rect)
        return False

    def place_panel(self) -> bool:
        app = self.app
        if app.panel is None or app.x11 is None or app._workarea is None:
            return False
        surface = app.panel.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        rect = panel_rect(
            app._workarea,
            surface.get_scale(),
            PANEL_WIDTH,
            STRIP_WIDTH,
        )
        app.x11.move_resize(xid, rect)
        return False


def _xid(window) -> int | None:
    surface = window.get_surface()
    if surface is None:
        return None
    return GdkX11.X11Surface.get_xid(surface)
