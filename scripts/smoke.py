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

import harness as h  # noqa: E402

from lurkn.strings import STRIP_TITLE  # noqa: E402

SmokeFailure = h.SmokeFailure

STRIP_LOGICAL_WIDTH = 10  # spec §6, independent of the app's constant
REQUIRED_STATES = {
    "_NET_WM_STATE_ABOVE",
    "_NET_WM_STATE_SKIP_TASKBAR",
    "_NET_WM_STATE_STICKY",
}
ALL_DESKTOPS = 4294967295
STARTUP_TIMEOUT = 10.0
SETTLE_TIMEOUT = 5.0


_run = h.run
_effective_scale = h.effective_scale
_workarea = h.workarea


def _strip_windows(pid: int | None = None) -> list[str]:
    tree = _run("xwininfo", "-root", "-tree")
    pattern = re.compile(r'^\s*(0x[0-9a-f]+)\s+"([^"]*)":')
    windows = [
        match.group(1)
        for line in tree.splitlines()
        if (match := pattern.match(line)) and match.group(2) == STRIP_TITLE
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


_ensure_running = h.ensure_running
_stop = h.stop
_assert_app_id_free = h.assert_app_id_free


def main() -> int:
    app: subprocess.Popen[str] | None = None
    try:
        # Gtk.Application is single-instance keyed by application id. A second
        # process with the same id would hand the launch to the existing one
        # and exit, so the smoke test uses its own id and checks that the
        # window belongs to the process it spawned (_NET_WM_PID).
        app_id = h.app_id("smoke")
        _assert_app_id_free(app_id)

        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-") as data_home:
            # Returning user: ticket 09's onboarding banner is covered by its
            # own smoke against a fresh data dir.
            data_home = Path(data_home)
            h.mark_onboarded(data_home)
            env = h.make_env(data_home, app_id)
            app = h.launch([], env)
            deadline = time.monotonic() + STARTUP_TIMEOUT
            windows: list[str] = []
            while time.monotonic() < deadline:
                if app.poll() is not None:
                    stdout, stderr = app.communicate(timeout=5)
                    raise SmokeFailure(
                        f"app exited with {app.returncode} before showing the strip\n"
                        f"stdout: {stdout[-2000:]}\nstderr: {stderr[-2000:]}"
                    )
                windows = _strip_windows(app.pid)
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
