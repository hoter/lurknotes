"""X11/EWMH plumbing and the geometry math behind window placement.

GTK sizes and positions are logical pixels; X11 works in physical pixels.
Everything that crosses into Xlib therefore goes through :func:`strip_rect`.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from . import strings


@dataclass(frozen=True)
class Rect:
    """A rectangle. Used both for logical workareas and physical X11 rects."""

    x: int
    y: int
    width: int
    height: int


def strip_rect(workarea: Rect, scale: float, width: int) -> Rect:
    """Place a vertical strip against the right edge of *workarea*.

    The strip is top-aligned with the workarea (below the GNOME top bar) and
    flush with its right edge. ``workarea`` and ``width`` are logical pixels;
    the result is physical pixels for ``XMoveResizeWindow``.
    """
    return Rect(
        x=round((workarea.x + workarea.width) * scale) - round(width * scale),
        y=round(workarea.y * scale),
        width=round(width * scale),
        height=round(workarea.height * scale),
    )


class _ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class _Event(ctypes.Union):
    _fields_ = [("client", _ClientMessage), ("pad", ctypes.c_long * 24)]


class _WMHints(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_long),
        ("input", ctypes.c_int),
        ("initial_state", ctypes.c_int),
        ("icon_pixmap", ctypes.c_ulong),
        ("icon_window", ctypes.c_ulong),
        ("icon_x", ctypes.c_int),
        ("icon_y", ctypes.c_int),
        ("icon_mask", ctypes.c_ulong),
        ("window_group", ctypes.c_ulong),
    ]


_CLIENT_MESSAGE = 33
_XA_CARDINAL = 6
_INPUT_HINT = 1
_SUBSTRUCTURE_NOTIFY = 1 << 20
_SUBSTRUCTURE_REDIRECT = 1 << 19
_ALL_DESKTOPS = 0xFFFFFFFF

# Strip/panel windows must be above, sticky across desktops, and absent from
# the taskbar and pager. The panel will toggle these when it becomes editable.
_STRIP_STATES = (
    "_NET_WM_STATE_ABOVE",
    "_NET_WM_STATE_SKIP_TASKBAR",
    "_NET_WM_STATE_STICKY",
    "_NET_WM_STATE_SKIP_PAGER",
)


class X11:
    """A thin ctypes wrapper over the handful of Xlib calls LurkNotes needs."""

    def __init__(self) -> None:
        lib = ctypes.CDLL("libX11.so.6")
        self._lib = lib

        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._display = lib.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError(strings.NO_DISPLAY)

        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self._root = lib.XDefaultRootWindow(self._display)

        lib.XDisplayWidth.restype = ctypes.c_int
        lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.root_width = lib.XDisplayWidth(self._display, 0)

        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XMoveResizeWindow.restype = ctypes.c_int
        lib.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        lib.XSendEvent.restype = ctypes.c_int
        lib.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        lib.XQueryPointer.restype = ctypes.c_int
        lib.XQueryPointer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XFlush.restype = ctypes.c_int
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XSetWMHints.restype = ctypes.c_int
        lib.XSetWMHints.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_WMHints),
        ]
        lib.XChangeProperty.restype = ctypes.c_int
        lib.XChangeProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        lib.XDeleteProperty.restype = ctypes.c_int
        lib.XDeleteProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        lib.XCloseDisplay.restype = ctypes.c_int
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]

        self._atoms: dict[str, int] = {}

    def atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = self._lib.XInternAtom(
                self._display, name.encode(), 0
            )
        return self._atoms[name]

    def flush(self) -> None:
        self._lib.XFlush(self._display)

    def close(self) -> None:
        if self._display:
            self._lib.XCloseDisplay(self._display)
            self._display = None

    def move_resize(self, xid: int, rect: Rect) -> None:
        """Position an already-mapped window using physical X11 pixels."""
        self._lib.XMoveResizeWindow(
            self._display,
            xid,
            int(rect.x),
            int(rect.y),
            int(rect.width),
            int(rect.height),
        )
        self.flush()

    def _client_message(self, xid: int, message_type: int, data0: int, data1: int = 0) -> None:
        event = _Event()
        event.client.type = _CLIENT_MESSAGE
        event.client.send_event = 1
        event.client.display = self._display
        event.client.window = xid
        event.client.message_type = message_type
        event.client.format = 32
        event.client.data[0] = data0
        event.client.data[1] = data1
        mask = _SUBSTRUCTURE_NOTIFY | _SUBSTRUCTURE_REDIRECT
        self._lib.XSendEvent(
            self._display, self._root, 0, mask, ctypes.byref(event)
        )
        self.flush()

    def set_deck_hints(self, xid: int) -> None:
        """Ask the WM for above/sticky/out-of-taskbar and all desktops.

        Uses EWMH client messages rather than writing ``_NET_WM_STATE``
        directly: the WM owns that property. ``_NET_WM_DESKTOP = 0xFFFFFFFF``
        is the "all desktops" value (spec §9.1).
        """
        state = self.atom("_NET_WM_STATE")
        for prop in _STRIP_STATES:
            # data0 = _NET_WM_STATE_ADD, data1 = the state atom.
            self._client_message(xid, state, 1, self.atom(prop))
        self._client_message(xid, self.atom("_NET_WM_DESKTOP"), _ALL_DESKTOPS)

    def set_input(self, xid: int, enabled: bool) -> None:
        """Set ``WM_HINTS.input``.

        With input off the WM must not give the strip keyboard focus, so
        mapping it cannot interrupt typing in another window (spec §9.1).
        """
        hints = _WMHints()
        hints.flags = _INPUT_HINT
        hints.input = 1 if enabled else 0
        self._lib.XSetWMHints(self._display, xid, ctypes.byref(hints))
        self.flush()

    def set_no_focus(self, xid: int) -> None:
        """Set ``_NET_WM_USER_TIME = 0`` so mapping does not activate the window."""
        value = (ctypes.c_long * 1)(0)
        self._lib.XChangeProperty(
            self._display,
            xid,
            self.atom("_NET_WM_USER_TIME"),
            _XA_CARDINAL,
            32,
            0,
            ctypes.cast(value, ctypes.c_void_p),
            1,
        )
        self.flush()

    def allow_focus(self, xid: int) -> None:
        """Drop the user-time hint so ``present()`` may activate the window."""
        self._lib.XDeleteProperty(self._display, xid, self.atom("_NET_WM_USER_TIME"))
        self.flush()

    def pointer(self) -> tuple[int, int] | None:
        """Return the pointer position in root (physical X11) coordinates."""
        root_return = ctypes.c_ulong()
        child_return = ctypes.c_ulong()
        root_x, root_y, win_x, win_y = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        ok = self._lib.XQueryPointer(
            self._display,
            self._root,
            ctypes.byref(root_return),
            ctypes.byref(child_return),
            ctypes.byref(root_x),
            ctypes.byref(root_y),
            ctypes.byref(win_x),
            ctypes.byref(win_y),
            ctypes.byref(mask),
        )
        if not ok:
            return None
        return root_x.value, root_y.value
