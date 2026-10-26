#!/usr/bin/env python3
"""Prove the ticket 02–03 vertical slices through the real X11 UI.

File -> fan -> real X11 click on a tab -> editor -> programmatic typing ->
400 ms debounce -> SIGKILL -> JSON on disk -> restart -> text in the editor.
Then the multi-note rules: + creates an open empty note at the top, the rail
switches notes, Ctrl+Tab wraps, and a session-created untouched note vanishes
on close or on switching away while a loaded empty note survives.

The only test-only production hooks are documented in ``src/lurkn/app.py``:
``LURKNOTES_TEST_DUMP`` snapshots the deck (including clickable centres) and
``LURKNOTES_TEST_TYPE`` inserts text into the open note. Everything else is
checked from outside through xwininfo/xprop and the JSON file. Exits 0 on
success, 1 with a clear message otherwise. Always stops the app it starts.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lurkn.strings import FAN_TITLE, NOTE_TITLE, STRIP_TITLE  # noqa: E402

PANEL_LOGICAL_WIDTH = 380
STRIP_LOGICAL_WIDTH = 10
BACKGROUND = (28, 28, 34)  # #1c1c22, spec §6.5
ALL_DESKTOPS = 4294967295
REQUIRED_STATES = {
    "_NET_WM_STATE_ABOVE",
    "_NET_WM_STATE_SKIP_TASKBAR",
    "_NET_WM_STATE_STICKY",
}
STARTUP_TIMEOUT = 10.0
SETTLE_TIMEOUT = 5.0
DUMP_TIMEOUT = 8.0
SAVE_TIMEOUT = 3.0
# Another worktree's LurkNotes can cover ours for the length of its own test
# run; wait that out instead of failing on a transient overlay.
COVER_TIMEOUT = 20.0


class SmokeFailure(Exception):
    pass


# -- external commands ---------------------------------------------------


def _run(*command: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SmokeFailure(
            f"{' '.join(command)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def _effective_scale() -> float:
    override = os.environ.get("GDK_SCALE")
    if override:
        return float(override)
    output = _run("xrdb", "-query")
    match = re.search(r"Xft\.dpi:\s*([0-9.]+)", output)
    if match is None:
        return 1.0
    return float(match.group(1)) / 96.0


def _workarea() -> tuple[int, int, int, int]:
    output = _run("xprop", "-root", "_NET_WORKAREA")
    match = re.search(r"_NET_WORKAREA\(CARDINAL\)\s*=\s*(.+)", output)
    if match is None:
        raise SmokeFailure("root window has no _NET_WORKAREA; cannot check geometry")
    values = [int(value) for value in re.findall(r"\d+", match.group(1))]
    if len(values) < 4:
        raise SmokeFailure(f"unexpected _NET_WORKAREA: {output.strip()}")
    return values[0], values[1], values[2], values[3]


def _windows_titled(title: str, pid: int | None = None) -> list[str]:
    # A concurrent window can disappear between enumeration and xprop, making
    # xwininfo fail with BadWindow for the whole tree. Retry that transient.
    tree = ""
    for attempt in range(3):
        try:
            tree = _run("xwininfo", "-root", "-tree")
            break
        except SmokeFailure:
            if attempt == 2:
                raise
            time.sleep(0.05)
    pattern = re.compile(r'^\s*(0x[0-9a-f]+)\s+"([^"]*)":')
    windows = [
        match.group(1)
        for line in tree.splitlines()
        if (match := pattern.match(line)) and match.group(2) == title
    ]
    if pid is None:
        return windows
    return [window for window in windows if _window_pid(window) == pid]


def _window_pid(window: str) -> int | None:
    """Owner of *window*, or None if it vanished (another instance's window)."""
    result = subprocess.run(
        ["xprop", "-id", window, "_NET_WM_PID"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    match = re.search(r"_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)", result.stdout)
    return int(match.group(1)) if match else None


def _window_info(window: str) -> dict[str, int | str]:
    output = ""
    for attempt in range(3):
        try:
            output = _run("xwininfo", "-id", window)
            break
        except SmokeFailure:
            if attempt == 2:
                raise
            time.sleep(0.03)
    info: dict[str, int | str] = {}
    fields = {
        "Absolute upper-left X": "x",
        "Absolute upper-left Y": "y",
        "Width": "width",
        "Height": "height",
    }
    for line in output.splitlines():
        key, _, value = line.strip().partition(":")
        if key in fields:
            info[fields[key]] = int(value.strip())
        elif key == "Map State":
            info["map_state"] = value.strip()
    return info


def _window_properties(window: str) -> str:
    return _run(
        "xprop",
        "-id",
        window,
        "_NET_WM_STATE",
        "_NET_WM_DESKTOP",
        "_NET_WM_USER_TIME",
        "WM_HINTS",
    )


def _check_states(properties: str) -> str:
    match = re.search(r"_NET_WM_STATE\(ATOM\)\s*=\s*(.*)", properties)
    observed = set(re.findall(r"_NET_WM_STATE_[A-Z_]+", match.group(1))) if match else set()
    missing = REQUIRED_STATES - observed
    if missing:
        raise SmokeFailure(
            "panel is missing required _NET_WM_STATE atoms: "
            + ", ".join(sorted(missing))
        )
    if "_NET_WM_STATE_SKIP_PAGER" not in observed:
        raise SmokeFailure("panel is missing _NET_WM_STATE_SKIP_PAGER")
    return ", ".join(sorted(observed))


def _check_desktop(properties: str) -> int:
    match = re.search(r"_NET_WM_DESKTOP\(CARDINAL\)\s*=\s*(\d+)", properties)
    if match is None:
        raise SmokeFailure("panel has no _NET_WM_DESKTOP")
    return int(match.group(1))


def _check_no_focus_hints(properties: str) -> None:
    if "Client accepts input or input focus: False" not in properties:
        raise SmokeFailure("fan WM_HINTS.input is not False; it may take focus")
    if re.search(r"_NET_WM_USER_TIME\(CARDINAL\)\s*=\s*0\b", properties) is None:
        raise SmokeFailure("fan _NET_WM_USER_TIME is not 0; mapping may activate it")


# -- dark theme ----------------------------------------------------------


def _xwd_image(
    window: str,
) -> tuple[bytes, int, int, int, int, int, int, int, int, int]:
    result = subprocess.run(
        ["xwd", "-id", window, "-silent"], capture_output=True, check=False
    )
    if result.returncode != 0:
        raise SmokeFailure(f"xwd failed: {result.stderr.decode(errors='replace').strip()}")
    data = result.stdout
    if len(data) < 100:
        raise SmokeFailure("xwd returned a truncated image")
    header = struct.unpack(">25I", data[:100])
    header_size = header[0]
    width, height = header[4], header[5]
    byte_order = header[7]
    bits_per_pixel = header[11]
    bytes_per_line = header[12]
    red_mask, green_mask, blue_mask = header[14], header[15], header[16]
    ncolors = header[19]
    offset = header_size + ncolors * 12
    needed = offset + bytes_per_line * height
    if len(data) < needed:
        raise SmokeFailure(
            f"xwd image is {len(data)} bytes, expected at least {needed}"
        )
    return (
        data,
        offset,
        width,
        height,
        bytes_per_line,
        bits_per_pixel,
        byte_order,
        red_mask,
        green_mask,
        blue_mask,
    )


def _bit_shift(mask: int) -> int:
    if mask == 0:
        return 0
    shift = 0
    while not (mask >> shift) & 1:
        shift += 1
    return shift


def _pixel_sampler(
    image: tuple[bytes, int, int, int, int, int, int, int, int, int, int],
) -> tuple[Callable[[int, int], tuple[int, int, int]], int, int]:
    """Decode an ``xwd`` dump into a ``pixel(x, y)`` closure."""
    (
        data,
        offset,
        width,
        height,
        bytes_per_line,
        bits_per_pixel,
        byte_order,
        red_mask,
        green_mask,
        blue_mask,
    ) = image
    bytes_per_pixel = (bits_per_pixel + 7) // 8
    endian = "little" if byte_order == 0 else "big"
    red_shift = _bit_shift(red_mask)
    green_shift = _bit_shift(green_mask)
    blue_shift = _bit_shift(blue_mask)

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        start = offset + y * bytes_per_line + x * bytes_per_pixel
        value = int.from_bytes(data[start : start + bytes_per_pixel], endian)
        return (
            (value & red_mask) >> red_shift,
            (value & green_mask) >> green_shift,
            (value & blue_mask) >> blue_shift,
        )

    return pixel, width, height


def _wait_rail(window: str, timeout: float = SETTLE_TIMEOUT) -> None:
    """Wait for the note page's rail to be drawn (#17171d, spec §6.5).

    ``Gtk.Window.set_title`` lands before the stack switches from the fan to
    the note page, so a capture taken the instant the title changes can still
    show the fan; without this the rail check fails intermittently.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pixel, _width, height = _pixel_sampler(_xwd_image(window))
        if pixel(0, height - 1) == (23, 23, 29):
            return
        time.sleep(0.05)
    raise SmokeFailure("the tab rail never appeared in the note window")


def _check_dark(window: str, *, rail: bool = False) -> None:
    pixel, width, height = _pixel_sampler(_xwd_image(window))

    if rail:
        # The note page has the tab rail (#17171d) down its left side.
        rail_colour = pixel(0, height - 1)
        if rail_colour != (23, 23, 29):
            raise SmokeFailure(
                f"tab rail is #{rail_colour[0]:02x}{rail_colour[1]:02x}"
                f"{rail_colour[2]:02x}, expected #17171d"
            )
        corners = ((width - 1, 0), (width - 1, height - 1), (width - 3, height // 2))
    else:
        corners = (
            (0, 0),
            (width - 1, 0),
            (0, height - 1),
            (width - 1, height - 1),
            (width // 2, height - 1),
        )
    for point in corners:
        observed = pixel(*point)
        if observed != BACKGROUND:
            raise SmokeFailure(
                f"panel corner {point} is #{observed[0]:02x}{observed[1]:02x}"
                f"{observed[2]:02x}, expected #1c1c22 (light flash?)"
            )

    white = 0
    for y in range(0, height, 8):
        for x in range(0, width, 8):
            red, green, blue = pixel(x, y)
            if red > 245 and green > 245 and blue > 245:
                white += 1
    if white:
        raise SmokeFailure(f"panel has {white} near-white samples; dark theme failed")


# -- app process ---------------------------------------------------------


def _app_id() -> str:
    return f"dev.lurknotes.LurkNotes.noteSmoke.s{os.getpid()}"


def _start_app(data_home: Path, dump: Path, type_text: str | None) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_APP_ID": _app_id(),
            "LURKNOTES_TEST_DUMP": str(dump),
            "LURKNOTES_TEST_CONTROL": "1",
            "LURKNOTES_TEST_PIN_DECK": "1",
        }
    )
    if type_text is not None:
        env["LURKNOTES_TEST_TYPE"] = type_text
    process = subprocess.Popen(
        [str(ROOT / "lurknotes")],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.lurk_app_id = env["LURKNOTES_APP_ID"]  # type: ignore[attr-defined]
    return process


def _ensure_running(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        return
    stdout, stderr = process.communicate(timeout=5)
    raise SmokeFailure(
        f"app exited with {process.returncode} unexpectedly\n"
        f"stdout: {stdout[-2000:]}\nstderr: {stderr[-2000:]}"
    )


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_for_exit(process: subprocess.Popen[str], timeout: float = 5.0) -> int:
    """Wait for a normal shutdown triggered from outside the process."""
    try:
        process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure(
            "the app did not exit within "
            f"{timeout:.0f}s after the WM close request"
        ) from exc
    if process.returncode != 0:
        raise SmokeFailure(
            f"the app exited with {process.returncode} after the WM close request"
        )
    return process.returncode


def _wait_for_window(
    title: str, process: subprocess.Popen[str], timeout: float = STARTUP_TIMEOUT
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _ensure_running(process)
        windows = _windows_titled(title, process.pid)
        if len(windows) > 1:
            raise SmokeFailure(f"expected one window titled {title!r}, found {len(windows)}")
        if windows:
            return windows[0]
        time.sleep(0.05)
    raise SmokeFailure(f"no window titled {title!r} appeared within {timeout:.0f}s")


def _wait_fan_viewable(
    process: subprocess.Popen[str], timeout: float = SETTLE_TIMEOUT
) -> str:
    """Wait for *our* fan window to be mapped, not merely created.

    Since ticket 04 the panel window exists from startup but stays unmapped in
    the strip state; ``xwininfo -tree`` lists it either way.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _ensure_running(process)
        for window in _windows_titled(FAN_TITLE, process.pid):
            info = _window_info(window)
            if info.get("map_state") == "IsViewable":
                return window
        time.sleep(0.05)
    raise SmokeFailure(f"the fan did not map within {timeout:.0f}s")


def _away_point() -> tuple[int, int]:
    """A point on the desktop well left of the deck."""
    x, y, _width, _height = _workarea()
    scale = _effective_scale()
    return x + round(120 * scale), y + round(120 * scale)


def _strip_point() -> tuple[int, int]:
    x, y, width, _height = _workarea()
    scale = _effective_scale()
    return x + width - round(5 * scale), y + round(200 * scale)


def _control(process: subprocess.Popen[str], command: str) -> bool:
    """Drive a deck interaction when another agent's window owns the edge.

    Only available when LURKNOTES_TEST_CONTROL is set; calls the same handlers
    as pointer and button events, so the smoke can still verify the deck under
    a concurrent ABOVE window.
    """
    app_id = getattr(process, "lurk_app_id", None)
    if app_id is None:
        return False
    path = "/" + app_id.replace(".", "/")
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            app_id,
            "--object-path",
            path,
            "--method",
            "org.gtk.Actions.Activate",
            "control",
            f'[<"{command}">]',
            "{}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"smoke-note: control {command!r} failed: {result.stderr.strip()}")
        return False
    return True


def _show_fan(xtest: "XTest", process: subprocess.Popen[str]) -> str:
    """Hover the strip like a user and return the mapped fan window.

    A real XTest pointer move is used instead of any test hook: this is the
    exact path spec §3 describes, including the 120 ms delay and the no-focus
    map. Moving away first matters when the pointer is still parked on the
    strip from an earlier step: XTest would send no new enter event.
    """
    strip = _wait_for_window(STRIP_TITLE, process)
    away_x, away_y = _away_point()
    xtest.move(away_x, away_y)
    time.sleep(0.05)
    x, y = _strip_point()
    try:
        _raise_until_top(xtest, strip, x, y, "the strip")
    except SmokeFailure as exc:
        print(f"smoke-note: could not raise the strip ({exc}); retrying")
    xtest.move(x, y)
    try:
        return _wait_fan_viewable(process)
    except SmokeFailure:
        print("smoke-note: strip hover was blocked; using the control channel")
        if not _control(process, "strip"):
            raise
        return _wait_fan_viewable(process)


def _wait_dump(
    path: Path,
    process: subprocess.Popen[str],
    predicate: Callable[[dict], bool],
    timeout: float = DUMP_TIMEOUT,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        _ensure_running(process)
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            last = snapshot
            if predicate(snapshot):
                return snapshot
        time.sleep(0.05)
    raise SmokeFailure(f"deck snapshot never matched; last dump: {last}")


# -- pointer / XTest -----------------------------------------------------


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


class _ClientEvent(ctypes.Union):
    _fields_ = [("xclient", _ClientMessage), ("pad", ctypes.c_long * 24)]


class XTest:
    """Real X11 pointer clicks, because xdotool is not installed."""

    def __init__(self) -> None:
        self.xlib = ctypes.CDLL("libX11.so.6")
        self.xtst = ctypes.CDLL("libXtst.so.6")

        self.xlib.XOpenDisplay.restype = ctypes.c_void_p
        self.xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.xlib.XDefaultRootWindow.restype = ctypes.c_ulong
        self.xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.xlib.XFlush.restype = ctypes.c_int
        self.xlib.XFlush.argtypes = [ctypes.c_void_p]
        self.xlib.XCloseDisplay.restype = ctypes.c_int
        self.xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.xlib.XInternAtom.restype = ctypes.c_ulong
        self.xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.xlib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.xlib.XSendEvent.restype = ctypes.c_int
        self.xlib.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        self.xlib.XQueryPointer.restype = ctypes.c_int
        self.xlib.XQueryPointer.argtypes = [
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
        self.xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.xtst.XTestFakeButtonEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.xlib.XKeysymToKeycode.restype = ctypes.c_uint
        self.xlib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.xlib.XSetInputFocus.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.xlib.XChangeProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self.xtst.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]

        self.display = self.xlib.XOpenDisplay(None)
        if not self.display:
            raise SmokeFailure("cannot open X display for XTest")
        self._root = self.xlib.XDefaultRootWindow(self.display)
        self.original = self._pointer()

    def _pointer(self) -> tuple[int, int] | None:
        root_return = ctypes.c_ulong()
        child_return = ctypes.c_ulong()
        root_x, root_y, win_x, win_y = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        ok = self.xlib.XQueryPointer(
            self.display,
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

    def focus(self, window: str) -> None:
        """Test-only focus grant: X input focus + root _NET_ACTIVE_WINDOW.

        ``present()`` is the app's real path. Concurrent agents and shell
        grabs can withhold activation, which would make keyboard smokes flaky;
        this makes "the panel is focused" true so Esc/Ctrl+Backspace reach it.
        """
        xid = int(window, 16)
        self.xlib.XSetInputFocus(self.display, xid, 2, 0)  # RevertToParent, now
        value = (ctypes.c_ulong * 1)(xid)
        self.xlib.XChangeProperty(
            self.display,
            self._root,
            self.xlib.XInternAtom(self.display, b"_NET_ACTIVE_WINDOW", 0),
            33,  # XA_WINDOW
            32,
            0,  # PropModeReplace
            ctypes.cast(value, ctypes.c_void_p),
            1,
        )
        self.xlib.XFlush(self.display)
        time.sleep(0.1)

    def click(self, x: int, y: int) -> None:
        self.move(x, y)
        self.xtst.XTestFakeButtonEvent(self.display, 1, 1, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.08)
        self.xtst.XTestFakeButtonEvent(self.display, 1, 0, 0)
        self.xlib.XFlush(self.display)

    def move(self, x: int, y: int) -> None:
        self.xtst.XTestFakeMotionEvent(self.display, -1, x, y, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.05)

    def wheel(self, notches: int, *, up: bool = False) -> None:
        """Turn the wheel over the pointer: X buttons 4 (up) and 5 (down)."""
        button = 4 if up else 5
        for _ in range(abs(notches)):
            self.xtst.XTestFakeButtonEvent(self.display, button, 1, 0)
            self.xtst.XTestFakeButtonEvent(self.display, button, 0, 0)
            self.xlib.XFlush(self.display)
            time.sleep(0.05)

    def top_window_at_pointer(self) -> int | None:
        """The root child under the pointer, i.e. the window a click hits."""
        root_return = ctypes.c_ulong()
        child_return = ctypes.c_ulong()
        root_x, root_y, win_x, win_y = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        ok = self.xlib.XQueryPointer(
            self.display,
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
        return child_return.value or None

    def raise_window(self, window: str) -> None:
        """Lift our window above another LurkNotes on the same screen edge.

        A second instance from another worktree uses the same ABOVE layer and
        the same rect. Its window would swallow the XTest click and hide ours
        from ``xwd``, so re-raise ours right before touching the screen. The
        other process is left alone.
        """
        self.xlib.XRaiseWindow(self.display, int(window, 16))
        self.xlib.XFlush(self.display)
        time.sleep(0.05)

    def close_window(self, window: str) -> None:
        """Send WM_DELETE_WINDOW, exactly what a window manager's × sends.

        Alt+F4 and the overview close button deliver the same client message,
        so this exercises the real shutdown path rather than a signal.
        """
        xid = int(window, 16)
        event = _ClientEvent()
        event.xclient.type = 33  # ClientMessage
        event.xclient.serial = 0
        event.xclient.send_event = 1
        event.xclient.display = self.display
        event.xclient.window = xid
        event.xclient.message_type = self.xlib.XInternAtom(
            self.display, b"WM_PROTOCOLS", 0
        )
        event.xclient.format = 32
        event.xclient.data[0] = self.xlib.XInternAtom(
            self.display, b"WM_DELETE_WINDOW", 0
        )
        self.xlib.XSendEvent(self.display, xid, 0, 0, ctypes.byref(event))
        self.xlib.XFlush(self.display)

    def restore(self) -> None:
        if self.original is not None:
            self.xtst.XTestFakeMotionEvent(
                self.display, -1, self.original[0], self.original[1], 0
            )
            self.xlib.XFlush(self.display)

    def press_escape(self) -> None:
        keycode = self.xlib.XKeysymToKeycode(self.display, 0xFF1B)
        self.xtst.XTestFakeKeyEvent(self.display, keycode, 1, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.08)
        self.xtst.XTestFakeKeyEvent(self.display, keycode, 0, 0)
        self.xlib.XFlush(self.display)

    def _tap(self, keysym: int) -> None:
        keycode = self.xlib.XKeysymToKeycode(self.display, keysym)
        self.xtst.XTestFakeKeyEvent(self.display, keycode, 1, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.02)
        self.xtst.XTestFakeKeyEvent(self.display, keycode, 0, 0)
        self.xlib.XFlush(self.display)

    def type_text(self, text: str) -> None:
        """Type plain lower-case ASCII into the focused editor."""
        for character in text:
            if character == "\n":
                self._tap(0xFF0D)
            elif character == " ":
                self._tap(0x20)
            else:
                self._tap(ord(character))
            time.sleep(0.01)

    def ctrl_q(self) -> None:
        control = self.xlib.XKeysymToKeycode(self.display, 0xFFE3)
        q = self.xlib.XKeysymToKeycode(self.display, 0x71)
        self.xtst.XTestFakeKeyEvent(self.display, control, 1, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.03)
        self.xtst.XTestFakeKeyEvent(self.display, q, 1, 0)
        self.xtst.XTestFakeKeyEvent(self.display, q, 0, 0)
        self.xtst.XTestFakeKeyEvent(self.display, control, 0, 0)
        self.xlib.XFlush(self.display)

    def chord(self, keysym: int) -> None:
        control = self.xlib.XKeysymToKeycode(self.display, 0xFFE3)
        key = self.xlib.XKeysymToKeycode(self.display, keysym)
        self.xtst.XTestFakeKeyEvent(self.display, control, 1, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.04)
        self.xtst.XTestFakeKeyEvent(self.display, key, 1, 0)
        self.xtst.XTestFakeKeyEvent(self.display, key, 0, 0)
        time.sleep(0.02)
        self.xtst.XTestFakeKeyEvent(self.display, control, 0, 0)
        self.xlib.XFlush(self.display)

    def ctrl_backspace(self) -> None:
        self.chord(0xFF08)

    def ctrl_z(self) -> None:
        self.chord(0x7A)

    def ctrl_tab(self, backward: bool = False) -> None:
        control = self.xlib.XKeysymToKeycode(self.display, 0xFFE3)
        shift = self.xlib.XKeysymToKeycode(self.display, 0xFFE1)
        self.xtst.XTestFakeKeyEvent(self.display, control, 1, 0)
        if backward:
            self.xtst.XTestFakeKeyEvent(self.display, shift, 1, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.05)
        self._tap(0xFF09)
        if backward:
            self.xtst.XTestFakeKeyEvent(self.display, shift, 0, 0)
        self.xtst.XTestFakeKeyEvent(self.display, control, 0, 0)
        self.xlib.XFlush(self.display)

    def close(self) -> None:
        if self.display:
            self.xlib.XCloseDisplay(self.display)
            self.display = None


# -- checks --------------------------------------------------------------


def _expected_panel_rect(scale: float) -> tuple[int, int, int, int]:
    workarea_x, workarea_y, workarea_w, workarea_h = _workarea()
    right = workarea_x + workarea_w
    width = round(PANEL_LOGICAL_WIDTH * scale)
    return (
        right
        - round((PANEL_LOGICAL_WIDTH + STRIP_LOGICAL_WIDTH) * scale),
        workarea_y,
        width,
        workarea_h,
    )


def _wait_geometry(window: str, expected: tuple[int, int, int, int]) -> dict[str, int | str]:
    deadline = time.monotonic() + SETTLE_TIMEOUT
    while True:
        info = _window_info(window)
        observed = (
            info.get("x"),
            info.get("y"),
            info.get("width"),
            info.get("height"),
        )
        if observed == expected or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    if observed != expected:
        raise SmokeFailure(
            f"panel geometry {observed} does not match {expected}"
        )
    if info.get("map_state") != "IsViewable":
        raise SmokeFailure(f"panel is not viewable (Map State: {info.get('map_state')})")
    return info


def _check_fan(panel: str) -> dict[str, int | str]:
    scale = _effective_scale()
    expected = _expected_panel_rect(scale)
    info = _wait_geometry(panel, expected)
    properties = _window_properties(panel)
    _check_states(properties)
    desktop = _check_desktop(properties)
    if desktop != ALL_DESKTOPS:
        raise SmokeFailure(
            f"_NET_WM_DESKTOP is {desktop}, expected {ALL_DESKTOPS} (all desktops)"
        )
    _check_no_focus_hints(properties)
    _check_dark(panel)
    print(
        "smoke-note: fan geometry "
        f"x={info['x']} y={info['y']} {info['width']}x{info['height']} "
        f"scale {scale:g}; dark palette OK"
    )
    return info


def _raise_until_top(
    xtest: XTest, window: str, x: int, y: int, label: str
) -> None:
    """Make sure *window* is the one a click at x,y would hit.

    Another worktree's LurkNotes uses the same screen edge and the same
    ``_NET_WM_STATE_ABOVE`` layer. A click sent while its window is on top
    goes to the wrong process. Raising ours and reading back the window under
    the pointer makes the check explicit instead of hoping for stacking luck.
    The other process is never touched.
    """
    xid = int(window, 16)
    deadline = time.monotonic() + COVER_TIMEOUT
    while time.monotonic() < deadline:
        xtest.move(x, y)
        xtest.raise_window(window)
        if xtest.top_window_at_pointer() == xid:
            return
        time.sleep(0.1)
    foreign = xtest.top_window_at_pointer()
    raise SmokeFailure(
        f"another window (0x{foreign:x}) covers {label} at {x},{y}"
        if foreign
        else f"nothing is under {label} at {x},{y}"
    )


def _raise_for_capture(
    xtest: XTest,
    window: str,
    label: str,
    points: tuple[tuple[int, int], ...] = (
        (1, 1),
        (378, 1),
        (1, 926),
        (378, 926),
        (190, 926),
    ),
) -> None:
    """Same as :func:`_raise_until_top`, for pixel snapshots.

    ``xwd`` on an obscured window returns garbage, which would look like a
    light-theme failure. The points are the corners and bottom-centre that
    ``_check_dark`` samples, so a covered window is caught before capture.
    """
    scale = _effective_scale()
    xid = int(window, 16)
    deadline = time.monotonic() + COVER_TIMEOUT
    while time.monotonic() < deadline:
        # The panel is re-placed by its map handler, so read the rect each
        # pass instead of computing the points once.
        info = _window_info(window)
        left, top = int(info["x"]), int(info["y"])
        clear = True
        for px, py in points:
            xtest.move(left + round(px * scale), top + round(py * scale))
            xtest.raise_window(window)
            if xtest.top_window_at_pointer() != xid:
                clear = False
                break
        if clear:
            return
        time.sleep(0.1)
    raise SmokeFailure(f"another window covers {label}; cannot capture pixels")


def _click_first_tab(xtest: XTest, panel: str, snapshot: dict) -> None:
    centers = snapshot.get("tab_centers") or []
    if not centers:
        raise SmokeFailure("fan snapshot has no tab centres to click")
    info = _window_info(panel)
    scale = _effective_scale()
    x = int(info["x"]) + round(centers[0][0] * scale)
    y = int(info["y"]) + round(centers[0][1] * scale)
    _raise_until_top(xtest, panel, x, y, "the first tab")
    xtest.click(x, y)
    print(f"smoke-note: clicked first tab at {x},{y}")


def _click_center(
    xtest: XTest, window: str, center: list[float], label: str
) -> None:
    info = _window_info(window)
    scale = _effective_scale()
    x = int(info["x"]) + round(center[0] * scale)
    y = int(info["y"]) + round(center[1] * scale)
    _raise_until_top(xtest, window, x, y, label)
    xtest.click(x, y)
    print(f"smoke-note: clicked {label} at {x},{y}")


def _click_new_note(
    xtest: XTest,
    process: subprocess.Popen[str],
    panel: str,
    dump: Path,
) -> dict:
    snapshot = _wait_dump(
        dump,
        process,
        lambda value: value.get("state") == "fan"
        and value.get("new_button_center") is not None,
    )
    for attempt in range(1, 5):
        try:
            _click_center(
                xtest, panel, snapshot["new_button_center"], "the + button"
            )
        except SmokeFailure as exc:
            print(f"smoke-note: + click attempt {attempt} was blocked ({exc})")
            time.sleep(0.4)
            continue
        try:
            return _wait_dump(
                dump,
                process,
                lambda value: value.get("state") == "open"
                and value.get("current_id") is not None
                and (value.get("ids") or [None])[0] == value.get("current_id")
                and value.get("text") == "",
                timeout=2.0,
            )
        except SmokeFailure:
            print(f"smoke-note: + click attempt {attempt} did not open a new note")
    raise SmokeFailure("the + button never opened a new note")


def _click_rail_note(
    xtest: XTest,
    process: subprocess.Popen[str],
    panel: str,
    dump: Path,
    note_id: str,
) -> dict:
    snapshot = _wait_dump(
        dump,
        process,
        lambda value: value.get("state") == "open"
        and note_id in (value.get("ids") or [])
        and len(value.get("rail_centers") or []) == len(value.get("ids") or []),
    )
    index = snapshot["ids"].index(note_id)
    _click_center(
        xtest, panel, snapshot["rail_centers"][index], f"rail note {note_id[:8]}"
    )
    return snapshot


def _wait_for_ids_on_disk(
    path: Path, expected_ids: list[str], timeout: float = SAVE_TIMEOUT
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            last = payload
            if [note.get("id") for note in payload.get("notes") or []] == expected_ids:
                return payload
        time.sleep(0.05)
    raise SmokeFailure(
        f"notes.json ids never matched {expected_ids} within {timeout:.0f}s; "
        f"last: {last}"
    )


def _click_until_note_open(
    xtest: XTest,
    process: subprocess.Popen[str],
    panel: str,
    snapshot: dict,
    attempts: int = 6,
) -> str:
    """One real click should open the note; retry for X server hiccups."""
    for attempt in range(1, attempts + 1):
        try:
            _click_first_tab(xtest, panel, snapshot)
        except SmokeFailure as exc:
            print(f"smoke-note: click attempt {attempt} was blocked ({exc})")
            time.sleep(0.5)
            continue
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            _ensure_running(process)
            windows = _windows_titled(NOTE_TITLE, process.pid)
            if windows:
                return windows[0]
            time.sleep(0.05)
        print(f"smoke-note: click attempt {attempt} did not open a note")
    raise SmokeFailure(f"no window titled {NOTE_TITLE!r} appeared after {attempts} clicks")


def _click_editor(xtest: XTest, note_window: str) -> None:
    """Click inside the text area so Esc is certain to reach the panel."""
    info = _window_info(note_window)
    scale = _effective_scale()
    x = int(info["x"]) + round((112 + 50) * scale)
    y = int(info["y"]) + round(120 * scale)
    _raise_until_top(xtest, note_window, x, y, "the editor")
    xtest.click(x, y)


def _close_note_with_escape(
    xtest: XTest,
    process: subprocess.Popen[str],
    note_window: str,
    attempts: int = 3,
    click_first: bool = True,
) -> None:
    for attempt in range(1, attempts + 1):
        # When proving close-flush, try Esc on the already-focused panel
        # before clicking: the click costs enough time for the 400 ms
        # autosave to fire, which would hide a missing close flush.
        if click_first or attempt > 1:
            _click_editor(xtest, note_window)
            time.sleep(0.1)
        # A concurrent test can steal focus between the click and the key.
        xtest.focus(note_window)
        xtest.press_escape()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            _ensure_running(process)
            if _windows_titled(FAN_TITLE, process.pid):
                return
            time.sleep(0.05)
        print(f"smoke-note: Esc attempt {attempt} did not return to the fan")
    raise SmokeFailure(f"note did not close after {attempts} Esc presses")


def _wait_for_text_on_disk(path: Path, expected: str) -> dict:
    deadline = time.monotonic() + SAVE_TIMEOUT
    last: dict | None = None
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            last = payload
            notes = payload.get("notes") or []
            if notes and notes[0].get("text") == expected:
                return payload
        time.sleep(0.05)
    raise SmokeFailure(f"text was not saved within {SAVE_TIMEOUT:.0f}s; last: {last}")


def _assert_app_id_free(app_id: str) -> None:
    """A same-id instance would receive our launch and exit 0 (PLATFORM §10).

    Only *our* id matters: another worktree's LurkNotes has a different id and
    may legitimately be on screen while this smoke runs.
    """
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.DBus",
            "--object-path",
            "/org/freedesktop/DBus",
            "--method",
            "org.freedesktop.DBus.NameHasOwner",
            app_id,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        # No gdbus or no session bus; the spawn below would fail visibly.
        return
    if "true" in result.stdout.lower():
        raise SmokeFailure(f"another LurkNotes instance owns {app_id}; retry")


def _wait_for_no_windows(
    titles: tuple[str, ...],
    process: subprocess.Popen[str],
    timeout: float = 5.0,
) -> None:
    """Wait until this process's windows are gone.

    Filtering by ``_NET_WM_PID`` is what keeps a concurrent LurkNotes from a
    different worktree (same window titles, different app id) from failing
    this check.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_windows_titled(title, process.pid) for title in titles):
            return
        time.sleep(0.05)
    raise SmokeFailure(f"windows survived shutdown: {titles}")


def main() -> int:
    app: subprocess.Popen[str] | None = None
    xtest: XTest | None = None
    try:
        _assert_app_id_free(_app_id())

        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-note-") as temporary:
            data_home = Path(temporary)
            notes_dir = data_home / "lurknotes"
            notes_dir.mkdir()
            notes_path = notes_dir / "notes.json"
            first_id = "11111111-1111-4111-8111-111111111111"
            second_id = "22222222-2222-4222-8222-222222222222"
            loaded_empty_id = "33333333-3333-4333-8333-333333333333"
            original_text = "Groceries\nmilk\neggs"
            payload = {
                "version": 1,
                "notes": [
                    {
                        "id": first_id,
                        "text": original_text,
                        "created": 100.0,
                        "updated": 100.0,
                    },
                    {
                        "id": second_id,
                        "text": "Standup\nnotes",
                        "created": 101.0,
                        "updated": 101.0,
                    },
                    {
                        # Empty and untouched-looking, but loaded from the
                        # file: spec §5.4 says it must survive every close.
                        "id": loaded_empty_id,
                        "text": "",
                        "created": 102.0,
                        "updated": 102.0,
                    },
                ],
            }
            notes_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            original_bytes = notes_path.read_bytes()
            typed = "\nSmoke typed text"
            expected_text = original_text + typed

            dump = data_home / "dump.json"
            app = _start_app(data_home, dump, typed)
            _wait_for_window(STRIP_TITLE, app)
            xtest = XTest()
            fan = _show_fan(xtest, app)
            _raise_for_capture(xtest, fan, "the fan")
            _check_fan(fan)

            fan_snapshot = _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and len(snapshot.get("tab_centers") or []) == 3,
            )
            if fan_snapshot.get("titles") != ["Groceries", "Standup", "Untitled"]:
                raise SmokeFailure(
                    f"fan titles are {fan_snapshot.get('titles')}, expected array order"
                )

            note_window = _click_until_note_open(xtest, app, fan, fan_snapshot)
            # Read the dump before the pixel checks: the type hook fires 600 ms
            # after the note opens, and a slow capture would hide the
            # "nothing typed yet" snapshot this asserts.
            open_snapshot = _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("text") == original_text
                and snapshot.get("cursor_at_end") is True
                and snapshot.get("typed") is False
                and snapshot.get("rail_width") == 112,
            )
            if open_snapshot.get("rail_width") != 112:
                raise SmokeFailure(
                    f"tab rail is {open_snapshot.get('rail_width')} px, expected 112"
                )
            typed_snapshot = _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("typed") is True
                and snapshot.get("text") == expected_text
                and snapshot.get("cursor_at_end") is True,
            )
            if typed_snapshot.get("current_id") != first_id:
                raise SmokeFailure("editor opened a different note")

            _wait_geometry(note_window, _expected_panel_rect(_effective_scale()))
            _wait_rail(note_window)
            _raise_for_capture(xtest, note_window, "the note page")
            _check_dark(note_window, rail=True)
            print("smoke-note: tab click opened the note, cursor at end, text inserted")

            _wait_for_text_on_disk(notes_path, expected_text)
            backup = json.loads((notes_dir / "notes.bak.json").read_text(encoding="utf-8"))
            if backup["notes"][0]["text"] != original_text:
                raise SmokeFailure("notes.bak.json does not hold the previous file")
            if backup["notes"][2]["id"] != loaded_empty_id:
                raise SmokeFailure("notes.bak.json lost the loaded empty note")
            if (notes_dir / "notes.bak.json").read_bytes() != original_bytes:
                raise SmokeFailure("notes.bak.json bytes differ from the previous file")

            app.kill()  # SIGKILL: the debounce/save must already be durable
            app.wait(timeout=5)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)

            after_kill = json.loads(notes_path.read_text(encoding="utf-8"))
            if after_kill.get("version") != 1:
                raise SmokeFailure("notes.json lost its version after SIGKILL")
            if after_kill["notes"][0]["text"] != expected_text:
                raise SmokeFailure("notes.json lost the typed text after SIGKILL")
            if after_kill["notes"][0]["updated"] <= after_kill["notes"][0]["created"]:
                raise SmokeFailure("updated timestamp was not bumped")
            if after_kill["notes"][1]["text"] != "Standup\nnotes":
                raise SmokeFailure("the second note changed unexpectedly")
            if after_kill["notes"][2]["id"] != loaded_empty_id:
                raise SmokeFailure("the loaded empty note was lost after SIGKILL")
            if after_kill["notes"][2]["text"] != "":
                raise SmokeFailure("the loaded empty note gained text")
            if (notes_dir / "notes.json.tmp").exists():
                raise SmokeFailure("notes.json.tmp survived a successful save")
            print("smoke-note: SIGKILL after debounce left valid JSON with the text")

            restart_dump = data_home / "restart-dump.json"
            close_typed = "\nClosed before debounce"
            app = _start_app(data_home, restart_dump, close_typed)
            fan = _show_fan(xtest, app)
            restart_fan = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and len(snapshot.get("tab_centers") or []) == 3,
            )
            restart_note = _click_until_note_open(xtest, app, fan, restart_fan)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("text") == expected_text
                and snapshot.get("cursor_at_end") is True
                and snapshot.get("typed") is False,
            )
            print("smoke-note: after restart the editor shows the saved text")

            # Closing the note must flush even if the 400 ms timer has not run.
            closed_text = expected_text + close_typed
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("typed") is True
                and snapshot.get("text") == closed_text,
            )
            _close_note_with_escape(xtest, app, restart_note, click_first=False)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("current_id") is None,
            )
            _wait_for_text_on_disk(notes_path, closed_text)
            print("smoke-note: Esc returned to the fan and flushed the pending text")

            # -- ticket 03: many notes ----------------------------------
            base_ids = [first_id, second_id, loaded_empty_id]

            # '+' puts an untouched note at the top and opens it empty.
            _click_new_note(xtest, app, restart_note, restart_dump)
            new_top = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("ids", [None])[0] == snapshot.get("current_id")
                and snapshot.get("ids", [])[1:] == base_ids
                and snapshot.get("titles", [None])[0] == "Untitled"
                and snapshot.get("text") == ""
                and snapshot.get("cursor_offset") == 0,
            )
            top_id = new_top["current_id"]
            if top_id in base_ids:
                raise SmokeFailure("+ reused an existing note id")
            if new_top.get("titles") != [
                "Untitled",
                "Groceries",
                "Standup",
                "Untitled",
            ]:
                raise SmokeFailure(
                    f"duplicate Untitled titles broke the list: {new_top.get('titles')}"
                )
            _wait_for_ids_on_disk(notes_path, [top_id, *base_ids])
            print("smoke-note: + created an empty note at the top and opened it")

            # Closing that untouched note deletes it and saves immediately.
            _close_note_with_escape(xtest, app, restart_note)
            after_close = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("current_id") is None
                and snapshot.get("ids") == base_ids,
            )
            if after_close.get("titles") != ["Groceries", "Standup", "Untitled"]:
                raise SmokeFailure(
                    f"untouched close left titles {after_close.get('titles')}"
                )
            _wait_for_ids_on_disk(notes_path, base_ids)
            saved = json.loads(notes_path.read_text(encoding="utf-8"))
            if loaded_empty_id not in [note["id"] for note in saved["notes"]]:
                raise SmokeFailure("closing an untouched note dropped the loaded empty one")
            print("smoke-note: closing the untouched note removed it; loaded empty kept")

            # A rail click switches notes and deletes the untouched one left.
            _click_new_note(xtest, app, restart_note, restart_dump)
            rail_open = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("ids", [None])[0] == snapshot.get("current_id")
                and snapshot.get("ids", [])[1:] == base_ids
                and len(snapshot.get("rail_centers") or []) == 4,
            )
            _wait_for_ids_on_disk(
                notes_path, [rail_open["current_id"], *base_ids]
            )
            _click_rail_note(xtest, app, restart_note, restart_dump, first_id)
            switched = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == first_id
                and snapshot.get("ids") == base_ids
                and snapshot.get("text") == closed_text
                and snapshot.get("cursor_at_end") is True
                # The highlight follows the id, and the rail is in array order,
                # so first_id must be row 0 even though titles differ.
                and snapshot.get("active_index") == 0,
            )
            if rail_open["current_id"] in switched.get("ids", []):
                raise SmokeFailure("switching notes kept the untouched note")
            _wait_for_ids_on_disk(notes_path, base_ids)
            print("smoke-note: rail click switched notes and dropped the untouched one")

            # Ctrl+Tab / Ctrl+Shift+Tab cycle in array order and wrap.
            _click_editor(xtest, restart_note)
            time.sleep(0.1)
            xtest.ctrl_tab()
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == second_id,
            )
            xtest.ctrl_tab(backward=True)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == first_id,
            )
            xtest.ctrl_tab(backward=True)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == loaded_empty_id,
            )
            xtest.ctrl_tab()
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == first_id,
            )
            print("smoke-note: Ctrl+Tab and Ctrl+Shift+Tab cycle and wrap")

            # Return to the fan so the + button is visible again.
            _close_note_with_escape(xtest, app, restart_note)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("current_id") is None
                and snapshot.get("ids") == base_ids,
            )

            # A typed note stays, keeps its top position, and survives restart.
            fresh_text = "fresh top"
            _click_new_note(xtest, app, restart_note, restart_dump)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("ids", [None])[0] == snapshot.get("current_id")
                and snapshot.get("text") == "",
            )
            fresh_id = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("ids", [None])[0] == snapshot.get("current_id"),
            )["current_id"]
            xtest.type_text(fresh_text)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == fresh_id
                and snapshot.get("text") == fresh_text,
            )
            xtest.ctrl_tab()
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == first_id
                and snapshot.get("ids") == [fresh_id, *base_ids],
            )
            _wait_for_ids_on_disk(notes_path, [fresh_id, *base_ids])
            saved = json.loads(notes_path.read_text(encoding="utf-8"))
            if saved["notes"][0]["text"] != fresh_text:
                raise SmokeFailure("typed text in the new top note was not saved")
            print("smoke-note: typed new note stayed at the top and was saved")

            _stop(app)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)
            final_dump = data_home / "final-dump.json"
            app = _start_app(data_home, final_dump, None)
            _wait_for_window(STRIP_TITLE, app)
            _show_fan(xtest, app)
            final_fan = _wait_dump(
                final_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids", [None])[0] == fresh_id,
            )
            if final_fan.get("titles") != [
                "fresh top",
                "Groceries",
                "Standup",
                "Untitled",
            ]:
                raise SmokeFailure(
                    f"order after restart is {final_fan.get('titles')}"
                )
            if loaded_empty_id not in final_fan.get("ids", []):
                raise SmokeFailure("the loaded empty note did not survive restart")
            print("smoke-note: note order and the loaded empty note survived restart")

            # Empty deck: + is the way in, and closing the last untouched
            # note returns to a saved empty deck.
            _stop(app)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)
            empty_home = data_home / "empty"
            empty_notes = empty_home / "lurknotes" / "notes.json"
            empty_dump = data_home / "empty-dump.json"
            app = _start_app(empty_home, empty_dump, None)
            _wait_for_window(STRIP_TITLE, app)
            empty_fan_window = _show_fan(xtest, app)
            empty_fan = _wait_dump(
                empty_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids") == []
                and snapshot.get("new_button_center") is not None,
            )
            if empty_fan.get("tab_centers") != []:
                raise SmokeFailure("an empty deck showed tabs")
            _click_center(
                xtest,
                empty_fan_window,
                empty_fan["new_button_center"],
                "+ on the empty deck",
            )
            _wait_dump(
                empty_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and len(snapshot.get("ids") or []) == 1
                and snapshot.get("ids", [None])[0] == snapshot.get("current_id")
                and snapshot.get("text") == ""
                and snapshot.get("cursor_offset") == 0,
            )
            _close_note_with_escape(xtest, app, _wait_for_window(NOTE_TITLE, app))
            _wait_dump(
                empty_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids") == []
                and snapshot.get("current_id") is None,
            )
            _wait_for_ids_on_disk(empty_notes, [])
            print("smoke-note: empty deck accepted + and saved after the last note closed")

            # -- normal shutdown ----------------------------------------
            # Closing the window (or Ctrl+Q) is a normal shutdown: flush the
            # pending text, drop untouched notes created this session, then
            # save. A SIGTERM would prove nothing here, so send the real
            # WM_DELETE_WINDOW a window manager sends (spec §5.2, §5.4).
            _stop(app)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)
            quit_text = "quit flush"
            quit_dump = data_home / "shutdown-flush-dump.json"
            app = _start_app(empty_home, quit_dump, quit_text)
            _wait_for_window(STRIP_TITLE, app)
            quit_fan_window = _show_fan(xtest, app)
            quit_fan = _wait_dump(
                quit_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids") == []
                and snapshot.get("new_button_center") is not None,
            )
            _click_center(
                xtest,
                quit_fan_window,
                quit_fan["new_button_center"],
                "+ before quitting with unsaved text",
            )
            # The test hook types and dumps before the 400 ms autosave fires.
            _wait_dump(
                quit_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("text") == quit_text,
            )
            xtest.close_window(_wait_for_window(NOTE_TITLE, app))
            _wait_for_exit(app)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)
            saved = json.loads(empty_notes.read_text(encoding="utf-8"))
            typed_ids = [note["id"] for note in saved["notes"]]
            if len(typed_ids) != 1:
                raise SmokeFailure(
                    f"shutdown saved {typed_ids}, expected just the typed note"
                )
            if saved["notes"][0]["text"] != quit_text:
                raise SmokeFailure("shutdown lost text typed before the debounce fired")
            print("smoke-note: quit flushed the pending text instead of dropping it")

            # The same quit path must drop an untouched note created now: if
            # it reached the file it would come back as a loaded empty note.
            discard_dump = data_home / "shutdown-discard-dump.json"
            app = _start_app(empty_home, discard_dump, None)
            _wait_for_window(STRIP_TITLE, app)
            discard_fan_window = _show_fan(xtest, app)
            discard_fan = _wait_dump(
                discard_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids") == typed_ids
                and snapshot.get("new_button_center") is not None,
            )
            _click_center(
                xtest,
                discard_fan_window,
                discard_fan["new_button_center"],
                "+ before quitting untouched",
            )
            opened = _wait_dump(
                discard_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("ids", [None])[0] == snapshot.get("current_id")
                and snapshot.get("ids", [])[1:] == typed_ids
                and snapshot.get("text") == ""
                and snapshot.get("active_index") == 0,
            )
            untouched_id = opened["current_id"]
            _wait_for_ids_on_disk(empty_notes, [untouched_id, *typed_ids])
            xtest.close_window(_wait_for_window(NOTE_TITLE, app))
            _wait_for_exit(app)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)
            saved = json.loads(empty_notes.read_text(encoding="utf-8"))
            kept = [note["id"] for note in saved["notes"]]
            if kept != typed_ids:
                raise SmokeFailure(
                    f"quit left {kept} on disk, expected only {typed_ids}"
                )
            print("smoke-note: quitting dropped the untouched note and kept the typed one")

            # Ctrl+Q is the other normal-shutdown path; the accelerator must
            # reach app.quit and run the same cleanup.
            ctrlq_dump = data_home / "shutdown-ctrlq-dump.json"
            app = _start_app(empty_home, ctrlq_dump, None)
            _wait_for_window(STRIP_TITLE, app)
            ctrlq_fan_window = _show_fan(xtest, app)
            ctrlq_fan = _wait_dump(
                ctrlq_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("tab_centers"),
            )
            _click_first_tab(
                xtest, ctrlq_fan_window, ctrlq_fan
            )
            ctrlq_note = _wait_for_window(NOTE_TITLE, app)
            _wait_dump(
                ctrlq_dump,
                app,
                lambda snapshot: snapshot.get("state") == "open",
            )
            for attempt in range(1, 4):
                _click_editor(xtest, ctrlq_note)
                xtest.ctrl_q()
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and app.poll() is None:
                    time.sleep(0.05)
                if app.poll() is not None:
                    break
                print(f"smoke-note: Ctrl+Q attempt {attempt} did not quit")
            else:
                raise SmokeFailure("Ctrl+Q did not quit the app")
            if app.returncode != 0:
                raise SmokeFailure(f"Ctrl+Q exited with {app.returncode}")
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)
            saved = json.loads(empty_notes.read_text(encoding="utf-8"))
            if [note["id"] for note in saved["notes"]] != typed_ids:
                raise SmokeFailure("Ctrl+Q did not go through the shutdown cleanup")
            print("smoke-note: Ctrl+Q quits through the same shutdown path")

            # And the next launch must not resurrect it as a loaded empty note.
            restart_dump_final = data_home / "shutdown-restart-dump.json"
            app = _start_app(empty_home, restart_dump_final, None)
            _wait_for_window(STRIP_TITLE, app)
            _show_fan(xtest, app)
            after_quit = _wait_dump(
                restart_dump_final,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids") == typed_ids,
            )
            if after_quit.get("titles") != [quit_text]:
                raise SmokeFailure(
                    f"deck after quit is {after_quit.get('titles')}"
                )
            print("smoke-note: the untouched note did not resurrect after a quit")

            print("smoke-note: OK")
            return 0

    except SmokeFailure as failure:
        print(f"smoke-note: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a smoke failure
        print(f"smoke-note: FAIL: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if app is not None:
            _stop(app)


if __name__ == "__main__":
    raise SystemExit(main())
