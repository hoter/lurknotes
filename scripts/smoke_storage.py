#!/usr/bin/env python3
"""Prove ticket 08 storage recovery through the real X11 UI.

Scenarios:
1. corrupt main + valid backup -> banner, backup notes in the fan, corrupt file
   quarantined, recovered deck persisted, restart shows it without a warning;
2. corrupt main + corrupt backup -> empty fan and a Continue banner, file bytes
   untouched after a clean shutdown;
3. future version -> read-only banner, notes visible, no bytes written even
   after typing and a normal shutdown;
4. unwritable data directory -> app keeps the typed text in memory, shows
   "Save failed", then persists it once permissions return.

All runs use an isolated XDG tree and a unique application id. Exits 0 on
success, 1 with a clear message otherwise, and always stops the process it
started.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import harness as h  # noqa: E402
import smoke_note as base  # noqa: E402

SmokeFailure = base.SmokeFailure

NOTES_DIR = "lurknotes"
RUN = 0


def start_app(
    data_home: Path, dump: Path, type_text: str | None = None
) -> subprocess.Popen[str]:
    global RUN
    RUN += 1
    base._mark_onboarded(data_home)
    extra = {
        "LURKNOTES_TEST_CONTROL": "1",
        "LURKNOTES_TEST_PIN_DECK": "1",
    }
    if type_text is not None:
        extra["LURKNOTES_TEST_TYPE"] = type_text
    env = h.make_env(
        data_home,
        h.app_id(f"storageSmoke.r{RUN}"),
        dump=dump,
        extra=extra,
    )
    return h.launch([], env)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def note(note_id: str, text: str) -> dict:
    return {"id": note_id, "text": text, "created": 100.0, "updated": 100.0}


def payload(*notes: dict) -> dict:
    return {"version": 1, "notes": list(notes)}


def corrupt_files(notes_dir: Path) -> list[Path]:
    return sorted(notes_dir.glob("notes.corrupt-*.json"))


def wait_for_our_windows(app: subprocess.Popen[str], timeout: float = 5.0) -> None:
    """Wait for the windows of *this* process only; other agents may run one."""
    pid = app.pid
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(
            base._windows_titled(title, pid)
            for title in (base.STRIP_TITLE, base.FAN_TITLE, base.NOTE_TITLE)
        ):
            return
        time.sleep(0.05)
    raise SmokeFailure(f"windows of pid {pid} survived shutdown")


def fan_snapshot(dump: Path, app: subprocess.Popen[str], predicate) -> dict:
    return base._wait_dump(dump, app, lambda snapshot: snapshot.get("state") == "fan"
                           and predicate(snapshot))


def status_of(snapshot: dict) -> dict:
    status = snapshot.get("status")
    if not isinstance(status, dict):
        raise SmokeFailure(f"snapshot has no status block: {snapshot}")
    return status


def scenario_recover_from_backup(temporary: Path, xtest: base.XTest) -> None:
    data_home = temporary / "recover"
    notes_dir = data_home / NOTES_DIR
    notes_dir.mkdir(parents=True)
    path = notes_dir / "notes.json"
    backup = notes_dir / "notes.bak.json"
    recovered = [note("a", "Recovered first"), note("b", "Recovered second")]
    path.write_text("{corrupt", encoding="utf-8")
    corrupt_bytes = path.read_bytes()
    write_json(backup, payload(*recovered))
    backup_bytes = backup.read_bytes()

    dump = data_home / "dump.json"
    app = start_app(data_home, dump)
    try:
        fan = base._show_fan(xtest, app)
        snapshot = fan_snapshot(
            dump,
            app,
            lambda snap: status_of(snap)["visible"]
            and status_of(snap)["kind"] == "warning"
            and snap["titles"] == ["Recovered first", "Recovered second"],
        )
        try:
            base._raise_for_capture(xtest, fan, "the recovery banner")
        except SmokeFailure as exc:
            print(f"smoke-storage: banner pixel check skipped ({exc})")
        else:
            pixel, width, height = base._pixel_sampler(base._xwd_image(fan))
            banner = pixel(2, 2)
            if banner not in ((58, 58, 70), (74, 47, 53)):
                raise SmokeFailure(
                    f"status banner is #{banner[0]:02x}{banner[1]:02x}"
                    f"{banner[2]:02x}, expected a dark #3a3a46/#4a2f35 surface"
                )
            for y in range(0, height, 8):
                for x in range(0, width, 8):
                    red, green, blue = pixel(x, y)
                    if red > 245 and green > 245 and blue > 245:
                        raise SmokeFailure(
                            f"status banner has a near-white pixel at {x},{y}"
                        )
            print("smoke-storage: recovery banner surface is dark")
        status = status_of(snapshot)
        if "damaged" not in status["message"] or not status["dismissible"]:
            raise SmokeFailure(f"unexpected recovery banner: {status}")
        quarantined = corrupt_files(notes_dir)
        if len(quarantined) != 1 or quarantined[0].read_bytes() != corrupt_bytes:
            raise SmokeFailure("the corrupt main file was not preserved exactly once")
        if backup.read_bytes() != backup_bytes:
            raise SmokeFailure("the valid backup was modified during recovery")
        if read_json(path) != payload(*recovered):
            raise SmokeFailure("the recovered deck was not persisted to notes.json")
        if (notes_dir / "notes.json.tmp").exists():
            raise SmokeFailure("notes.json.tmp survived a successful recovery")
        print("smoke-storage: corrupt main recovered from backup and persisted")
    finally:
        base._stop(app)
    wait_for_our_windows(app)

    restart_dump = data_home / "restart.json"
    app = start_app(data_home, restart_dump)
    try:
        base._show_fan(xtest, app)
        fan_snapshot(
            restart_dump,
            app,
            lambda snap: snap["titles"] == ["Recovered first", "Recovered second"],
        )
        snapshot = fan_snapshot(restart_dump, app, lambda snap: True)
        if status_of(snapshot)["visible"]:
            raise SmokeFailure("recovery banner reappeared after a clean restart")
        if len(corrupt_files(notes_dir)) != 1:
            raise SmokeFailure("restart created another corrupt-file copy")
        print("smoke-storage: restart shows the recovered deck without a warning")
    finally:
        base._stop(app)
    wait_for_our_windows(app)


def click_center(
    xtest: base.XTest, window: str, center: list[float], scale: float
) -> None:
    info = base._window_info(window)
    xtest.click(
        int(info["x"]) + round(center[0] * scale),
        int(info["y"]) + round(center[1] * scale),
    )


def scenario_double_corruption(temporary: Path, xtest_holder: list) -> None:
    data_home = temporary / "double"
    notes_dir = data_home / NOTES_DIR
    notes_dir.mkdir(parents=True)
    path = notes_dir / "notes.json"
    backup = notes_dir / "notes.bak.json"
    path.write_text("{corrupt main", encoding="utf-8")
    backup.write_text("{corrupt backup", encoding="utf-8")
    main_bytes = path.read_bytes()
    backup_bytes = backup.read_bytes()
    typed = "\nAfter Continue"

    dump = data_home / "dump.json"
    app = start_app(data_home, dump, type_text=typed)
    try:
        xtest = xtest_holder[0]
        fan = base._show_fan(xtest, app)
        snapshot = fan_snapshot(
            dump,
            app,
            lambda snap: status_of(snap)["visible"]
            and status_of(snap)["action"]
            and snap["titles"] == []
            and snap["overwrite_blocked"] is True,
        )
        status = status_of(snapshot)
        if status["kind"] != "error" or status["action_label"] != "Continue":
            raise SmokeFailure(f"unexpected corruption banner: {status}")
        if path.read_bytes() != main_bytes or backup.read_bytes() != backup_bytes:
            raise SmokeFailure("startup wrote to a doubly-corrupt deck")
        if corrupt_files(notes_dir) or (notes_dir / "notes.json.tmp").exists():
            raise SmokeFailure("startup created files before the explicit action")
        print("smoke-storage: double corruption shows Continue and writes nothing")

        action_center = status.get("action_center")
        if not action_center:
            raise SmokeFailure("the Continue button has no clickable centre")
        scale = base._effective_scale()
        click_center(xtest, fan, action_center, scale)
        after_continue = fan_snapshot(
            dump,
            app,
            lambda snap: snap["overwrite_blocked"] is False
            and status_of(snap)["visible"] is False,
        )
        if path.read_bytes() != main_bytes or backup.read_bytes() != backup_bytes:
            raise SmokeFailure("Continue alone wrote to the corrupt deck")
        print("smoke-storage: Continue unblocked saves without writing by itself")

        new_center = after_continue.get("new_button_center")
        if not new_center:
            raise SmokeFailure("fan has no + button after Continue")
        click_center(xtest, fan, new_center, scale)
        note_window = base._wait_for_window(base.NOTE_TITLE, app)
        base._wait_dump(
            dump,
            app,
            lambda snap: snap.get("typed") is True
            and snap.get("unsaved") is False
            and snap.get("text") == typed,
            timeout=10.0,
        )
        deadline = time.monotonic() + 5.0
        saved: dict | None = None
        while time.monotonic() < deadline:
            try:
                saved = read_json(path)
            except (OSError, ValueError):
                pass
            else:
                if saved["notes"] and saved["notes"][0]["text"] == typed:
                    break
            time.sleep(0.05)
        if saved is None or saved["notes"][0]["text"] != typed:
            raise SmokeFailure(f"the post-Continue note was not saved: {saved}")
        quarantined = corrupt_files(notes_dir)
        if len(quarantined) != 1 or quarantined[0].read_bytes() != main_bytes:
            raise SmokeFailure("the corrupt main was not preserved before overwrite")
        # Creation is memory-only now (spec §5.2), so this first save
        # quarantines the confirmed corrupt main and has no valid previous
        # deck to copy. A second edit exercises normal ticket-02 backup
        # semantics: the just-written deck becomes notes.bak.json.
        base._click_editor(xtest, note_window)
        xtest.focus(note_window)
        xtest.type_text("x")
        edited = typed + "x"
        base._wait_dump(
            dump,
            app,
            lambda snap: snap.get("text") == edited
            and snap.get("unsaved") is False,
            timeout=5.0,
        )
        deadline = time.monotonic() + 5.0
        backup_deck: dict | None = None
        while time.monotonic() < deadline:
            try:
                backup_deck = read_json(backup)
            except (OSError, ValueError):
                backup_deck = None
            if backup_deck and backup_deck.get("version") == 1:
                break
            time.sleep(0.05)
        if backup_deck is None or backup_deck.get("version") != 1:
            raise SmokeFailure(
                f"notes.bak.json is not a valid deck after the second save: "
                f"{backup_deck!r}"
            )
        if backup_deck["notes"][0]["text"] != typed:
            raise SmokeFailure(
                "the second save did not back up the first saved deck: "
                f"{backup_deck['notes'][0]['text']!r}"
            )
        if (notes_dir / "notes.json.tmp").exists():
            raise SmokeFailure("a temp file survived the post-Continue save")
        print("smoke-storage: after Continue the next save quarantined the corrupt file")
    finally:
        base._stop(app)
    wait_for_our_windows(app)
    if path.read_bytes() == main_bytes:
        raise SmokeFailure("the post-Continue deck did not survive shutdown")
    try:
        final_backup = read_json(backup)
    except (OSError, ValueError) as exc:
        raise SmokeFailure(f"shutdown left an invalid backup: {exc}") from exc
    if final_backup.get("version") != 1:
        raise SmokeFailure(f"shutdown left an invalid backup: {final_backup}")
    if len(corrupt_files(notes_dir)) != 1:
        raise SmokeFailure("shutdown lost the quarantined corrupt file")
    print("smoke-storage: explicit action + save persisted and preserved the original")


def scenario_future_version(temporary: Path, xtest_holder: list) -> None:
    data_home = temporary / "future"
    notes_dir = data_home / NOTES_DIR
    notes_dir.mkdir(parents=True)
    path = notes_dir / "notes.json"
    write_json(path, {"version": 99, "notes": [note("a", "Future note")]})
    original = path.read_bytes()
    typed = "\nTyped into read-only"

    dump = data_home / "dump.json"
    app = start_app(data_home, dump, type_text=typed)
    try:
        xtest = xtest_holder[0]
        fan = base._show_fan(xtest, app)
        snapshot = fan_snapshot(
            dump,
            app,
            lambda snap: status_of(snap)["visible"]
            and snap["read_only"] is True
            and snap["titles"] == ["Future note"],
        )
        if status_of(snapshot)["kind"] != "warning":
            raise SmokeFailure(f"future version banner is not a warning: {snapshot}")
        note_window = base._click_until_note_open(xtest, app, fan, snapshot)
        base._wait_dump(
            dump,
            app,
            lambda snap: snap.get("state") == "open"
            and snap.get("typed") is True
            and typed.strip() in (snap.get("text") or ""),
        )
        time.sleep(1.0)  # let the autosave debounce fire at least once
        if path.read_bytes() != original:
            raise SmokeFailure("read-only mode wrote to a future-version file")
        base._close_note_with_escape(xtest, app, note_window)
        base._wait_dump(
            dump, app, lambda snap: snap.get("state") == "fan"
        )
        print("smoke-storage: future version is read-only across typing and close")
    finally:
        base._stop(app)
    wait_for_our_windows(app)
    if path.read_bytes() != original:
        raise SmokeFailure("shutdown wrote to a future-version file")
    print("smoke-storage: shutdown left the future-version file byte-identical")


def scenario_unwritable_then_retry(temporary: Path, xtest_holder: list) -> None:
    data_home = temporary / "unwritable"
    notes_dir = data_home / NOTES_DIR
    notes_dir.mkdir(parents=True)
    path = notes_dir / "notes.json"
    write_json(path, payload(note("a", "Base")))
    original = path.read_bytes()
    typed = "\nTyped while unwritable"
    expected = "Base" + typed
    notes_dir.chmod(0o500)
    app = None
    try:
        dump = data_home / "dump.json"
        app = start_app(data_home, dump, type_text=typed)
        xtest = xtest_holder[0]
        fan = base._show_fan(xtest, app)
        snapshot = fan_snapshot(dump, app, lambda snap: snap["titles"] == ["Base"])
        base._click_until_note_open(xtest, app, fan, snapshot)
        failing = base._wait_dump(
            dump,
            app,
            lambda snap: snap.get("typed") is True
            and snap.get("unsaved") is True
            and status_of(snap)["visible"]
            and "Save failed" in status_of(snap)["message"],
            timeout=10.0,
        )
        if path.read_bytes() != original:
            raise SmokeFailure("a failed save changed notes.json")
        if (notes_dir / "notes.json.tmp").exists():
            raise SmokeFailure("a failed save left a temp file")
        print(
            "smoke-storage: unwritable deck stayed in memory; banner says "
            f"{status_of(failing)['message']!r}"
        )

        notes_dir.chmod(0o700)
        print(
            "smoke-storage: permissions restored "
            f"({oct(notes_dir.stat().st_mode & 0o777)})"
        )
        recovered = base._wait_dump(
            dump,
            app,
            lambda snap: snap.get("unsaved") is False
            and not status_of(snap)["visible"]
            and snap.get("text") == expected,
            timeout=45.0,
        )
        if recovered.get("text") != expected:
            raise SmokeFailure("the retry lost the typed text")
        saved = read_json(path)
        if saved["notes"][0]["text"] != expected:
            raise SmokeFailure("the retry did not reach the disk")
        backup = read_json(notes_dir / "notes.bak.json")
        if backup["notes"][0]["text"] != "Base":
            raise SmokeFailure("the pre-failure deck is not in notes.bak.json")
        if (notes_dir / "notes.json.tmp").exists():
            raise SmokeFailure("the successful retry left a temp file")
        print("smoke-storage: retry after chmod persisted the memory deck")
    finally:
        if app is not None:
            base._stop(app)
        notes_dir.chmod(0o700)
    wait_for_our_windows(app)


def main() -> int:
    xtest_holder: list = []
    xtest = None
    try:
        xtest = base.XTest()
        xtest_holder.append(xtest)
        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-storage-") as temp:
            temporary = Path(temp)
            scenario_recover_from_backup(temporary, xtest_holder[0])
            scenario_double_corruption(temporary, xtest_holder)
            scenario_future_version(temporary, xtest_holder)
            scenario_unwritable_then_retry(temporary, xtest_holder)
        print("smoke-storage: OK")
        return 0
    except SmokeFailure as failure:
        print(f"smoke-storage: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a failure
        print(f"smoke-storage: FAIL: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()


if __name__ == "__main__":
    raise SystemExit(main())
