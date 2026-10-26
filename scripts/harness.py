"""Common harness for the live X11 smoke scripts.

The smokes all need the same low-level plumbing: run an X11 query, compute the
surface scale, build an isolated XDG environment, start/stop one app, and wait
for its JSON dump. Keeping it here means a fix (for example waiting out a
concurrent window) lands once. Script-specific observation — geometry, pixels,
XTest gestures, window titles — stays in each smoke.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "lurknotes"


class SmokeFailure(Exception):
    """A smoke check failed; the script prints this and exits 1."""


def run(*command: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SmokeFailure(
            f"{' '.join(command)} failed ({result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def effective_scale() -> float:
    """The surface scale GDK will use: GDK_SCALE override, else Xft.dpi."""
    override = os.environ.get("GDK_SCALE")
    if override:
        return float(override)
    output = run("xrdb", "-query")
    match = re.search(r"Xft\.dpi:\s*([0-9.]+)", output)
    if match is None:
        return 1.0
    return float(match.group(1)) / 96.0


def workarea() -> tuple[int, int, int, int]:
    output = run("xprop", "-root", "_NET_WORKAREA")
    match = re.search(r"_NET_WORKAREA\(CARDINAL\)\s*=\s*(.+)", output)
    if match is None:
        raise SmokeFailure("root window has no _NET_WORKAREA; cannot check geometry")
    values = [int(value) for value in re.findall(r"\d+", match.group(1))]
    if len(values) < 4:
        raise SmokeFailure(f"unexpected _NET_WORKAREA: {output.strip()}")
    return values[0], values[1], values[2], values[3]


def app_id(prefix: str) -> str:
    """A unique application id so concurrent worktrees cannot collide."""
    return f"dev.lurknotes.LurkNotes.{prefix}.s{os.getpid()}"


def mark_onboarded(data_home: Path) -> None:
    """Returning user for smokes that are not testing the first-launch banner.

    The banner changes fan/editor geometry and dark-pixel samples. Ticket 09's
    onboarding smoke runs against a fresh data dir instead.
    """
    marker = Path(data_home) / "lurknotes" / "onboarded"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("onboarded\n", encoding="utf-8")
    except OSError:
        # Storage tests deliberately make the data dir unwritable; onboarding
        # is outside what they assert.
        pass


def make_env(
    data_home: Path,
    app: str,
    *,
    dump: Path | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """An isolated environment: temp XDG dirs, X11 backend, unique app id."""
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_APP_ID": app,
        }
    )
    if dump is not None:
        env["LURKNOTES_TEST_DUMP"] = str(dump)
    if extra:
        env.update(extra)
    return env


def launch(
    args: list[str],
    env: dict[str, str],
    *,
    launcher: Path = LAUNCHER,
    cwd: Path = ROOT,
) -> subprocess.Popen[str]:
    """Start one app process and remember its id/env for later commands."""
    process = subprocess.Popen(
        [str(launcher), *args],
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.lurk_app_id = env.get("LURKNOTES_APP_ID")  # type: ignore[attr-defined]
    process.lurk_env = env  # type: ignore[attr-defined]
    return process


def ensure_running(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        return
    stdout, stderr = process.communicate(timeout=5)
    raise SmokeFailure(
        f"app exited with {process.returncode} unexpectedly\n"
        f"stdout: {stdout[-2000:]}\nstderr: {stderr[-2000:]}"
    )


def stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_dump(
    path: Path,
    process: subprocess.Popen[str],
    predicate: Callable[[dict], bool],
    timeout: float = 8.0,
    interval: float = 0.05,
) -> dict:
    """Poll the JSON dump until *predicate* is true; never trust a stale file."""
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        ensure_running(process)
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            last = snapshot
            if predicate(snapshot):
                return snapshot
        time.sleep(interval)
    raise SmokeFailure(f"deck snapshot never matched; last dump: {last}")


def assert_app_id_free(app: str) -> None:
    """A same-id instance would receive our launch and exit 0 (PLATFORM §10)."""
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
            app,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        # No gdbus or no session bus; the spawn below would fail visibly.
        return
    if "true" in result.stdout.lower():
        raise SmokeFailure(f"another LurkNotes instance owns {app}; retry")
