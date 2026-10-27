#!/usr/bin/env python3
"""Acceptance probes and measurements for ticket 10 (spec §11, §12).

This is the deterministic, isolated harness behind
``.scratch/lurknotes-mvp/acceptance.md``. It does not replace the feature
smokes: those prove the interaction slices, this script covers the remaining
acceptance criteria and records the numbers the ticket asks for.

Everything runs against temporary ``XDG_DATA_HOME`` / ``XDG_CONFIG_HOME``
directories and a unique application id per probe. The real
``~/.local/share/lurknotes``, ``~/.config/autostart`` and the user's GNOME
keybindings are never touched. No network access, no sudo, no extra packages.

Probes
------
* strip rest state after ``--autostart``: geometry, EWMH, no focus, no file
* cold start to the first mapped strip (several runs)
* warm ``lurknotes new`` delivery and visible effect from another directory
* real XTest typing -> editor -> 400 ms autosave latency
* delete + undo at 9.5 s, expiry after 10 s, no undo after a restart
* fullscreen window stacking and pixels (recorded honestly; see acceptance.md)
* strip/panel pixels while mapping (no white flash)
* idle RSS in the strip-only state
* process sockets: no AF_INET/AF_INET6 TCP or UDP
* ``kill -9`` during large writes, repeated, with main/backup validation
* ``--install-autostart`` writes an absolute ``--autostart`` Exec in temp XDG

Usage::

    /home/dev/projects/ubuntu/.venv/bin/python scripts/acceptance.py [--keep]

``--keep`` leaves the temporary tree for inspection. Without it, the tree is
removed and every process the script started is stopped first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import smoke_note as base  # noqa: E402
from lurkn.strings import (  # noqa: E402
    FAN_TITLE,
    NOTE_TITLE,
    STRIP_TITLE,
    UNDO_TOAST,
)

LAUNCHER = ROOT / "lurknotes"
STRIP_RGB = (36, 36, 44)  # #24242c, spec §6.5
PANEL_RGB = (28, 28, 34)  # #1c1c22
NEAR_WHITE = 244
ALL_DESKTOPS = 4294967295
COLD_RUNS = 7
WARM_RUNS = 5
RSS_RUNS = 5
SAVE_RUNS = 3
KILL_RUNS = 15
RSS_TARGET_MB = 120.0
COLD_TARGET_MS = 1500.0
WARM_TARGET_MS = 300.0

_RUNNING: list[subprocess.Popen[str]] = []
_RUN_COUNTER = 0
_RESULTS: dict[str, object] = {}


class AcceptanceFailure(Exception):
    pass


# -- process / environment ------------------------------------------------


def app_id(tag: str) -> str:
    global _RUN_COUNTER
    _RUN_COUNTER += 1
    # Every D-Bus name element must start with a letter: a trailing numeric
    # element makes GApplication reject the id, which silently disables
    # single-instance hand-off and turns a warm command into a second app.
    return (
        f"dev.lurknotes.LurkNotes.acceptance.s{os.getpid()}"
        f".{tag}.r{_RUN_COUNTER}"
    )


def env_for(
    data_home: Path,
    app_id_value: str,
    dump: Path | None = None,
    **extra: str,
) -> dict[str, str]:
    data_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_APP_ID": app_id_value,
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    if dump is not None:
        env["LURKNOTES_TEST_DUMP"] = str(dump)
    env.update(extra)
    return env


def spawn(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path | str = Path("/tmp"),
) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # The smoke helpers drive the test-only "control" action through this
    # attribute; without it gdbus has no destination to call.
    if env.get("LURKNOTES_APP_ID"):
        process.lurk_app_id = env["LURKNOTES_APP_ID"]  # type: ignore[attr-defined]
    _RUNNING.append(process)
    return process


def run_capture(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path | str = Path("/tmp"),
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def stop(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    if process in _RUNNING:
        _RUNNING.remove(process)


def cleanup() -> None:
    for process in list(reversed(_RUNNING)):
        try:
            stop(process)
        except Exception:  # noqa: BLE001 - best effort cleanup
            pass


def read_dump(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def wait_dump(
    path: Path,
    process: subprocess.Popen[str],
    predicate,
    timeout: float = 8.0,
    interval: float = 0.02,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        base._ensure_running(process)
        snapshot = read_dump(path)
        if snapshot is not None:
            last = snapshot
            if predicate(snapshot):
                return snapshot
        time.sleep(interval)
    raise AcceptanceFailure(f"deck dump never matched; last: {last}")


def wait_strip(process: subprocess.Popen[str], timeout: float = 10.0) -> str:
    return base._wait_for_window(STRIP_TITLE, process, timeout=timeout)


def active_window() -> int | None:
    output = base._run("xprop", "-root", "_NET_ACTIVE_WINDOW")
    match = re.search(r"window id # (0x[0-9a-f]+)", output)
    return int(match.group(1), 16) if match else None


def move_pointer_away() -> None:
    """Keep the shared pointer from starting a hover during rest-state probes."""
    xtest = base.XTest()
    try:
        xtest.move(*base._away_point())
    finally:
        xtest.close()


def wait_viewable(
    title: str,
    process: subprocess.Popen[str],
    timeout: float = 8.0,
    interval: float = 0.01,
) -> tuple[str, float]:
    """Return the first window of *title* that is viewable and the time spent."""
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        base._ensure_running(process)
        windows = base._windows_titled(title, process.pid)
        for window in windows:
            info = base._window_info(window)
            if info.get("map_state") == "IsViewable":
                return window, (time.monotonic() - started) * 1000
        time.sleep(interval)
    raise AcceptanceFailure(f"no viewable {title!r} within {timeout:.0f}s")


def seed_notes(path: Path, notes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "notes": notes}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def note(note_id: str, text: str, stamp: float) -> dict:
    return {
        "id": note_id,
        "text": text,
        "created": stamp,
        "updated": stamp,
    }


def workarea() -> tuple[int, int, int, int]:
    return base._workarea()


def assert_strip_rest(
    strip: str,
    snapshot: dict | None,
    process: subprocess.Popen[str],
    notes_path: Path,
    *,
    label: str,
) -> dict:
    info = base._window_info(strip)
    if info.get("map_state") != "IsViewable":
        raise AcceptanceFailure(f"{label}: strip is not viewable")
    properties = base._window_properties(strip)
    states = base._check_states(properties)
    desktop = base._check_desktop(properties)
    base._check_no_focus_hints(properties)
    if desktop != ALL_DESKTOPS:
        raise AcceptanceFailure(f"{label}: _NET_WM_DESKTOP={desktop}")
    # _NET_WORKAREA is already physical X11 pixels; only the 10 logical px
    # width needs the surface scale.
    x, y, width, height = workarea()
    scale = base._effective_scale()
    expected = {
        "x": x + width - round(10 * scale),
        "y": y,
        "width": round(10 * scale),
        "height": height,
    }
    for key in ("x", "y", "width", "height"):
        if int(info[key]) != expected[key]:
            raise AcceptanceFailure(
                f"{label}: strip {key}={info[key]}, expected {expected[key]}"
            )
    fan_windows = [
        window
        for window in base._windows_titled(FAN_TITLE, process.pid)
        if base._window_info(window).get("map_state") == "IsViewable"
    ]
    if fan_windows:
        raise AcceptanceFailure(f"{label}: fan is mapped at rest")
    if snapshot is not None and snapshot.get("state") != "strip":
        raise AcceptanceFailure(f"{label}: deck state is {snapshot.get('state')!r}")
    if notes_path.exists():
        raise AcceptanceFailure(f"{label}: notes.json exists before any note")
    active = active_window()
    own = base._windows_titled(STRIP_TITLE, process.pid)
    if active is not None and own and active == int(own[0], 16):
        raise AcceptanceFailure(f"{label}: autostart took keyboard focus")
    print(
        f"acceptance: {label}: strip {info['width']}x{info['height']}"
        f"+{info['x']}+{info['y']}; states={states}; "
        f"desktop={desktop}; input=False; user_time=0; no focus"
    )
    return info


# -- 1. autostart rest state ---------------------------------------------


def probe_autostart_rest(root: Path) -> None:
    data = root / "autostart"
    dump = data / "dump.json"
    value = app_id("autostart")
    base._assert_app_id_free(value)
    base._mark_onboarded(data)
    move_pointer_away()
    env = env_for(data, value, dump)
    process = spawn([str(LAUNCHER), "--autostart"], env=env)
    try:
        strip = wait_strip(process)
        snapshot = wait_dump(
            dump, process, lambda value: value.get("state") == "strip"
        )
        info = assert_strip_rest(
            strip,
            snapshot,
            process,
            data / "lurknotes" / "notes.json",
            label="autostart",
        )
        _RESULTS["autostart_strip_geometry"] = {
            key: info[key] for key in ("x", "y", "width", "height")
        }
    finally:
        stop(process)


# -- 2. cold start -------------------------------------------------------


def probe_cold_start(root: Path, runs: int = COLD_RUNS) -> None:
    data = root / "cold"
    base._mark_onboarded(data)
    move_pointer_away()
    seed_notes(
        data / "lurknotes" / "notes.json",
        [
            note(
                f"cold-{index}",
                f"Cold note {index}\n" + "body " * 20,
                1000.0 + index,
            )
            for index in range(30)
        ],
    )
    samples: list[float] = []
    for run in range(1, runs + 1):
        value = app_id(f"cold{run}")
        base._assert_app_id_free(value)
        env = env_for(data, value, data / f"dump-{run}.json")
        started = time.monotonic()
        process = spawn([str(LAUNCHER), "--autostart"], env=env)
        try:
            deadline = started + 10.0
            elapsed = None
            while time.monotonic() < deadline:
                base._ensure_running(process)
                for window in base._windows_titled(STRIP_TITLE, process.pid):
                    if (
                        base._window_info(window).get("map_state")
                        == "IsViewable"
                    ):
                        elapsed = (time.monotonic() - started) * 1000
                        break
                if elapsed is not None:
                    break
                time.sleep(0.005)
            if elapsed is None:
                raise AcceptanceFailure(f"cold run {run}: strip never mapped")
            samples.append(elapsed)
            print(f"acceptance: cold start run {run}: {elapsed:.0f} ms to strip")
        finally:
            stop(process)
    median = statistics.median(samples)
    summary = {
        "samples": [round(value) for value in samples],
        "min": round(min(samples)),
        "median": round(median),
        "max": round(max(samples)),
        "target_ms": COLD_TARGET_MS,
    }
    _RESULTS["cold_start_ms"] = summary
    print(
        f"acceptance: cold start median {median:.0f} ms "
        f"(min {min(samples):.0f}, max {max(samples):.0f}; target ≤ "
        f"{COLD_TARGET_MS:.0f} ms)"
    )
    if median > COLD_TARGET_MS:
        raise AcceptanceFailure(f"cold start median {median:.0f} ms over target")


# -- 3. warm new ---------------------------------------------------------


def probe_warm_new(root: Path, runs: int = WARM_RUNS) -> None:
    data = root / "warm"
    dump = data / "dump.json"
    base._mark_onboarded(data)
    move_pointer_away()
    seed_notes(
        data / "lurknotes" / "notes.json",
        [note("warm-existing", "Existing note\nkeep me", 1000.0)],
    )
    value = app_id("warm")
    base._assert_app_id_free(value)
    env = env_for(data, value, dump, LURKNOTES_TEST_CONTROL="1")
    process = spawn([str(LAUNCHER), "--autostart"], env=env)
    delivery: list[float] = []
    effect: list[float] = []
    try:
        wait_strip(process)
        wait_dump(dump, process, lambda snap: snap.get("state") == "strip")
        for run in range(1, runs + 1):
            before = wait_dump(
                dump, process, lambda snap: snap.get("state") in ("strip", "fan")
            )
            before_ids = set(before.get("ids") or [])
            started = time.monotonic()
            # Another process, absolute launcher, cwd outside the checkout:
            # this is what the GNOME custom shortcut holds.
            result = run_capture(
                [str(LAUNCHER), "new"], env=env, cwd=Path("/tmp")
            )
            delivered = (time.monotonic() - started) * 1000
            if result.returncode != 0:
                raise AcceptanceFailure(
                    f"warm new exited {result.returncode}: {result.stderr.strip()}"
                )
            opened = wait_dump(
                dump,
                process,
                lambda snap: snap.get("state") == "open"
                and snap.get("current_id") is not None
                and set(snap.get("ids") or []) - before_ids,
                timeout=3.0,
                interval=0.01,
            )
            observed = (time.monotonic() - started) * 1000
            if opened["current_id"] not in (opened.get("ids") or []):
                raise AcceptanceFailure("warm new did not open the new note")
            delivery.append(delivered)
            effect.append(observed)
            print(
                f"acceptance: warm new run {run}: delivered in "
                f"{delivered:.0f} ms, visible in {observed:.0f} ms"
            )
            # Return to the rest state for the next measurement. Closing the
            # untouched note removes it; the header » collapses the fan.
            if not base._control(process, "close"):
                raise AcceptanceFailure("could not close the warm-test note")
            wait_dump(
                dump,
                process,
                lambda snap: snap.get("state") == "fan"
                and snap.get("current_id") is None,
            )
            if not base._control(process, "header"):
                raise AcceptanceFailure("could not collapse the warm-test fan")
            wait_dump(dump, process, lambda snap: snap.get("state") == "strip")
    finally:
        stop(process)
    summary = {
        "delivery_ms": {
            "samples": [round(value) for value in delivery],
            "min": round(min(delivery)),
            "median": round(statistics.median(delivery)),
            "max": round(max(delivery)),
        },
        "visible_ms": {
            "samples": [round(value) for value in effect],
            "min": round(min(effect)),
            "median": round(statistics.median(effect)),
            "max": round(max(effect)),
        },
        "target_ms": WARM_TARGET_MS,
    }
    _RESULTS["warm_new_ms"] = summary
    print(
        f"acceptance: warm new median delivery "
        f"{statistics.median(delivery):.0f} ms, visible "
        f"{statistics.median(effect):.0f} ms (target ≤ {WARM_TARGET_MS:.0f} ms)"
    )
    if statistics.median(effect) > WARM_TARGET_MS:
        raise AcceptanceFailure("warm new visible effect over target")


# -- 4. real typing and the 400 ms save ---------------------------------


def probe_typing_save(root: Path, runs: int = SAVE_RUNS) -> None:
    data = root / "typing"
    dump = data / "dump.json"
    base._mark_onboarded(data)
    seed_notes(
        data / "lurknotes" / "notes.json",
        [note("typing-existing", "Existing note\nkeep me", 1000.0)],
    )
    value = app_id("typing")
    base._assert_app_id_free(value)
    env = env_for(data, value, dump, LURKNOTES_TEST_PIN_DECK="1")
    process = spawn([str(LAUNCHER), "new"], env=env)
    xtest: base.XTest | None = None
    latencies: list[float] = []
    try:
        wait_strip(process)
        note_window, _ = wait_viewable(NOTE_TITLE, process)
        opened = wait_dump(
            dump,
            process,
            lambda snap: snap.get("state") == "open"
            and snap.get("current_id") is not None,
        )
        xtest = base.XTest()
        if not opened.get("panel_focused"):
            base._click_editor(xtest, note_window)
            opened = wait_dump(
                dump, process, lambda snap: snap.get("panel_focused") is True
            )
        notes_path = data / "lurknotes" / "notes.json"
        for run in range(1, runs + 1):
            # XTest.type_text only sends unshifted ASCII, so keep it lower-case.
            typed = f"typed by xtest {run}"
            xtest.type_text(typed)
            typed_snapshot = wait_dump(
                dump,
                process,
                lambda snap: typed in (snap.get("text") or ""),
                timeout=2.0,
                interval=0.01,
            )
            if typed_snapshot.get("state") != "open":
                raise AcceptanceFailure("typing did not stay in the editor")
            # Measure from the last key event (type_text returned) to the
            # moment the production Store.save has replaced notes.json.
            started = time.monotonic()
            deadline = started + 3.0
            saved = None
            while time.monotonic() < deadline:
                try:
                    payload = json.loads(notes_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = None
                if payload is not None and any(
                    typed in item.get("text", "")
                    for item in payload.get("notes", [])
                ):
                    saved = (time.monotonic() - started) * 1000
                    break
                time.sleep(0.005)
            if saved is None:
                raise AcceptanceFailure("typed text never reached notes.json")
            latencies.append(saved)
            print(
                f"acceptance: typing run {run}: {len(typed)} chars reached the "
                f"editor; saved in {saved:.0f} ms"
            )
            opened = typed_snapshot
    finally:
        if xtest is not None:
            xtest.close()
        stop(process)
    summary = {
        "samples": [round(value) for value in latencies],
        "min": round(min(latencies)),
        "median": round(statistics.median(latencies)),
        "max": round(max(latencies)),
        "debounce_ms": 400,
    }
    _RESULTS["typing_save_ms"] = summary
    print(
        f"acceptance: autosave median {statistics.median(latencies):.0f} ms "
        f"(min {min(latencies):.0f}, max {max(latencies):.0f}; debounce 400 ms)"
    )


# -- 5. delete and undo at the real 10 s --------------------------------


class ChordXTest(base.XTest):
    def _chord(self, keysym: int) -> None:
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
        self._chord(0xFF08)

    def ctrl_z(self) -> None:
        self._chord(0x7A)


def probe_delete_undo(root: Path) -> None:
    data = root / "undo"
    dump = data / "dump.json"
    base._mark_onboarded(data)
    ids = ["undo-a", "undo-b", "undo-c"]
    seed_notes(
        data / "lurknotes" / "notes.json",
        [
            note(ids[0], "First note\nbody", 1000.0),
            note(ids[1], "Second note\nbody", 1001.0),
            note(ids[2], "Third note\nbody", 1002.0),
        ],
    )
    notes_path = data / "lurknotes" / "notes.json"
    value = app_id("undo")
    base._assert_app_id_free(value)
    env = env_for(
        data, value, dump, LURKNOTES_TEST_PIN_DECK="1", LURKNOTES_TEST_CONTROL="1"
    )

    def start() -> subprocess.Popen[str]:
        return spawn([str(LAUNCHER)], env=env)

    def disk_ids() -> list[str]:
        payload = json.loads(notes_path.read_text(encoding="utf-8"))
        return [item["id"] for item in payload.get("notes", [])]

    xtest = ChordXTest()
    process: subprocess.Popen[str] | None = None
    try:
        process = start()
        wait_strip(process)
        panel = base._show_fan(xtest, process)
        fan = wait_dump(
            dump,
            process,
            lambda snap: snap.get("state") == "fan"
            and len(snap.get("tab_centers") or []) == 3,
        )
        base._click_first_tab(xtest, panel, fan)
        opened = wait_dump(
            dump,
            process,
            lambda snap: snap.get("state") == "open"
            and snap.get("current_id") == ids[0],
        )
        note_window, _ = wait_viewable(NOTE_TITLE, process)
        base._click_editor(xtest, note_window)
        time.sleep(0.1)

        # Delete, then wait almost the full ten seconds and undo.
        started = time.monotonic()
        xtest.ctrl_backspace()
        deleted = wait_dump(
            dump,
            process,
            lambda snap: snap.get("state") == "open"
            and ids[0] not in (snap.get("ids") or [])
            and (snap.get("toast") or {}).get("visible") is True
            and snap.get("undo_pending") is True,
        )
        deleted_ms = (time.monotonic() - started) * 1000
        if (deleted.get("toast") or {}).get("label") != UNDO_TOAST:
            raise AcceptanceFailure(
                f"unexpected toast text {(deleted.get('toast') or {}).get('label')!r}"
            )
        if disk_ids() != ids[1:]:
            raise AcceptanceFailure(f"delete did not write the file: {disk_ids()}")
        print(
            f"acceptance: delete reached UI+disk in {deleted_ms:.0f} ms; "
            f"toast {UNDO_TOAST!r}"
        )

        time.sleep(9.5)
        still = read_dump(dump)
        if not still or not still.get("undo_pending"):
            raise AcceptanceFailure("undo expired before 9.5 s")
        xtest.focus(note_window)
        xtest.ctrl_z()
        restored = wait_dump(
            dump,
            process,
            lambda snap: ids[0] in (snap.get("ids") or [])
            and snap.get("undo_pending") is False,
        )
        if restored.get("current_id") != ids[0]:
            raise AcceptanceFailure("undo did not reopen the deleted note")
        if ids[0] not in disk_ids():
            raise AcceptanceFailure("undo did not write the restored note")
        print("acceptance: undo after 9.5 s restored the note at its index")
        base._click_editor(xtest, note_window)
        time.sleep(0.1)

        # Delete again and let the real 10 s timer expire.
        xtest.ctrl_backspace()
        wait_dump(
            dump,
            process,
            lambda snap: ids[0] not in (snap.get("ids") or [])
            and snap.get("undo_pending") is True,
        )
        expired_started = time.monotonic()
        expired = wait_dump(
            dump,
            process,
            lambda snap: snap.get("undo_pending") is False
            and (snap.get("toast") or {}).get("visible") is False,
            timeout=13.0,
            interval=0.05,
        )
        expired_ms = (time.monotonic() - expired_started) * 1000
        if expired_ms < 9_000:
            raise AcceptanceFailure(
                f"undo expired after {expired_ms:.0f} ms, expected ~10 s"
            )
        xtest.focus(note_window)
        xtest.ctrl_z()
        time.sleep(0.4)
        after_expiry = read_dump(dump) or expired
        if ids[0] in (after_expiry.get("ids") or []):
            raise AcceptanceFailure("Ctrl+Z restored a note after expiry")
        print(
            f"acceptance: undo expired after {expired_ms:.0f} ms; Ctrl+Z did "
            "nothing"
        )

        # A restart must not remember a pending undo.
        stop(process)
        process = start()
        wait_strip(process)
        restarted = wait_dump(
            dump,
            process,
            lambda snap: snap.get("state") in ("strip", "fan")
            and ids[0] not in (snap.get("ids") or [])
            and snap.get("undo_pending") is False,
        )
        if (restarted.get("toast") or {}).get("visible") is True:
            raise AcceptanceFailure("a toast reappeared after restart")
        panel = base._show_fan(xtest, process)
        xtest.focus(panel)
        xtest.ctrl_z()
        time.sleep(0.5)
        after_restart = read_dump(dump) or restarted
        if ids[0] in (after_restart.get("ids") or []):
            raise AcceptanceFailure("Ctrl+Z after restart restored a note")
        if ids[0] in disk_ids():
            raise AcceptanceFailure("restart rewrote a deleted note")
        print("acceptance: restart forgot the pending undo; Ctrl+Z did nothing")
        _RESULTS["delete_undo"] = {
            "delete_ms": round(deleted_ms),
            "expiry_ms": round(expired_ms),
            "undo_at_9_5s": True,
            "no_undo_after_restart": True,
        }
    finally:
        stop(process)
        xtest.close()


# -- 6. fullscreen stacking ---------------------------------------------


FULLSCREEN_PROBE = r"""
import os
os.environ["GDK_BACKEND"] = "x11"
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GdkX11", "4.0")
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk
import sys
sys.path.insert(0, os.environ["LURKNOTES_SRC"])
from lurkn.x11 import X11

class Probe(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="dev.lurknotes.FullscreenProbe.p%d" % os.getpid(),
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.x11 = X11()

    def do_command_line(self, _command_line):
        window = Gtk.Window(application=self, title="Fullscreen acceptance probe")
        window.set_default_size(900, 700)
        provider = Gtk.CssProvider()
        provider.load_from_string(".fs-acceptance { background-color: #00aa00; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        window.add_css_class("fs-acceptance")
        window.fullscreen()
        window.present()

        def take_focus():
            surface = window.get_surface()
            if surface is None:
                return True
            xid = GdkX11.X11Surface.get_xid(surface)
            self.x11.set_input(xid, True)
            self.x11.allow_focus(xid)
            window.present()
            return False

        GLib.timeout_add(250, take_focus)
        self.hold()
        return 0

Probe().run()
"""


def root_xid() -> str:
    output = base._run("xwininfo", "-root", "-tree")
    match = re.search(r"Window id: (0x[0-9a-f]+)", output)
    if match is None:
        raise AcceptanceFailure("cannot read the X root window id")
    return match.group(1)


def probe_fullscreen(root: Path) -> None:
    data = root / "fullscreen"
    dump = data / "dump.json"
    base._mark_onboarded(data)
    move_pointer_away()
    value = app_id("fullscreen")
    base._assert_app_id_free(value)
    env = env_for(data, value, dump)
    app = spawn([str(LAUNCHER), "--autostart"], env=env)
    probe = None
    try:
        strip = wait_strip(app)
        probe_env = env.copy()
        probe_env["LURKNOTES_SRC"] = str(ROOT / "src")
        probe = spawn(
            [sys.executable, "-c", FULLSCREEN_PROBE],
            env=probe_env,
            cwd=Path("/tmp"),
        )
        fs_window = base._wait_for_window(
            "Fullscreen acceptance probe", probe, timeout=10.0
        )
        time.sleep(0.8)
        properties = base._window_properties(fs_window)
        states = re.search(r"_NET_WM_STATE\(ATOM\) = (.+)", properties)
        state_text = states.group(1) if states else ""
        if "_NET_WM_STATE_FULLSCREEN" not in state_text:
            raise AcceptanceFailure(
                f"probe window is not fullscreen: {state_text!r}"
            )
        focused = "_NET_WM_STATE_FOCUSED" in state_text
        stacking_output = base._run(
            "xprop", "-root", "_NET_CLIENT_LIST_STACKING"
        )
        stacking = re.findall(r"0x[0-9a-f]+", stacking_output)
        strip_hex = hex(int(strip, 16))
        fs_hex = hex(int(fs_window, 16))
        if strip_hex not in stacking or fs_hex not in stacking:
            raise AcceptanceFailure(
                f"stacking list does not contain {strip_hex} and {fs_hex}: "
                f"{stacking}"
            )
        strip_above = stacking.index(strip_hex) > stacking.index(fs_hex)
        # Pixel evidence on the root: the strip column and the fullscreen
        # surface a little further left.
        pixel, _width, _height = base._pixel_sampler(
            base._xwd_image(root_xid())
        )
        x, y, width, height = workarea()
        scale = base._effective_scale()
        strip_point = (
            x + width - round(5 * scale),
            y + round(200 * scale),
        )
        fs_point = (strip_point[0] - round(200 * scale), strip_point[1])
        strip_pixel = pixel(*strip_point)
        fs_pixel = pixel(*fs_point)
        print(
            "acceptance: fullscreen probe: "
            f"states={state_text.strip()}, focused={focused}"
        )
        print(
            "acceptance: fullscreen stacking bottom→top: "
            + ", ".join(stacking)
        )
        print(
            f"acceptance: fullscreen pixels: strip={strip_pixel} "
            f"fullscreen={fs_pixel} at {strip_point}/{fs_point}"
        )
        if strip_above:
            print(
                "acceptance: CRITERION 11 NOT MET: the strip stays above the "
                "focused fullscreen window (Mutter 46 ABOVE over FULLSCREEN)"
            )
        _RESULTS["fullscreen"] = {
            "focused": focused,
            "strip_above": strip_above,
            "strip_pixel": strip_pixel,
            "fullscreen_pixel": fs_pixel,
            "stacking": stacking,
        }
    finally:
        stop(probe)
        stop(app)


# -- 7. dark pixels while mapping ---------------------------------------


def count_near_white(pixel, width: int, height: int, step: int = 8) -> tuple[int, tuple[int, int, int], int]:
    white = 0
    brightest = (0, 0, 0)
    samples = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            observed = pixel(x, y)
            samples += 1
            if sum(observed) > sum(brightest):
                brightest = observed
            if all(channel > NEAR_WHITE for channel in observed):
                white += 1
    return white, brightest, samples


def probe_dark_map(root: Path) -> None:
    data = root / "dark"
    dump = data / "dump.json"
    base._mark_onboarded(data)
    move_pointer_away()
    seed_notes(
        data / "lurknotes" / "notes.json",
        [note("dark-note", "Dark theme\nbody", 1000.0)],
    )
    value = app_id("dark")
    base._assert_app_id_free(value)
    env = env_for(data, value, dump)
    app = spawn([str(LAUNCHER), "--autostart"], env=env)
    xtest = base.XTest()
    try:
        strip = wait_strip(app)
        # xwd reads the server-side contents; an obscured window returns
        # garbage. Put the strip on top first, exactly like the feature smokes.
        base._raise_for_capture(
            xtest, strip, "the strip", points=((5, 200),)
        )
        pixel, width, height = base._pixel_sampler(base._xwd_image(strip))
        strip_rgb = pixel(width // 2, height // 2)
        white, brightest, samples = count_near_white(pixel, width, height, step=4)
        if strip_rgb != STRIP_RGB or white:
            raise AcceptanceFailure(
                f"strip pixels {strip_rgb} white={white}; expected {STRIP_RGB}"
            )
        print(
            f"acceptance: strip pixels {strip_rgb}, {white}/{samples} near-white, "
            f"brightest {brightest}"
        )

        # Map the fan through the bare command (same path as a login/hotkey
        # look at the deck) and capture the first available frames.
        started = time.monotonic()
        run_capture([str(LAUNCHER)], env=env, cwd=Path("/tmp"))
        fan, _ = wait_viewable(FAN_TITLE, app, timeout=5.0, interval=0.005)
        first_ms = (time.monotonic() - started) * 1000
        base._raise_for_capture(xtest, fan, "the fan")
        worst_white = 0
        worst_brightest = (0, 0, 0)
        first_rgb = None
        captures = 0
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            try:
                pixel, width, height = base._pixel_sampler(
                    base._xwd_image(fan)
                )
            except base.SmokeFailure:
                time.sleep(0.01)
                continue
            white, brightest, _samples = count_near_white(
                pixel, width, height, step=8
            )
            if first_rgb is None:
                first_rgb = pixel(width // 2, height - 1)
            worst_white = max(worst_white, white)
            if sum(brightest) > sum(worst_brightest):
                worst_brightest = brightest
            captures += 1
        if first_rgb != PANEL_RGB:
            raise AcceptanceFailure(
                f"first fan frame is {first_rgb}, expected {PANEL_RGB}"
            )
        if worst_white:
            raise AcceptanceFailure(
                f"fan has {worst_white} near-white samples while mapping"
            )
        print(
            f"acceptance: fan mapped in {first_ms:.0f} ms; first frame "
            f"{first_rgb}; {captures} captures, 0 near-white, brightest "
            f"{worst_brightest}"
        )
        _RESULTS["dark"] = {
            "strip_rgb": strip_rgb,
            "panel_first_rgb": first_rgb,
            "near_white": 0,
            "brightest": worst_brightest,
            "map_ms": round(first_ms),
        }
    finally:
        xtest.close()
        stop(app)


# -- 8. idle RSS ---------------------------------------------------------


def rss_mb(process: subprocess.Popen[str]) -> float:
    status = Path(f"/proc/{process.pid}/status").read_text(encoding="utf-8")
    match = re.search(r"^VmRSS:\s+(\d+)\s+kB", status, re.MULTILINE)
    if match is None:
        raise AcceptanceFailure("no VmRSS in /proc status")
    return int(match.group(1)) / 1024.0


def cpu_ticks(process: subprocess.Popen[str]) -> int:
    """utime+stime from /proc/pid/stat, robust to spaces in the comm field."""
    data = Path(f"/proc/{process.pid}/stat").read_text(encoding="utf-8")
    fields = data[data.rindex(")") + 2 :].split()
    return int(fields[11]) + int(fields[12])


def probe_rss(root: Path, runs: int = RSS_RUNS) -> None:
    data = root / "rss"
    base._mark_onboarded(data)
    move_pointer_away()
    seed_notes(
        data / "lurknotes" / "notes.json",
        [
            note(f"rss-{index}", f"Idle note {index}\n" + "body " * 20, 1000.0 + index)
            for index in range(30)
        ],
    )
    samples: list[float] = []
    cpu_samples: list[float] = []
    hz = os.sysconf("SC_CLK_TCK")
    for run in range(1, runs + 1):
        value = app_id(f"rss{run}")
        base._assert_app_id_free(value)
        env = env_for(data, value, data / f"dump-{run}.json")
        process = spawn([str(LAUNCHER), "--autostart"], env=env)
        try:
            wait_strip(process)
            time.sleep(2.0)
            readings = []
            ticks_start = cpu_ticks(process)
            wall_start = time.monotonic()
            for _ in range(3):
                readings.append(rss_mb(process))
                time.sleep(1.0)
            wall = time.monotonic() - wall_start
            cpu_percent = (
                (cpu_ticks(process) - ticks_start) / hz / wall * 100.0
            )
            median = statistics.median(readings)
            samples.append(median)
            cpu_samples.append(cpu_percent)
            print(
                f"acceptance: idle RSS run {run}: "
                f"{median:.1f} MB (samples {[round(v, 1) for v in readings]}), "
                f"CPU {cpu_percent:.2f}% over {wall:.1f}s"
            )
        finally:
            stop(process)
    summary = {
        "samples": [round(value, 1) for value in samples],
        "min": round(min(samples), 1),
        "median": round(statistics.median(samples), 1),
        "max": round(max(samples), 1),
        "target_mb": RSS_TARGET_MB,
        "cpu_percent": {
            "samples": [round(value, 2) for value in cpu_samples],
            "median": round(statistics.median(cpu_samples), 2),
        },
    }
    _RESULTS["idle_rss_mb"] = summary
    print(
        f"acceptance: idle RSS median {statistics.median(samples):.1f} MB "
        f"(min {min(samples):.1f}, max {max(samples):.1f}; target ≤ "
        f"{RSS_TARGET_MB:.0f} MB); idle CPU median "
        f"{statistics.median(cpu_samples):.2f}%"
    )
    if statistics.median(samples) > RSS_TARGET_MB:
        print(
            "acceptance: RSS target missed; record as an accepted deviation "
            "with a Rust threshold (spec §11)"
        )


# -- 9. no network sockets ----------------------------------------------


def socket_inodes(pid: int) -> set[str]:
    inodes: set[str] = set()
    directory = Path(f"/proc/{pid}/fd")
    for entry in directory.iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        match = re.fullmatch(r"socket:\[(\d+)\]", target)
        if match:
            inodes.add(match.group(1))
    return inodes


def net_table(path: str) -> set[str]:
    """Inodes from /proc/net/tcp, tcp6, udp, udp6 (inode is field 10)."""
    inodes: set[str] = set()
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return inodes
    for line in lines:
        fields = line.split()
        if len(fields) > 9:
            inodes.add(fields[9])
    return inodes


def unix_table(path: str = "/proc/net/unix") -> set[str]:
    """Inodes from /proc/net/unix (inode is field 7)."""
    inodes: set[str] = set()
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return inodes
    for line in lines:
        fields = line.split()
        if len(fields) > 6:
            inodes.add(fields[6])
    return inodes


def probe_network(root: Path) -> None:
    data = root / "network"
    base._mark_onboarded(data)
    move_pointer_away()
    value = app_id("network")
    base._assert_app_id_free(value)
    env = env_for(data, value, data / "dump.json")
    process = spawn([str(LAUNCHER), "--autostart"], env=env)
    try:
        wait_strip(process)
        time.sleep(1.5)
        inodes = socket_inodes(process.pid)
        tables = {
            "tcp": net_table("/proc/net/tcp"),
            "tcp6": net_table("/proc/net/tcp6"),
            "udp": net_table("/proc/net/udp"),
            "udp6": net_table("/proc/net/udp6"),
        }
        inet_hits = {
            name: sorted(inodes & table) for name, table in tables.items()
        }
        inet_hits = {name: hits for name, hits in inet_hits.items() if hits}
        unix_hits = sorted(inodes & unix_table())
        lsof = run_capture(
            ["lsof", "-nP", "-p", str(process.pid), "-a", "-i"],
            env=env,
            cwd=Path("/tmp"),
            timeout=10.0,
        )
        lsof_lines = [
            line
            for line in lsof.stdout.splitlines()
            if "lsof:" not in line
        ]
        print(
            f"acceptance: sockets pid {process.pid}: {len(inodes)} total, "
            f"{len(unix_hits)} AF_UNIX (D-Bus expected), "
            f"{sum(len(v) for v in inet_hits.values())} AF_INET/AF_INET6"
        )
        print(
            "acceptance: lsof -p PID -a -i output: "
            + ("<empty>" if not lsof_lines else lsof.stdout.strip())
        )
        if inet_hits:
            raise AcceptanceFailure(f"network sockets open: {inet_hits}")
        if lsof_lines:
            raise AcceptanceFailure(
                f"lsof lists internet sockets: {lsof.stdout.strip()}"
            )
        _RESULTS["network"] = {
            "total_sockets": len(inodes),
            "unix_dbus_sockets": len(unix_hits),
            "inet_sockets": 0,
        }
    finally:
        stop(process)


# -- 10. kill -9 during writes ------------------------------------------


KILL_WRITER = r"""
import os
import sys
from lurkn.notes import Note
from lurkn.store import Store

COUNT = 3000
FILLER = "x" * 3000

def deck(tag):
    return [
        Note(
            id="%s-%04d" % (tag, index),
            text="%s note %04d\n%s" % (tag, index, FILLER),
            created=1000.0 + index,
            updated=1000.0 + index,
        )
        for index in range(COUNT)
    ]

A = deck("A")
B = deck("B")
store = Store()
for generation in range(1000):
    print("SAVE", generation, flush=True)
    store.save(A if generation % 2 == 0 else B)
    print("DONE", generation, flush=True)
"""


def validate_deck(path: Path, *, required: bool) -> tuple[bool, str]:
    if not path.exists():
        return (not required), "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"unparseable: {exc}"
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return False, "bad version"
    notes = payload.get("notes")
    if not isinstance(notes, list) or len(notes) != 3000:
        return False, f"notes length {len(notes) if isinstance(notes, list) else notes!r}"
    tags = set()
    for item in notes:
        if not isinstance(item, dict):
            return False, "non-object note"
        text = item.get("text")
        if not isinstance(text, str):
            return False, "non-string text"
        if not (text.startswith("A note ") or text.startswith("B note ")):
            return False, f"unexpected note text {text[:30]!r}"
        tag = text[0]
        if not isinstance(item.get("created"), (int, float)):
            return False, "bad created"
        if not isinstance(item.get("updated"), (int, float)):
            return False, "bad updated"
        if not isinstance(item.get("id"), str) or not item["id"]:
            return False, "bad id"
        tags.add(tag)
    if len(tags) != 1:
        return False, f"mixed generations: {sorted(tags)}"
    return True, tags.pop()


def probe_kill_stress(root: Path, runs: int = KILL_RUNS) -> None:
    data = root / "kill"
    data.mkdir(parents=True, exist_ok=True)
    notes_path = data / "lurknotes" / "notes.json"
    backup_path = data / "lurknotes" / "notes.bak.json"
    env = env_for(data, app_id("kill"), data / "dump.json")
    completed = 0
    backup_checked = 0
    mid_write = 0
    generations: dict[str, int] = {"A": 0, "B": 0}
    for run in range(1, runs + 1):
        process = spawn(
            [sys.executable, "-c", KILL_WRITER],
            env=env,
            cwd=Path("/tmp"),
        )
        assert process.stdout is not None
        saw_done = False
        killed = False
        try:
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                line = process.stdout.readline()
                if not line:
                    break
                text = line.strip()
                if text == "DONE 0":
                    saw_done = True
                elif text == "SAVE 1" and saw_done:
                    # Kill while the second, large save is in progress. The
                    # first save completed, so notes.json must already exist.
                    # A fixed spread keeps the probe deterministic while
                    # still hitting different points inside the write.
                    time.sleep(0.001 + (run * 0.00263) % 0.039)
                    process.kill()
                    process.wait(timeout=5)
                    killed = True
                    break
            if not killed:
                raise AcceptanceFailure(
                    f"kill run {run}: writer never reached SAVE 1"
                )
            tmp_present = (
                notes_path.parent / "notes.json.tmp"
            ).exists() or (
                notes_path.parent / "notes.bak.json.tmp"
            ).exists()
            mid_write += int(tmp_present)
            ok, detail = validate_deck(notes_path, required=True)
            if not ok:
                raise AcceptanceFailure(
                    f"kill run {run}: notes.json invalid ({detail})"
                )
            generations[detail] += 1
            backup_ok, backup_detail = validate_deck(
                backup_path, required=False
            )
            if not backup_ok:
                raise AcceptanceFailure(
                    f"kill run {run}: notes.bak.json invalid ({backup_detail})"
                )
            if backup_path.exists():
                backup_checked += 1
            completed += 1
            print(
                f"acceptance: kill run {run}: main={detail}, "
                f"backup={backup_detail}, tmp_left={tmp_present}"
            )
        finally:
            stop(process)
    summary = {
        "runs": completed,
        "mid_write_tmp_seen": mid_write,
        "backup_present_and_valid": backup_checked,
        "main_generations": generations,
    }
    _RESULTS["kill_stress"] = summary
    print(
        f"acceptance: kill -9 stress {completed}/{runs} runs: every "
        f"notes.json parsed coherently; {backup_checked} backups validated; "
        f"{mid_write} kills left a temp file (mid-write evidence)"
    )


# -- 11. autostart desktop file -----------------------------------------


def probe_install_autostart(root: Path) -> None:
    data = root / "install"
    env = env_for(data, app_id("install"))
    result = run_capture(
        [str(LAUNCHER), "--install-autostart"], env=env, cwd=Path("/tmp")
    )
    if result.returncode != 0:
        raise AcceptanceFailure(
            f"--install-autostart exited {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    target = (
        data / "config" / "autostart" / "dev.lurknotes.LurkNotes.desktop"
    )
    if not target.is_file():
        raise AcceptanceFailure(f"desktop file missing at {target}")
    contents = target.read_text(encoding="utf-8")
    expected_exec = f"Exec={LAUNCHER} --autostart"
    if expected_exec not in contents:
        raise AcceptanceFailure(
            f"desktop Exec is not the absolute launcher: {contents!r}"
        )
    for required in (
        "NoDisplay=true",
        "X-GNOME-Autostart-enabled=true",
        "OnlyShowIn=GNOME;",
    ):
        if required not in contents:
            raise AcceptanceFailure(f"desktop file lacks {required}")
    validated = None
    if shutil.which("desktop-file-validate"):
        validated = run_capture(
            ["desktop-file-validate", str(target)], env=env, cwd=Path("/tmp")
        )
        if validated.returncode != 0:
            raise AcceptanceFailure(
                f"desktop-file-validate failed: {validated.stderr.strip()}"
            )
    print(
        f"acceptance: --install-autostart wrote {target} with "
        f"{expected_exec!r}; desktop-file-validate rc="
        f"{validated.returncode if validated is not None else 'n/a'}"
    )
    _RESULTS["autostart_desktop"] = str(target)


# -- main ----------------------------------------------------------------


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    if any(argument not in ("--keep",) for argument in argv):
        print("usage: acceptance.py [--keep]", file=sys.stderr)
        return 2
    temporary = Path(tempfile.mkdtemp(prefix="lurknotes-acceptance-"))
    print(f"acceptance: temporary tree {temporary}")
    print(
        "acceptance: DISPLAY=%s GDK_BACKEND=x11; real XDG data/config untouched"
        % os.environ.get("DISPLAY")
    )
    try:
        probe_autostart_rest(temporary)
        probe_cold_start(temporary)
        probe_warm_new(temporary)
        probe_typing_save(temporary)
        probe_delete_undo(temporary)
        probe_fullscreen(temporary)
        probe_dark_map(temporary)
        probe_rss(temporary)
        probe_network(temporary)
        probe_kill_stress(temporary)
        probe_install_autostart(temporary)
    except AcceptanceFailure as failure:
        print(f"acceptance: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report unexpected failures
        print(
            f"acceptance: FAIL: {type(failure).__name__}: {failure}",
            file=sys.stderr,
        )
        return 1
    finally:
        cleanup()
        if keep:
            print(f"acceptance: kept temporary tree {temporary}")
        else:
            shutil.rmtree(temporary, ignore_errors=True)
    print("acceptance: summary " + json.dumps(_RESULTS, sort_keys=True))
    print("acceptance: OK (criterion 11 fullscreen deviation is recorded above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
