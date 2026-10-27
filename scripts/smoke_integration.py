#!/usr/bin/env python3
"""Prove ticket 09 through the real CLI and X11 UI.

Runs, each with isolated XDG dirs and a unique application id:

1. cold ``new`` creates and opens a note; a warm second process delivers
   ``new`` synchronously and reuses the untouched note; only the primary
   process exists.
2. bare ``lurknotes`` maps the fan immediately with the pointer far from the
   deck, so the hover timer cannot be the cause.
3. ``--autostart`` maps only the strip, steals no focus, writes no notes, and
   a second ``--autostart`` process exits without starting another app.
4. a refused activation (simulated) shows "Click to type"; the first click
   sets WM_HINTS input, focuses the editor, hides the hint, and typing lands.
5. onboarding is shown on the first visible deck and not after a restart.
6. ``--install-autostart`` writes the expected file into a temp XDG config.
7. ticket 08 gates: ``new`` on read-only and overwrite-blocked decks shows the
   status banner instead of silently doing nothing.

Exits 0 on success, 1 with a message otherwise. Always stops the processes it
starts and only touches windows whose ``_NET_WM_PID`` is its own primary.
"""

from __future__ import annotations

import json
import os
import re
import stat
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
)

SmokeFailure = base.SmokeFailure


def app_id(name: str) -> str:
    return f"dev.lurknotes.LurkNotes.integrationSmoke.s{os.getpid()}.{name}"


def env_for(
    data_home: Path,
    app_id_value: str,
    dump: Path,
    **extra: str,
) -> dict[str, str]:
    data_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home / "data"),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_APP_ID": app_id_value,
            "LURKNOTES_TEST_DUMP": str(dump),
            "LURKNOTES_TEST_CONTROL": "1",
            "LURKNOTES_TEST_PIN_DECK": "1",
        }
    )
    env.update(extra)
    return env


def start(
    argv: list[str],
    env: dict[str, str],
    **popen_kwargs,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(ROOT / "lurknotes"), *argv],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,
    )


def run_second(
    argv: list[str], env: dict[str, str], timeout: float = 5.0
) -> tuple[int, float, subprocess.Popen[str]]:
    """Run a second process synchronously; it must hand argv over and exit."""
    started = time.monotonic()
    process = start(argv, env)
    try:
        process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        base._stop(process)
        raise SmokeFailure(
            f"second process {argv!r} blocked instead of handing off"
        ) from exc
    elapsed = time.monotonic() - started
    if process.returncode != 0:
        raise SmokeFailure(
            f"second process {argv!r} exited {process.returncode}, expected 0"
        )
    if Path(f"/proc/{process.pid}").exists():
        raise SmokeFailure(f"second process {process.pid} is still alive")
    return process.returncode, elapsed, process


def processes_with_app_id(value: str) -> list[int]:
    needle = f"LURKNOTES_APP_ID={value}".encode()
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environ = (entry / "environ").read_bytes()
        except OSError:
            continue
        if needle in environ:
            found.append(int(entry.name))
    return sorted(found)


def assert_only_primary(primary: subprocess.Popen[str], value: str) -> None:
    owners = processes_with_app_id(value)
    if owners != [primary.pid]:
        raise SmokeFailure(
            f"expected only the primary pid {primary.pid}, found {owners}"
        )


def wait_dump(
    dump: Path,
    process: subprocess.Popen[str],
    predicate,
    timeout: float = base.DUMP_TIMEOUT,
) -> dict:
    return base._wait_dump(dump, process, predicate, timeout=timeout)


def active_window() -> int | None:
    output = base._run("xprop", "-root", "_NET_ACTIVE_WINDOW")
    match = re.search(r"0x[0-9a-f]+", output)
    if match is None:
        raise SmokeFailure(f"cannot read _NET_ACTIVE_WINDOW: {output.strip()}")
    return int(match.group(0), 16) or None


def owned_xids(process: subprocess.Popen[str], titles) -> set[int]:
    owned: set[int] = set()
    for title in titles:
        owned.update(int(window, 16) for window in base._windows_titled(title, process.pid))
    return owned


def assert_no_edit_windows(process: subprocess.Popen[str]) -> None:
    for title in (FAN_TITLE, NOTE_TITLE):
        for window in base._windows_titled(title, process.pid):
            info = base._window_info(window)
            if info.get("map_state") == "IsViewable":
                raise SmokeFailure(f"{title!r} is mapped during a quiet start")


def notes_path(data_home: Path) -> Path:
    return data_home / "data" / "lurknotes" / "notes.json"


def write_note_file(data_home: Path, payload: dict | None) -> Path:
    path = notes_path(data_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload is None:
        path.write_text("{not json", encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# -- 1. commands on a live primary --------------------------------------


def run_commands(root: Path) -> None:
    value = app_id("commands")
    base._assert_app_id_free(value)
    data = root / "commands"
    dump = data / "dump.json"
    env = env_for(data, value, dump)
    primary: subprocess.Popen[str] | None = None
    try:
        primary = start(["new"], env)
        base._wait_for_window(STRIP_TITLE, primary)
        opened = wait_dump(
            dump,
            primary,
            lambda d: d.get("state") == "open"
            and len(d.get("ids") or []) == 1
            and d.get("current_id") == (d.get("ids") or [None])[0],
        )
        first_id = opened["current_id"]
        if opened.get("titles") != ["Untitled"]:
            raise SmokeFailure(f"cold new titles are {opened.get('titles')}")
        print("smoke-integration: cold `new` created and opened a note")

        rc, elapsed, _ = run_second(["new"], env)
        reused = wait_dump(
            dump,
            primary,
            lambda d: d.get("state") == "open"
            and d.get("ids") == [first_id]
            and d.get("current_id") == first_id,
            timeout=2.0,
        )
        if reused.get("titles") != ["Untitled"]:
            raise SmokeFailure("the second new replaced the untouched note")
        assert_only_primary(primary, value)
        print(
            "smoke-integration: warm `new` reused the untouched note "
            f"({elapsed * 1000:.0f} ms, rc {rc}), one process only"
        )

    finally:
        if primary is not None:
            base._stop(primary)


# -- 2. bare invocation expands the fan immediately ---------------------


def run_bare_expand(root: Path) -> None:
    value = app_id("bare")
    base._assert_app_id_free(value)
    data = root / "bare"
    dump = data / "dump.json"
    # Disable the hover path: the only way to a fan in this run is the bare
    # command itself. That makes the proof independent of a shared pointer.
    env = env_for(data, value, dump, LURKNOTES_TEST_NO_HOVER="1")
    primary: subprocess.Popen[str] | None = None
    xtest: base.XTest | None = None
    try:
        xtest = base.XTest()
        away_x, away_y = base._away_point()
        xtest.move(away_x, away_y)
        primary = start([], env)
        base._wait_for_window(STRIP_TITLE, primary)
        snapshot = wait_dump(
            dump,
            primary,
            lambda d: d.get("state") == "fan"
            and d.get("last_command") == "expand",
            timeout=3.0,
        )
        print(
            "smoke-integration: bare command dispatched expand; pointer at "
            f"{xtest._pointer()}"
        )
        fan = base._wait_fan_viewable(primary)
        if base._window_info(fan).get("map_state") != "IsViewable":
            raise SmokeFailure("the fan is not viewable after bare `lurknotes`")
        if snapshot.get("onboarding", {}).get("visible") is not True:
            raise SmokeFailure("the first-launch hint did not show with the fan")
        print("smoke-integration: bare `lurknotes` expanded the fan without hover")
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if primary is not None:
            base._stop(primary)


# -- 3. autostart --------------------------------------------------------


def run_autostart(root: Path) -> None:
    value = app_id("autostart")
    base._assert_app_id_free(value)
    data = root / "autostart"
    dump = data / "dump.json"
    env = env_for(data, value, dump, LURKNOTES_TEST_PIN_DECK="0")
    primary: subprocess.Popen[str] | None = None
    xtest: base.XTest | None = None
    try:
        xtest = base.XTest()
        away_x, away_y = base._away_point()
        xtest.move(away_x, away_y)
        primary = start(["--autostart"], env)
        base._wait_for_window(STRIP_TITLE, primary)
        snapshot = wait_dump(
            dump,
            primary,
            lambda d: d.get("state") == "strip",
            timeout=3.0,
        )
        if snapshot.get("onboarding", {}).get("visible"):
            raise SmokeFailure("autostart showed the onboarding panel")
        assert_no_edit_windows(primary)
        if notes_path(data).exists():
            raise SmokeFailure("autostart wrote notes.json before any note existed")
        active = active_window()
        ours = owned_xids(primary, (STRIP_TITLE, FAN_TITLE, NOTE_TITLE))
        if active in ours:
            raise SmokeFailure("autostart stole keyboard focus")
        print(
            "smoke-integration: --autostart mapped only the strip, no focus, "
            "no notes file"
        )

        run_second(["--autostart"], env)
        time.sleep(0.3)
        base._ensure_running(primary)
        assert_only_primary(primary, value)
        assert_no_edit_windows(primary)
        if active_window() in owned_xids(primary, (STRIP_TITLE, FAN_TITLE, NOTE_TITLE)):
            raise SmokeFailure("a second --autostart stole focus")
        if notes_path(data).exists():
            raise SmokeFailure("a second --autostart wrote notes.json")
        strips = base._windows_titled(STRIP_TITLE, primary.pid)
        if len(strips) != 1:
            raise SmokeFailure(f"expected one strip window, found {len(strips)}")
        print("smoke-integration: second --autostart was a no-op command, not an app")
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if primary is not None:
            base._stop(primary)


# -- 4. refused focus ----------------------------------------------------


def run_refused_focus(root: Path) -> None:
    value = app_id("focus")
    base._assert_app_id_free(value)
    data = root / "focus"
    dump = data / "dump.json"
    env = env_for(data, value, dump, LURKNOTES_TEST_REFUSE_FOCUS="1")
    primary: subprocess.Popen[str] | None = None
    xtest: base.XTest | None = None
    try:
        primary = start(["new"], env)
        base._wait_for_window(STRIP_TITLE, primary)
        note_window = base._wait_for_window(NOTE_TITLE, primary)
        hinted = wait_dump(
            dump,
            primary,
            lambda d: d.get("state") == "open"
            and (d.get("focus_hint") or {}).get("visible") is True
            and (d.get("focus_hint") or {}).get("center") is not None,
        )
        if hinted["focus_hint"].get("text") != "Click to type":
            raise SmokeFailure(
                f"unexpected focus hint text {hinted['focus_hint'].get('text')!r}"
            )
        print("smoke-integration: refused focus showed the 'Click to type' hint")

        xtest = base.XTest()
        # Click the editor, not the hint button: the spec's promise is that
        # the first click *anywhere* on the panel takes input, not only the
        # labelled target.
        base._click_editor(xtest, note_window)
        clicked = wait_dump(
            dump,
            primary,
            lambda d: (d.get("focus_hint") or {}).get("visible") is False,
            timeout=3.0,
        )
        properties = base._window_properties(note_window)
        if "Client accepts input or input focus: True" not in properties:
            raise SmokeFailure("the first click did not set WM_HINTS input")
        if clicked.get("panel_focused") is not True:
            raise SmokeFailure("the first click did not focus the editor")
        print(
            "smoke-integration: first click took input, focused the editor, "
            "hid the hint"
        )

        # Typing after the click must reach the note. A concurrent test may
        # steal focus between the assertions and the keystrokes, so only this
        # last step uses the test-only focus grant.
        xtest.focus(note_window)
        xtest.type_text("focusclick")
        wait_dump(
            dump,
            primary,
            lambda d: "focusclick" in (d.get("text") or ""),
            timeout=4.0,
        )
        print("smoke-integration: typing after the click reached the note")
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if primary is not None:
            base._stop(primary)


# -- 5. onboarding once --------------------------------------------------


def run_onboarding_once(root: Path) -> None:
    value = app_id("onboard")
    base._assert_app_id_free(value)
    data = root / "onboard"
    dump = data / "dump.json"
    env = env_for(data, value, dump)
    marker = data / "data" / "lurknotes" / "onboarded"
    first: subprocess.Popen[str] | None = None
    second: subprocess.Popen[str] | None = None
    try:
        first = start([], env)
        base._wait_for_window(STRIP_TITLE, first)
        shown = wait_dump(
            dump,
            first,
            lambda d: d.get("state") == "fan"
            and (d.get("onboarding") or {}).get("visible") is True,
        )
        text = shown["onboarding"].get("text") or ""
        if "Ctrl+Alt+N" not in text:
            raise SmokeFailure(f"onboarding text is missing the hotkey: {text!r}")
        if not marker.is_file():
            raise SmokeFailure("the onboarded marker was not created when shown")
        print("smoke-integration: first launch showed the hotkey onboarding")
        base._stop(first)
        first = None

        dump2 = data / "dump2.json"
        env2 = env_for(data, value, dump2)
        second = start([], env2)
        base._wait_for_window(STRIP_TITLE, second)
        restart = wait_dump(
            dump2,
            second,
            lambda d: d.get("state") == "fan",
        )
        if restart["onboarding"].get("visible") is not False:
            raise SmokeFailure("onboarding appeared again after a restart")
        print("smoke-integration: onboarding stayed hidden after restart")

        # The hinted command really is what the desktop entry/hotkey runs.
        if "lurknotes new" not in text:
            raise SmokeFailure("onboarding does not name the CLI command")
    finally:
        if first is not None:
            base._stop(first)
        if second is not None:
            base._stop(second)


# -- 6. install autostart ------------------------------------------------


def run_install_autostart(root: Path) -> None:
    data = root / "install"
    config = data / "config"
    env = os.environ.copy()
    env.update(
        {
            "XDG_CONFIG_HOME": str(config),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
        }
    )
    # No display is needed for this local command: it must work from a plain
    # terminal before any session is attached.
    env.pop("DISPLAY", None)
    result = subprocess.run(
        [str(ROOT / "lurknotes"), "--install-autostart"],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise SmokeFailure(
            f"--install-autostart exited {result.returncode}: {result.stderr.strip()}"
        )
    target = config / "autostart" / "dev.lurknotes.LurkNotes.desktop"
    if not target.is_file():
        raise SmokeFailure(f"no autostart file at {target}")
    lines = target.read_text(encoding="utf-8").splitlines()
    expected_exec = f"Exec={ROOT / 'lurknotes'} --autostart"
    for required in (
        "[Desktop Entry]",
        "Type=Application",
        "Name=LurkNotes",
        expected_exec,
        "Terminal=false",
        "NoDisplay=true",
        "X-GNOME-Autostart-enabled=true",
        "OnlyShowIn=GNOME;",
    ):
        if required not in lines:
            raise SmokeFailure(f"autostart file is missing {required!r}")
    if stat.S_IMODE(target.stat().st_mode) != 0o644:
        raise SmokeFailure("autostart file is not 0644")
    leftovers = [p.name for p in target.parent.iterdir() if p.name != target.name]
    if leftovers:
        raise SmokeFailure(f"autostart left temp files: {leftovers}")
    print(f"smoke-integration: --install-autostart wrote {target}")


# -- 7. ticket 08 gates --------------------------------------------------


def run_storage_gates(root: Path) -> None:
    # Read-only (future version): new must show the banner, not create a note.
    value = app_id("readonly")
    base._assert_app_id_free(value)
    data = root / "readonly"
    note_id = "11111111-1111-4111-8111-111111111111"
    write_note_file(
        data,
        {
            "version": 2,
            "notes": [
                {
                    "id": note_id,
                    "text": "From the future",
                    "created": 100.0,
                    "updated": 101.0,
                }
            ],
        },
    )
    dump = data / "dump.json"
    env = env_for(data, value, dump)
    primary: subprocess.Popen[str] | None = None
    try:
        primary = start(["new"], env)
        base._wait_for_window(STRIP_TITLE, primary)
        gate = wait_dump(
            dump,
            primary,
            lambda d: d.get("read_only") is True
            and d.get("state") == "fan"
            and (d.get("status") or {}).get("visible") is True,
        )
        if gate.get("ids") != [note_id]:
            raise SmokeFailure(f"read-only new changed the deck: {gate.get('ids')}")
        if not gate["status"].get("message"):
            raise SmokeFailure("read-only new showed an empty status banner")
        print("smoke-integration: read-only `new` surfaced the status banner")
    finally:
        if primary is not None:
            base._stop(primary)

    # Corrupt with no backup: overwrite_blocked, same surface, no write.
    value = app_id("blocked")
    base._assert_app_id_free(value)
    data = root / "blocked"
    path = write_note_file(data, None)
    original = path.read_bytes()
    dump = data / "dump.json"
    env = env_for(data, value, dump)
    primary = None
    try:
        primary = start(["new"], env)
        base._wait_for_window(STRIP_TITLE, primary)
        blocked = wait_dump(
            dump,
            primary,
            lambda d: d.get("overwrite_blocked") is True
            and d.get("state") == "fan"
            and (d.get("status") or {}).get("visible") is True,
        )
        if blocked.get("ids"):
            raise SmokeFailure("overwrite-blocked new created a note")
        if path.read_bytes() != original:
            raise SmokeFailure("overwrite-blocked new touched the corrupt file")
        print(
            "smoke-integration: overwrite-blocked `new` surfaced the banner "
            "and left the file byte-identical"
        )
    finally:
        if primary is not None:
            base._stop(primary)
    if path.read_bytes() != original:
        raise SmokeFailure("shutdown touched the overwrite-blocked file")


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(
            prefix="lurknotes-smoke-integration-"
        ) as temporary:
            root = Path(temporary)
            run_commands(root)
            run_bare_expand(root)
            run_autostart(root)
            run_refused_focus(root)
            run_onboarding_once(root)
            run_install_autostart(root)
            run_storage_gates(root)
            print("smoke-integration: OK")
            return 0
    except SmokeFailure as failure:
        print(f"smoke-integration: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - any crash is a smoke failure
        print(
            f"smoke-integration: FAIL: {type(failure).__name__}: {failure}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
