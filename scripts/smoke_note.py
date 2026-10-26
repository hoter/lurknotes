#!/usr/bin/env python3
"""Prove the ticket 02 vertical slice through the real X11 UI.

File -> fan -> real X11 click on a tab -> editor -> programmatic typing ->
400 ms debounce -> SIGKILL -> JSON on disk -> restart -> text in the editor.

The only test-only production hook is documented in ``src/lurkn/app.py``:
``LURKNOTES_TEST_DUMP`` snapshots the deck (including tab centres) and
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


def _windows_titled(title: str) -> list[str]:
    tree = _run("xwininfo", "-root", "-tree")
    pattern = re.compile(r'^\s*(0x[0-9a-f]+)\s+"([^"]*)":')
    return [
        match.group(1)
        for line in tree.splitlines()
        if (match := pattern.match(line)) and match.group(2) == title
    ]


def _window_info(window: str) -> dict[str, int | str]:
    output = _run("xwininfo", "-id", window)
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


def _check_dark(window: str, *, rail: bool = False) -> None:
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
    ) = _xwd_image(window)
    bytes_per_pixel = (bits_per_pixel + 7) // 8
    endian = "little" if byte_order == 0 else "big"
    red_shift = _bit_shift(red_mask)
    green_shift = _bit_shift(green_mask)
    blue_shift = _bit_shift(blue_mask)

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        start = offset + y * bytes_per_line + x * bytes_per_pixel
        value = int.from_bytes(
            data[start : start + bytes_per_pixel], endian
        )
        return (
            (value & red_mask) >> red_shift,
            (value & green_mask) >> green_shift,
            (value & blue_mask) >> blue_shift,
        )

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


def _start_app(data_home: Path, dump: Path, type_text: str | None) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_TEST_DUMP": str(dump),
        }
    )
    if type_text is not None:
        env["LURKNOTES_TEST_TYPE"] = type_text
    return subprocess.Popen(
        [str(ROOT / "lurknotes")],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


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


def _wait_for_window(
    title: str, process: subprocess.Popen[str], timeout: float = STARTUP_TIMEOUT
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _ensure_running(process)
        windows = _windows_titled(title)
        if len(windows) > 1:
            raise SmokeFailure(f"expected one window titled {title!r}, found {len(windows)}")
        if windows:
            return windows[0]
        time.sleep(0.05)
    raise SmokeFailure(f"no window titled {title!r} appeared within {timeout:.0f}s")


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

    def click(self, x: int, y: int) -> None:
        self.xtst.XTestFakeMotionEvent(self.display, -1, x, y, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.15)
        self.xtst.XTestFakeButtonEvent(self.display, 1, 1, 0)
        self.xlib.XFlush(self.display)
        time.sleep(0.08)
        self.xtst.XTestFakeButtonEvent(self.display, 1, 0, 0)
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


def _click_first_tab(xtest: XTest, panel: str, snapshot: dict) -> None:
    centers = snapshot.get("tab_centers") or []
    if not centers:
        raise SmokeFailure("fan snapshot has no tab centres to click")
    info = _window_info(panel)
    scale = _effective_scale()
    x = int(info["x"]) + round(centers[0][0] * scale)
    y = int(info["y"]) + round(centers[0][1] * scale)
    xtest.click(x, y)
    print(f"smoke-note: clicked first tab at {x},{y}")


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


def _assert_no_instance() -> None:
    running = [
        title
        for title in (STRIP_TITLE, FAN_TITLE, NOTE_TITLE)
        if _windows_titled(title)
    ]
    if running:
        raise SmokeFailure(
            "another LurkNotes instance is already running "
            f"({', '.join(running)}); stop it and retry"
        )


def _wait_for_no_windows(titles: tuple[str, ...], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_windows_titled(title) for title in titles):
            return
        time.sleep(0.05)
    raise SmokeFailure(f"windows survived shutdown: {titles}")


def main() -> int:
    app: subprocess.Popen[str] | None = None
    xtest: XTest | None = None
    try:
        _assert_no_instance()

        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-note-") as temporary:
            data_home = Path(temporary)
            notes_dir = data_home / "lurknotes"
            notes_dir.mkdir()
            notes_path = notes_dir / "notes.json"
            first_id = "11111111-1111-4111-8111-111111111111"
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
                        "id": "22222222-2222-4222-8222-222222222222",
                        "text": "Standup\nnotes",
                        "created": 101.0,
                        "updated": 101.0,
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
            fan = _wait_for_window(FAN_TITLE, app)
            _check_fan(fan)

            fan_snapshot = _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and len(snapshot.get("tab_centers") or []) == 2,
            )
            if fan_snapshot.get("titles") != ["Groceries", "Standup"]:
                raise SmokeFailure(
                    f"fan titles are {fan_snapshot.get('titles')}, expected array order"
                )

            xtest = XTest()
            _click_first_tab(xtest, fan, fan_snapshot)
            note_window = _wait_for_window(NOTE_TITLE, app)
            _wait_geometry(note_window, _expected_panel_rect(_effective_scale()))
            _check_dark(note_window, rail=True)

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
            print("smoke-note: tab click opened the note, cursor at end, text inserted")

            _wait_for_text_on_disk(notes_path, expected_text)
            backup = json.loads((notes_dir / "notes.bak.json").read_text(encoding="utf-8"))
            if backup["notes"][0]["text"] != original_text:
                raise SmokeFailure("notes.bak.json does not hold the previous file")
            if (notes_dir / "notes.bak.json").read_bytes() != original_bytes:
                raise SmokeFailure("notes.bak.json bytes differ from the previous file")

            app.kill()  # SIGKILL: the debounce/save must already be durable
            app.wait(timeout=5)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE))

            after_kill = json.loads(notes_path.read_text(encoding="utf-8"))
            if after_kill.get("version") != 1:
                raise SmokeFailure("notes.json lost its version after SIGKILL")
            if after_kill["notes"][0]["text"] != expected_text:
                raise SmokeFailure("notes.json lost the typed text after SIGKILL")
            if after_kill["notes"][0]["updated"] <= after_kill["notes"][0]["created"]:
                raise SmokeFailure("updated timestamp was not bumped")
            if after_kill["notes"][1]["text"] != "Standup\nnotes":
                raise SmokeFailure("the second note changed unexpectedly")
            if (notes_dir / "notes.json.tmp").exists():
                raise SmokeFailure("notes.json.tmp survived a successful save")
            print("smoke-note: SIGKILL after debounce left valid JSON with the text")

            restart_dump = data_home / "restart-dump.json"
            close_typed = "\nClosed before debounce"
            app = _start_app(data_home, restart_dump, close_typed)
            fan = _wait_for_window(FAN_TITLE, app)
            restart_fan = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and len(snapshot.get("tab_centers") or []) == 2,
            )
            _click_first_tab(xtest, fan, restart_fan)
            _wait_for_window(NOTE_TITLE, app)
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
            xtest.press_escape()
            _wait_for_window(FAN_TITLE, app)
            _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("current_id") is None,
            )
            _wait_for_text_on_disk(notes_path, closed_text)
            print("smoke-note: Esc returned to the fan and flushed the pending text")
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
