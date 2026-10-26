#!/usr/bin/env python3
"""Launch LurkNotes and prove the strip is placed and hinted correctly.

Checks through X11 tools only: one strip window, workarea-relative geometry,
EWMH state, all-desktops desktop, and non-focusing WM hints. Exits 0 on success,
1 with a clear message otherwise. Always stops the app it started.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lurkn.strings import STRIP_TITLE  # noqa: E402

STRIP_LOGICAL_WIDTH = 10  # spec §6, independent of the app's constant
REQUIRED_STATES = {
    "_NET_WM_STATE_ABOVE",
    "_NET_WM_STATE_SKIP_TASKBAR",
    "_NET_WM_STATE_STICKY",
}
ALL_DESKTOPS = 4294967295
STARTUP_TIMEOUT = 10.0
SETTLE_TIMEOUT = 5.0


class SmokeFailure(Exception):
    pass


def _run(*command: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SmokeFailure(
            f"{' '.join(command)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def _effective_scale() -> float:
    """The surface scale GDK will use: GDK_SCALE override, else Xft.dpi."""
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


def _strip_windows() -> list[str]:
    tree = _run("xwininfo", "-root", "-tree")
    pattern = re.compile(r'^\s*(0x[0-9a-f]+)\s+"([^"]*)":')
    windows: list[str] = []
    for line in tree.splitlines():
        match = pattern.match(line)
        if match and match.group(2) == STRIP_TITLE:
            windows.append(match.group(1))
    return windows


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
            "window is missing required _NET_WM_STATE atoms: "
            + ", ".join(sorted(missing))
        )
    if "_NET_WM_STATE_SKIP_PAGER" not in observed:
        raise SmokeFailure("window is missing _NET_WM_STATE_SKIP_PAGER")
    return ", ".join(sorted(observed))


def _check_desktop(properties: str) -> int:
    match = re.search(r"_NET_WM_DESKTOP\(CARDINAL\)\s*=\s*(\d+)", properties)
    if match is None:
        raise SmokeFailure("window has no _NET_WM_DESKTOP")
    desktop = int(match.group(1))
    if desktop != ALL_DESKTOPS:
        raise SmokeFailure(
            f"_NET_WM_DESKTOP is {desktop}, expected {ALL_DESKTOPS} (all desktops)"
        )
    return desktop


def _check_no_focus_hints(properties: str) -> None:
    if "Client accepts input or input focus: False" not in properties:
        raise SmokeFailure("WM_HINTS.input is not False; the strip may take focus")
    if re.search(r"_NET_WM_USER_TIME\(CARDINAL\)\s*=\s*0\b", properties) is None:
        raise SmokeFailure("_NET_WM_USER_TIME is not 0; mapping may activate the strip")


def _ensure_running(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        return
    stdout, stderr = process.communicate(timeout=5)
    raise SmokeFailure(
        f"app exited with {process.returncode} while the strip was checked; "
        "another LurkNotes instance may already be running\n"
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


def main() -> int:
    app: subprocess.Popen[str] | None = None
    try:
        # Gtk.Application is single-instance: a second process would hand the
        # launch to an existing one and exit. Checking the window beforehand is
        # the only reliable way to know the window we inspect is ours — poll()
        # races with the D-Bus hand-off and can miss the early exit.
        existing = _strip_windows()
        if existing:
            raise SmokeFailure(
                "another LurkNotes instance is already running "
                f"(window {', '.join(existing)}); stop it and retry"
            )

        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-") as data_home:
            env = os.environ.copy()
            env["XDG_DATA_HOME"] = data_home
            env["NO_AT_BRIDGE"] = "1"
            app = subprocess.Popen(
                [str(ROOT / "lurknotes")],
                cwd=str(ROOT),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            deadline = time.monotonic() + STARTUP_TIMEOUT
            windows: list[str] = []
            while time.monotonic() < deadline:
                if app.poll() is not None:
                    stdout, stderr = app.communicate(timeout=5)
                    raise SmokeFailure(
                        f"app exited with {app.returncode} before showing the strip\n"
                        f"stdout: {stdout[-2000:]}\nstderr: {stderr[-2000:]}"
                    )
                windows = _strip_windows()
                if len(windows) > 1:
                    raise SmokeFailure(f"expected one strip window, found {len(windows)}")
                if windows:
                    break
                time.sleep(0.1)
            if not windows:
                raise SmokeFailure(
                    f"no window titled {STRIP_TITLE!r} appeared within "
                    f"{STARTUP_TIMEOUT:.0f}s"
                )

            window = windows[0]
            workarea_x, workarea_y, workarea_w, workarea_h = _workarea()
            scale = _effective_scale()
            expected = {
                "x": workarea_x + workarea_w - round(STRIP_LOGICAL_WIDTH * scale),
                "y": workarea_y,
                "width": round(STRIP_LOGICAL_WIDTH * scale),
                "height": round(workarea_h),
            }

            settle_deadline = time.monotonic() + SETTLE_TIMEOUT
            while True:
                info = _window_info(window)
                observed = {key: info.get(key) for key in expected}
                if observed == expected or time.monotonic() >= settle_deadline:
                    break
                time.sleep(0.1)

            if info.get("map_state") != "IsViewable":
                raise SmokeFailure(
                    f"strip is not viewable (Map State: {info.get('map_state')})"
                )
            if observed != expected:
                raise SmokeFailure(
                    "strip geometry does not match the workarea: "
                    f"observed x={observed['x']} y={observed['y']} "
                    f"{observed['width']}x{observed['height']}, "
                    f"expected x={expected['x']} y={expected['y']} "
                    f"{expected['width']}x{expected['height']} "
                    f"(workarea {workarea_x},{workarea_y} "
                    f"{workarea_w}x{workarea_h}, scale {scale:g})"
                )

            properties = _window_properties(window)
            states = _check_states(properties)
            desktop = _check_desktop(properties)
            _check_no_focus_hints(properties)
            _ensure_running(app)

            print(f"smoke: window {window} {STRIP_TITLE!r}")
            print(
                "smoke: geometry "
                f"x={observed['x']} y={observed['y']} "
                f"{observed['width']}x{observed['height']} "
                f"(workarea {workarea_x},{workarea_y} {workarea_w}x{workarea_h}, "
                f"scale {scale:g})"
            )
            print(f"smoke: _NET_WM_STATE = {states}")
            print(f"smoke: _NET_WM_DESKTOP = {desktop}")
            print("smoke: WM_HINTS input = False, _NET_WM_USER_TIME = 0")
            print("smoke: OK")
            return 0

    except SmokeFailure as failure:
        print(f"smoke: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a smoke failure
        print(f"smoke: FAIL: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    finally:
        if app is not None:
            _stop(app)


if __name__ == "__main__":
    raise SystemExit(main())
