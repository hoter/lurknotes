#!/usr/bin/env python3
"""Prove ticket 05 through the real X11 UI: delete, toast, undo, expiry.

Flow: open a note, Ctrl+Backspace -> notes.json shrinks before the toast is
read, the toast is visible with the spec text and the dark palette, typing into
the next note (autosave rebuild) does not lose it, Ctrl+Z restores the note at
its original index, the Undo button does the same, expiry (shortened by
``LURKNOTES_TEST_UNDO_MS``) drops the payload, a second delete discards the
first, the last-note delete shows the empty fan, and a restart has no undo.
A read-only (future version) deck is deleted in memory with no write.

Uses the helpers from smoke_note.py; isolated XDG dirs and a unique app id keep
it safe next to other agents' LurkNotes instances. Always stops its own app.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import harness as h  # noqa: E402

from lurkn.strings import FAN_TITLE, NOTE_TITLE, STRIP_TITLE, UNDO_TOAST  # noqa: E402
from smoke_note import (  # noqa: E402
    SmokeFailure,
    XTest,
    _assert_app_id_free,
    _click_center,
    _click_editor,
    _effective_scale,
    _mark_onboarded,
    _pixel_sampler,
    _raise_for_capture,
    _wait_dump,
    _wait_for_ids_on_disk,
    _wait_for_no_windows,
    _wait_for_window,
    _show_fan,
    _xwd_image,
)

UNDO_TIMEOUT_MS = 6_000  # test hook only; production is 10_000
TOAST_BACKGROUND = (58, 58, 70)  # #3a3a46, spec §6.5


class DeleteXTest(XTest):
    """XTest chord helper on top of the existing pointer/keyboard wrapper."""

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


def _app_id() -> str:
    return h.app_id("deleteSmoke")


def _start_app(
    data_home: Path, dump: Path, *, undo_ms: int = UNDO_TIMEOUT_MS
) -> subprocess.Popen[str]:
    _mark_onboarded(data_home)
    env = h.make_env(
        data_home,
        _app_id(),
        dump=dump,
        extra={
            "LURKNOTES_TEST_UNDO_MS": str(undo_ms),
            "LURKNOTES_TEST_CONTROL": "1",
            "LURKNOTES_TEST_PIN_DECK": "1",
        },
    )
    return h.launch([], env)


_ensure_running = h.ensure_running
_stop = h.stop


def _write_deck(path: Path, notes: list[dict], version: int = 1) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": version, "notes": notes}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path.read_bytes()


def _note(note_id: str, text: str, stamp: float) -> dict:
    return {"id": note_id, "text": text, "created": stamp, "updated": stamp}


def _disk_ids(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [note["id"] for note in payload["notes"]]


def _wait_note_text(path: Path, note_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 3.0
    last: dict | None = None
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            last = payload
            notes = payload.get("notes") or []
            if notes and notes[0].get("id") == note_id and notes[0].get("text") == expected:
                return payload
            for note in notes:
                if note.get("id") == note_id and note.get("text") == expected:
                    return payload
        time.sleep(0.05)
    raise SmokeFailure(f"note {note_id[:8]} text never became {expected!r}; last: {last}")


def _toast_predicate(visible: bool) -> Callable[[dict], bool]:
    def predicate(snapshot: dict) -> bool:
        toast = snapshot.get("toast") or {}
        return (
            toast.get("visible") is visible
            and snapshot.get("undo_pending") is visible
        )

    return predicate


def _wait_toast(
    dump: Path, process: subprocess.Popen[str], *, visible: bool = True, **state
) -> dict:
    def predicate(snapshot: dict) -> bool:
        if not _toast_predicate(visible)(snapshot):
            return False
        return all(snapshot.get(key) == value for key, value in state.items())

    return _wait_dump(dump, process, predicate)


def _open_tab(
    xtest: DeleteXTest,
    process: subprocess.Popen[str],
    panel: str,
    dump: Path,
    index: int,
    note_id: str,
) -> dict:
    fan = _wait_dump(
        dump,
        process,
        lambda snapshot: snapshot.get("state") == "fan"
        and len(snapshot.get("tab_centers") or []) > index,
    )
    for attempt in range(1, 6):
        try:
            _click_center(
                xtest, panel, fan["tab_centers"][index], f"tab {index}"
            )
        except SmokeFailure as exc:
            print(f"smoke-delete: tab click {attempt} was blocked ({exc})")
            time.sleep(0.4)
            continue
        try:
            return _wait_dump(
                dump,
                process,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("current_id") == note_id
                and snapshot.get("active_index") == index,
                timeout=2.0,
            )
        except SmokeFailure:
            print(f"smoke-delete: tab click {attempt} did not open the note")
    raise SmokeFailure(f"tab {index} never opened note {note_id[:8]}")


def _check_toast_palette(
    xtest: DeleteXTest, panel: str, bounds: list[float]
) -> None:
    _raise_for_capture(
        xtest,
        panel,
        "the undo toast",
        points=(
            (int(bounds[0] + 4), int(bounds[1] + bounds[3] / 2)),
            (1, 1),
            (378, 926),
        ),
    )
    pixel, _width, _height = _pixel_sampler(_xwd_image(panel))
    scale = _effective_scale()
    x = round((bounds[0] + 5) * scale)
    y = round((bounds[1] + bounds[3] / 2) * scale)
    observed = pixel(x, y)
    if observed != TOAST_BACKGROUND:
        raise SmokeFailure(
            "undo toast background is "
            f"#{observed[0]:02x}{observed[1]:02x}{observed[2]:02x}, "
            "expected #3a3a46"
        )


def _delete_and_expect(
    xtest: DeleteXTest,
    process: subprocess.Popen[str],
    panel: str,
    dump: Path,
    expected_ids: list[str],
    dump_state: str,
) -> dict:
    if dump_state == "open":
        try:
            _click_editor(xtest, panel)
        except SmokeFailure as exc:
            print(f"smoke-delete: editor click was blocked ({exc}); focusing")
    xtest.focus(panel)
    time.sleep(0.1)
    xtest.ctrl_backspace()
    return _wait_toast(dump, process, state=dump_state, ids=expected_ids)


def main() -> int:
    app: subprocess.Popen[str] | None = None
    xtest: DeleteXTest | None = None
    try:
        _assert_app_id_free(_app_id())

        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-delete-") as temporary:
            data_home = Path(temporary)
            notes_dir = data_home / "lurknotes"
            notes_path = notes_dir / "notes.json"
            first_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            second_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            third_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            first_text = "Alpha\nalpha body"
            second_text = "Beta\nbeta body"
            third_text = "Gamma\ngamma body"
            _write_deck(
                notes_path,
                [
                    _note(first_id, first_text, 100.0),
                    _note(second_id, second_text, 101.0),
                    _note(third_id, third_text, 102.0),
                ],
            )

            dump = data_home / "dump.json"
            app = _start_app(data_home, dump)
            _wait_for_window(STRIP_TITLE, app)
            xtest = DeleteXTest()
            panel = _show_fan(xtest, app)
            _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and len(snapshot.get("tab_centers") or []) == 3,
            )

            # -- delete writes at once and shows the toast ---------------
            opened = _open_tab(xtest, app, panel, dump, 1, second_id)
            if opened.get("toast", {}).get("visible"):
                raise SmokeFailure("a toast is visible before any delete")

            deleted = _delete_and_expect(
                xtest, app, panel, dump, [first_id, third_id], "open"
            )
            if deleted.get("current_id") != third_id:
                raise SmokeFailure(
                    f"after deleting the middle note the panel shows "
                    f"{deleted.get('current_id')}, expected the next note"
                )
            toast = deleted["toast"]
            if toast.get("label") != UNDO_TOAST:
                raise SmokeFailure(
                    f"toast says {toast.get('label')!r}, expected {UNDO_TOAST!r}"
                )
            if not toast.get("button_center") or not toast.get("bounds"):
                raise SmokeFailure("toast has no Undo button or bounds")
            _wait_for_ids_on_disk(notes_path, [first_id, third_id], timeout=2.0)
            _check_toast_palette(xtest, panel, toast["bounds"])
            print("smoke-delete: delete wrote notes.json and showed the dark toast")

            # -- the toast survives a fan/rail rebuild from autosave -----
            xtest.focus(panel)
            xtest.type_text("x")
            survived = _wait_dump(
                dump,
                app,
                # Another test's click can move the caret; the point here is
                # that the keystroke reached the editor after the rebuild.
                lambda snapshot: snapshot.get("state") == "open"
                and (snapshot.get("text") or "").count("x")
                == third_text.count("x") + 1
                and len(snapshot.get("text") or "") == len(third_text) + 1
                and snapshot.get("undo_pending") is True
                and snapshot.get("toast", {}).get("visible") is True,
            )
            deadline = time.monotonic() + 3.0
            saved_text: str | None = None
            while time.monotonic() < deadline:
                saved_payload = json.loads(notes_path.read_text(encoding="utf-8"))
                saved_text = next(
                    (
                        note["text"]
                        for note in saved_payload.get("notes", [])
                        if note["id"] == third_id
                    ),
                    None,
                )
                if saved_text is not None and len(saved_text) == len(third_text) + 1:
                    break
                time.sleep(0.05)
            if saved_text is None or len(saved_text) != len(third_text) + 1:
                raise SmokeFailure(f"the keystroke did not reach the disk: {saved_text!r}")
            if not survived["toast"]["visible"]:
                raise SmokeFailure("the autosave rebuild lost the undo toast")
            print("smoke-delete: the toast survived an autosave refresh")

            # -- Ctrl+Z restores at the original index -------------------
            xtest.focus(panel)
            xtest.ctrl_z()
            restored = _wait_toast(
                dump,
                app,
                visible=False,
                state="open",
                current_id=second_id,
                ids=[first_id, second_id, third_id],
            )
            if restored.get("active_index") != 1:
                raise SmokeFailure(
                    f"restored note is rail row {restored.get('active_index')}, "
                    "expected its original index 1"
                )
            _wait_for_ids_on_disk(notes_path, [first_id, second_id, third_id])
            print("smoke-delete: Ctrl+Z restored the note at index 1 and reopened it")

            # -- the Undo button does the same ---------------------------
            deleted = _delete_and_expect(
                xtest, app, panel, dump, [first_id, third_id], "open"
            )
            _click_center(
                xtest, panel, deleted["toast"]["button_center"], "Undo button"
            )
            _wait_toast(
                dump,
                app,
                visible=False,
                state="open",
                current_id=second_id,
                ids=[first_id, second_id, third_id],
            )
            _wait_for_ids_on_disk(notes_path, [first_id, second_id, third_id])
            print("smoke-delete: the Undo button restored the note")

            # -- the rail Delete button deletes the open note ------------
            opened = _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("state") == "open"
                and snapshot.get("note_delete_center") is not None,
            )
            _click_center(
                xtest, panel, opened["note_delete_center"], "the rail delete button"
            )
            deleted = _wait_toast(
                dump, app, state="open", ids=[first_id, third_id]
            )
            if deleted.get("current_id") != third_id:
                raise SmokeFailure(
                    f"the rail delete button left {deleted.get('current_id')} "
                    "open, expected the next note"
                )
            _wait_for_ids_on_disk(notes_path, [first_id, third_id], timeout=2.0)
            _click_center(
                xtest, panel, deleted["toast"]["button_center"], "Undo button"
            )
            _wait_toast(
                dump,
                app,
                visible=False,
                state="open",
                current_id=second_id,
                ids=[first_id, second_id, third_id],
            )
            _wait_for_ids_on_disk(notes_path, [first_id, second_id, third_id])
            print(
                "smoke-delete: the rail delete button deleted the note, showed "
                "the toast, and Undo restored it"
            )

            # -- expiry finalises the delete -----------------------------
            deleted = _delete_and_expect(
                xtest, app, panel, dump, [first_id, third_id], "open"
            )
            dead = _wait_toast(dump, app, visible=False, ids=[first_id, third_id])
            _wait_for_ids_on_disk(notes_path, [first_id, third_id])
            if dead.get("undo_pending"):
                raise SmokeFailure("the undo payload survived its timeout")
            xtest.focus(panel)
            xtest.ctrl_z()
            time.sleep(0.5)
            after_late_undo = _wait_dump(
                dump, app, lambda snapshot: snapshot.get("ids") == [first_id, third_id]
            )
            if after_late_undo.get("toast", {}).get("visible"):
                raise SmokeFailure("Ctrl+Z resurrected a toast after expiry")
            _wait_for_ids_on_disk(notes_path, [first_id, third_id])
            print(
                f"smoke-delete: after {UNDO_TIMEOUT_MS} ms expiry dropped the undo "
                "and Ctrl+Z did nothing"
            )

            # -- a second delete finalises the first, timer restarts -----
            # The open note is third. Delete it, wait past half the window,
            # delete first, then outlive the first timer: only the second
            # delete must remain undoable.
            deleted = _delete_and_expect(
                xtest, app, panel, dump, [first_id], "open"
            )
            if deleted.get("undo_pending") is not True:
                raise SmokeFailure("first delete has no pending undo")
            time.sleep(UNDO_TIMEOUT_MS / 2 / 1000)  # half the window
            second_delete = _delete_and_expect(
                xtest, app, panel, dump, [], "fan"
            )
            if second_delete.get("current_id") is not None:
                raise SmokeFailure("deleting the last note kept a current id")
            time.sleep(2.5)  # would be past the first timer if it survived
            still = _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("undo_pending") is True
                and snapshot.get("toast", {}).get("visible") is True,
            )
            if still.get("undo_pending") is not True:
                raise SmokeFailure("the first timer expired the second delete")
            xtest.ctrl_z()
            _wait_toast(
                dump,
                app,
                visible=False,
                state="open",
                current_id=first_id,
                ids=[first_id],
            )
            _wait_for_ids_on_disk(notes_path, [first_id])
            print(
                "smoke-delete: the second delete finalised the first and "
                "restarted the toast timer"
            )

            # -- last note: empty state, second delete is harmless --------
            _click_editor(xtest, panel)
            time.sleep(0.1)
            xtest.ctrl_backspace()
            empty = _wait_toast(dump, app, state="fan", ids=[])
            if empty.get("current_id") is not None:
                raise SmokeFailure("empty deck kept a current id")
            _wait_for_ids_on_disk(notes_path, [])
            xtest.ctrl_backspace()  # no note left: must not crash
            time.sleep(0.3)
            still_empty = _wait_dump(
                dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids") == [],
            )
            if still_empty.get("undo_pending") is not True:
                raise SmokeFailure("the harmless second delete dropped the undo")
            xtest.ctrl_z()
            _wait_toast(
                dump,
                app,
                visible=False,
                state="open",
                ids=[first_id],
                current_id=first_id,
            )
            _wait_for_ids_on_disk(notes_path, [first_id])
            print(
                "smoke-delete: deleting the last note showed the empty fan; "
                "deleting again did not crash"
            )

            # -- restart has no undo -------------------------------------
            _click_editor(xtest, panel)
            time.sleep(0.1)
            xtest.ctrl_backspace()
            _wait_toast(dump, app, state="fan", ids=[])
            _wait_for_ids_on_disk(notes_path, [])
            _stop(app)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)

            restart_dump = data_home / "restart-dump.json"
            app = _start_app(data_home, restart_dump)
            _wait_for_window(STRIP_TITLE, app)
            panel = _show_fan(xtest, app)
            after_restart = _wait_dump(
                restart_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("ids") == []
                and snapshot.get("undo_pending") is False
                and snapshot.get("toast", {}).get("visible") is False,
            )
            if after_restart.get("toast", {}).get("visible"):
                raise SmokeFailure("a toast reappeared after restart")
            xtest.focus(panel)
            xtest.ctrl_z()
            time.sleep(0.5)
            after_restart_ctrlz = _wait_dump(
                restart_dump, app, lambda snapshot: snapshot.get("ids") == []
            )
            if after_restart_ctrlz.get("toast", {}).get("visible"):
                raise SmokeFailure("Ctrl+Z after restart found a deleted note")
            _wait_for_ids_on_disk(notes_path, [])
            print("smoke-delete: a restart forgot the pending undo")
            _stop(app)
            _wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE), app)

            # -- read-only: memory-only delete and undo -------------------
            readonly_home = data_home / "readonly"
            readonly_notes = readonly_home / "lurknotes" / "notes.json"
            read_first = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
            read_second = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
            original_bytes = _write_deck(
                readonly_notes,
                [
                    _note(read_first, "Read one", 200.0),
                    _note(read_second, "Read two", 201.0),
                ],
                version=2,
            )
            readonly_dump = readonly_home / "dump.json"
            app = _start_app(readonly_home, readonly_dump)
            _wait_for_window(STRIP_TITLE, app)
            panel = _show_fan(xtest, app)
            _wait_dump(
                readonly_dump,
                app,
                lambda snapshot: snapshot.get("state") == "fan"
                and snapshot.get("read_only") is True
                and snapshot.get("ids") == [read_first, read_second],
            )
            _open_tab(xtest, app, panel, readonly_dump, 0, read_first)
            _click_editor(xtest, panel)
            time.sleep(0.1)
            xtest.ctrl_backspace()
            deleted_readonly = _wait_toast(
                readonly_dump,
                app,
                state="open",
                ids=[read_second],
                current_id=read_second,
                read_only=True,
            )
            if readonly_notes.read_bytes() != original_bytes:
                raise SmokeFailure("a read-only deck was written on delete")
            if not deleted_readonly["toast"]["visible"]:
                raise SmokeFailure("read-only delete showed no toast")
            xtest.ctrl_z()
            _wait_toast(
                readonly_dump,
                app,
                visible=False,
                state="open",
                ids=[read_first, read_second],
                current_id=read_first,
                read_only=True,
            )
            if readonly_notes.read_bytes() != original_bytes:
                raise SmokeFailure("a read-only deck was written on undo")
            print(
                "smoke-delete: read-only delete/undo stayed in memory and the "
                "file was untouched"
            )

            print("smoke-delete: OK")
            return 0

    except SmokeFailure as failure:
        print(f"smoke-delete: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a smoke failure
        print(f"smoke-delete: FAIL: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if app is not None:
            _stop(app)


if __name__ == "__main__":
    raise SystemExit(main())
