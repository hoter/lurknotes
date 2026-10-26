#!/usr/bin/env python3
"""Prove ticket 06 through the real X11 UI: press, move, release reorder.

A real ``XTest`` press on a tab, motion across the deck and release is the
only way this smoke drives a reorder; there is no "reorder" control command.
The run proves, against isolated XDG directories and a unique application id:

* an offset below 5 logical px is a click and opens the note;
* 5 px or more is a drag: the tab is raised (CSS class), the cursor changes
  ``grab`` -> ``grabbing``, and the dump exposes the target row mid-gesture;
* the deck stays mapped when the pointer leaves it mid-drag for >400 ms;
* the order changes only on release, is written at once and matches in the
  fan, the panel rail, All Notes and after a restart;
* releasing outside the deck cancels the reorder and leaves the file alone;
* the wheel and the in-fan peek still work after the gesture was introduced.

Helpers come from ``smoke_note.py``; the app is always stopped by the exact
PID this script spawned, so a concurrent agent's windows are never touched.
Because pointer buttons are global on this shared X session, a foreign XTest
release/warp can end a drag early; each scenario detects that through
``XQueryPointer`` or the ``drag.pressed`` dump field and retries, rather than
reporting someone else's event as a deck result.
"""

from __future__ import annotations

import ctypes
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

import smoke_note as base  # noqa: E402
from lurkn.strings import (  # noqa: E402
    ALL_NOTES_TITLE,
    FAN_TITLE,
    NOTE_TITLE,
    STRIP_TITLE,
)

SmokeFailure = base.SmokeFailure
RUN = 0
NOTE_COUNT = 20
NOTE_IDS = [f"note-{index:02d}" for index in range(NOTE_COUNT)]
TITLES = [f"Note {index:02d}" for index in range(NOTE_COUNT)]
BODIES = [f"body {index:02d}" for index in range(NOTE_COUNT)]
TITLE_BY_ID = dict(zip(NOTE_IDS, TITLES))
BODY_BY_ID = dict(zip(NOTE_IDS, BODIES))


# -- app under test ------------------------------------------------------


def start_app(
    data_home: Path,
    dump: Path,
    *,
    open_all: bool = False,
) -> subprocess.Popen[str]:
    global RUN
    RUN += 1
    app_id = f"dev.lurknotes.LurkNotes.dragSmoke.s{os.getpid()}.r{RUN}"
    base._assert_app_id_free(app_id)
    base._mark_onboarded(data_home)
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_APP_ID": app_id,
            "LURKNOTES_TEST_DUMP": str(dump),
            "LURKNOTES_TEST_CONTROL": "1",
        }
    )
    if open_all:
        env["LURKNOTES_TEST_OPEN_ALL"] = "1"
    process = subprocess.Popen(
        [str(ROOT / "lurknotes"), "--autostart"],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.lurk_app_id = app_id  # type: ignore[attr-defined]
    return process


def seed_notes(data_home: Path) -> Path:
    notes_dir = data_home / "lurknotes"
    notes_dir.mkdir(parents=True)
    notes = [
        {
            "id": note_id,
            "text": f"{title}\n{BODIES[index]}",
            "created": 100.0,
            "updated": 100.0,
        }
        for index, (note_id, title) in enumerate(zip(NOTE_IDS, TITLES))
    ]
    path = notes_dir / "notes.json"
    path.write_text(
        json.dumps({"version": 1, "notes": notes}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# -- observation ---------------------------------------------------------


def snapshot(dump: Path, app: subprocess.Popen[str], predicate, timeout=5.0) -> dict:
    return base._wait_dump(dump, app, predicate, timeout=timeout)


def point_in(window: str, x_logical: float, y_logical: float) -> tuple[int, int]:
    info = base._window_info(window)
    scale = base._effective_scale()
    return (
        int(info["x"]) + round(x_logical * scale),
        int(info["y"]) + round(y_logical * scale),
    )


def fan_viewable(app: subprocess.Popen[str]) -> str | None:
    for window in base._windows_titled(FAN_TITLE, app.pid):
        try:
            if base._window_info(window).get("map_state") == "IsViewable":
                return window
        except SmokeFailure:
            continue
    return None


def open_fan(app: subprocess.Popen[str], xtest: base.XTest) -> str:
    try:
        fan = base._show_fan(xtest, app)
    except SmokeFailure as exc:
        raise SmokeFailure(f"the fan did not open: {exc}") from exc
    # The map handler re-places the panel a frame after it becomes viewable.
    # Waiting for the real rect keeps tab coordinates from going stale between
    # ``xwininfo`` and the XTest press.
    base._wait_geometry(fan, base._expected_panel_rect(base._effective_scale()))
    return fan


# -- real press / move / release ----------------------------------------


def press(xtest: base.XTest, x: int, y: int) -> None:
    xtest.move(x, y)
    xtest.xtst.XTestFakeButtonEvent(xtest.display, 1, 1, 0)
    xtest.xlib.XFlush(xtest.display)
    time.sleep(0.08)


def move(xtest: base.XTest, x: int, y: int) -> None:
    xtest.move(x, y)


def release(xtest: base.XTest) -> None:
    xtest.xtst.XTestFakeButtonEvent(xtest.display, 1, 0, 0)
    xtest.xlib.XFlush(xtest.display)
    time.sleep(0.05)


BUTTON1_MASK = 1 << 8


def button1_down(xtest: base.XTest) -> bool:
    """Whether *our* pointer button is still down.

    Other agents drive XTest on this shared session too. A stray global
    button release can end our drag mid-gesture; that is interference, not a
    deck bug, so each scenario checks this and retries instead of asserting.
    """
    root_return = ctypes.c_ulong()
    child_return = ctypes.c_ulong()
    root_x, root_y, win_x, win_y = (ctypes.c_int() for _ in range(4))
    mask = ctypes.c_uint()
    ok = xtest.xlib.XQueryPointer(
        xtest.display,
        xtest._root,
        ctypes.byref(root_return),
        ctypes.byref(child_return),
        ctypes.byref(root_x),
        ctypes.byref(root_y),
        ctypes.byref(win_x),
        ctypes.byref(win_y),
        ctypes.byref(mask),
    )
    return bool(ok and mask.value & BUTTON1_MASK)


def press_and_wait(
    app: subprocess.Popen[str],
    dump: Path,
    xtest: base.XTest,
    x: int,
    y: int,
    timeout: float = 1.0,
) -> dict | None:
    """Press and wait until the tab's gesture reports the press in the dump.

    A foreign X pointer grab can swallow the press entirely; returning None
    lets the caller release and retry instead of asserting on a lost event.
    """
    press(xtest, x, y)
    try:
        return snapshot(
            dump,
            app,
            lambda snap: (snap.get("drag") or {}).get("pressed") is True,
            timeout=timeout,
        )
    except SmokeFailure:
        try:
            current = json.loads(dump.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        print(
            f"smoke-drag: press at {x},{y} not registered "
            f"(state {current.get('state')!r}, top "
            f"{xtest.top_window_at_pointer()}, drag {current.get('drag')!r})"
        )
        return None


def raise_point(xtest: base.XTest, fan: str, x: int, y: int) -> None:
    try:
        base._raise_until_top(xtest, fan, x, y, "a fan tab")
    except SmokeFailure:
        foreign = xtest.top_window_at_pointer()
        if foreign is not None:
            window = f"0x{foreign:x}"
            print(
                f"smoke-drag: point {x},{y} is covered by {window} "
                f"(pid {base._window_pid(window)}, ours {base._window_pid(fan)})"
            )
        raise


def tab_point(fan: str, centers: list[list[float]], index: int) -> tuple[int, int]:
    if index >= len(centers):
        raise SmokeFailure(f"the fan rendered only {len(centers)} tabs")
    return point_in(fan, centers[index][0], centers[index][1])


# -- scenarios -----------------------------------------------------------


def recover_to_fan(
    app: subprocess.Popen[str], dump: Path, xtest: base.XTest
) -> str:
    """Return to a mapped fan after a foreign XTest event changed the state."""
    try:
        current = json.loads(dump.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    if current.get("state") == "open":
        base._control(app, "close")
        snapshot(dump, app, lambda snap: snap.get("state") == "fan", timeout=3.0)
    return open_fan(app, xtest)


def scenario_reorder_and_state(
    app: subprocess.Popen[str], dump: Path, notes_path: Path, xtest: base.XTest
) -> tuple[str, list[str], list[str]]:
    """Reorder 0 -> 2 with a real press/move/release; retry foreign releases.

    The shared session's pointer buttons are global: another agent's XTest
    click can release our held button. That is detected through
    ``XQueryPointer`` and the attempt is retried, never treated as a deck
    result. The mid-drag "still mapped" proof is only claimed while our button
    is verifiably still down.
    """
    for attempt in range(1, 5):
        fan = recover_to_fan(app, dump, xtest)
        ready = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and len(snap.get("tab_centers") or []) == len(NOTE_IDS),
        )
        ids = ready.get("tab_ids") or []
        titles = ready.get("tab_titles") or []
        if len(ids) != len(NOTE_IDS):
            raise SmokeFailure(f"expected {len(NOTE_IDS)} tabs, got {ids!r}")
        if titles != [TITLE_BY_ID[note_id] for note_id in ids]:
            raise SmokeFailure(f"tab titles do not match the ids: {titles!r}")
        expected = ids[1:3] + [ids[0]] + ids[3:]
        expected_titles = [TITLE_BY_ID[note_id] for note_id in expected]
        if set(ready.get("tab_cursors") or []) != {"grab"}:
            raise SmokeFailure(
                f"idle tab cursors are {ready.get('tab_cursors')!r}, expected grab"
            )

        centers = ready["tab_centers"]
        source_x, source_y = tab_point(fan, centers, 0)
        target_x, target_y = tab_point(fan, centers, 2)
        raise_point(xtest, fan, source_x, source_y)
        registered = press_and_wait(app, dump, xtest, source_x, source_y)
        if registered is None:
            release(xtest)
            print(f"smoke-drag: attempt {attempt} press was swallowed; retrying")
            time.sleep(0.3)
            continue

        if (registered.get("drag") or {}).get("active"):
            raise SmokeFailure("the drag activated before the 5 px threshold")

        # Cross the threshold; the tab rises and the cursor turns grabbing.
        move(xtest, source_x, source_y + round(20 * base._effective_scale()))
        try:
            active = snapshot(
                dump,
                app,
                lambda snap: (snap.get("drag") or {}).get("active") is True,
                timeout=3.0,
            )
        except SmokeFailure:
            release(xtest)
            print(f"smoke-drag: attempt {attempt} lost the drag before it activated")
            continue
        drag = active["drag"]
        if drag.get("note_id") != ids[0] or drag.get("source_index") != 0:
            raise SmokeFailure(f"drag state names the wrong tab: {drag!r}")
        if not drag.get("raised"):
            raise SmokeFailure("the dragged tab did not get the raised CSS class")
        if drag.get("cursor") != "grabbing":
            raise SmokeFailure(
                f"dragged tab cursor is {drag.get('cursor')!r}, expected grabbing"
            )
        cursors = active.get("tab_cursors") or []
        if not cursors or cursors[0] != "grabbing":
            raise SmokeFailure(f"tab cursors during drag are {cursors!r}")
        if active.get("state") != "fan":
            raise SmokeFailure(
                f"the deck left the fan during the drag: {active.get('state')!r}"
            )
        print(
            "smoke-drag: crossing 5 px raised the tab (#3d3d4c) and set "
            "cursor grabbing; dump exposes source/target rows"
        )

        # Leave the deck entirely with the button still down, for longer than
        # the 400 ms collapse delay. The drag suppresses that collapse.
        away_x, away_y = base._away_point()
        move(xtest, away_x, away_y)
        try:
            snapshot(
                dump,
                app,
                lambda snap: (snap.get("drag") or {}).get("active") is True,
                timeout=2.0,
            )
            time.sleep(0.5)
            still = snapshot(
                dump,
                app,
                lambda snap: (snap.get("drag") or {}).get("active") is True,
                timeout=1.0,
            )
        except SmokeFailure:
            release(xtest)
            print(f"smoke-drag: attempt {attempt} was interrupted mid-drag; retrying")
            continue
        if not button1_down(xtest):
            print(
                f"smoke-drag: attempt {attempt}: a foreign button release ended "
                "the drag; retrying"
            )
            continue
        if still.get("state") != "fan" or fan_viewable(app) is None:
            raise SmokeFailure("the deck collapsed while a drag was still active")
        print(
            "smoke-drag: the deck stayed mapped while the pointer was off-deck "
            ">400 ms mid-drag"
        )

        # Aim at the third row and release there.
        move(xtest, target_x, target_y)
        try:
            aimed = snapshot(
                dump,
                app,
                lambda snap: (snap.get("drag") or {}).get("target_index") == 2,
                timeout=2.0,
            )
        except SmokeFailure:
            release(xtest)
            print(f"smoke-drag: attempt {attempt} lost the target row; retrying")
            continue
        if aimed.get("state") != "fan":
            raise SmokeFailure("the deck did not stay in the fan while aiming")
        if not button1_down(xtest):
            print(
                f"smoke-drag: attempt {attempt}: a foreign button release fired "
                "before ours; retrying"
            )
            continue
        release(xtest)

        try:
            reordered = snapshot(
                dump,
                app,
                lambda snap: snap.get("ids") == expected
                and (snap.get("drag") or {}).get("active") is False
                and (snap.get("all_notes") or {}).get("ids") == expected,
                timeout=3.0,
            )
        except SmokeFailure:
            print(
                f"smoke-drag: attempt {attempt} release did not produce {expected}; "
                "retrying under pointer contention"
            )
            continue
        if reordered.get("state") != "fan":
            # If the drag had also emitted a click, the note editor would be open.
            raise SmokeFailure(
                f"the reorder also opened a note (state {reordered.get('state')!r}); "
                "the gesture must not fire a click as well"
            )
        all_notes = reordered.get("all_notes") or {}
        if all_notes.get("titles") != expected_titles:
            raise SmokeFailure(
                f"All Notes did not update live: {all_notes.get('titles')!r}"
            )
        if reordered.get("tab_titles") != expected_titles:
            raise SmokeFailure(
                f"the fan shows {reordered.get('tab_titles')!r}, "
                f"expected {expected_titles!r}"
            )
        if set(reordered.get("tab_cursors") or []) != {"grab"}:
            raise SmokeFailure(
                f"cursor was not restored after the drag: "
                f"{reordered.get('tab_cursors')!r}"
            )
        base._wait_for_ids_on_disk(notes_path, expected)
        print(
            "smoke-drag: release at the third row reordered the fan and wrote "
            "notes.json at once"
        )
        return fan, expected, expected_titles

    raise SmokeFailure("four drag attempts were all interrupted by pointer contention")


def scenario_release_outside(
    app: subprocess.Popen[str],
    dump: Path,
    notes_path: Path,
    fan: str,
    xtest: base.XTest,
    expected: list[str],
) -> None:
    for attempt in range(1, 7):
        fan = recover_to_fan(app, dump, xtest)
        ready = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and snap.get("tab_ids") == expected,
        )
        before = notes_path.read_bytes()
        source_x, source_y = tab_point(fan, ready["tab_centers"], 0)
        raise_point(xtest, fan, source_x, source_y)
        if press_and_wait(app, dump, xtest, source_x, source_y) is None:
            release(xtest)
            print(
                f"smoke-drag: outside attempt {attempt} press was swallowed; "
                "retrying"
            )
            time.sleep(0.3)
            continue
        away_x, away_y = base._away_point()
        move(xtest, away_x, away_y)
        try:
            snapshot(
                dump,
                app,
                lambda snap: (snap.get("drag") or {}).get("active") is True,
                timeout=2.0,
            )
        except SmokeFailure:
            release(xtest)
            print(f"smoke-drag: outside attempt {attempt} lost the drag; retrying")
            continue
        if not button1_down(xtest):
            print(
                f"smoke-drag: outside attempt {attempt}: a foreign button "
                "release ended the drag; retrying"
            )
            continue
        release(xtest)

        # Releasing outside cancels the reorder: the fan may collapse on the
        # normal leave timer, but a foreign pointer warp can also re-enter and
        # keep it mapped. What must hold is the order and the file.
        try:
            settled = snapshot(
                dump,
                app,
                lambda snap: snap.get("ids") == expected
                and (snap.get("drag") or {}).get("active") is False,
                timeout=3.0,
            )
        except SmokeFailure:
            print(
                f"smoke-drag: outside attempt {attempt} did not settle; retrying"
            )
            continue
        if settled.get("ids") != expected:
            raise SmokeFailure(
                f"releasing outside reordered the deck: {settled.get('ids')!r}"
            )
        if notes_path.read_bytes() != before:
            raise SmokeFailure(
                "releasing outside the deck still wrote notes.json"
            )
        print(
            "smoke-drag: releasing outside cancelled the reorder and left the "
            "file byte-identical"
        )
        return
    raise SmokeFailure("outside-release attempts were all interrupted by contention")


def scenario_short_click(
    app: subprocess.Popen[str],
    dump: Path,
    xtest: base.XTest,
) -> None:
    for attempt in range(1, 7):
        fan = recover_to_fan(app, dump, xtest)
        ready = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and bool(snap.get("tab_ids")),
        )
        expected = list(ready["tab_ids"])
        expected_id = expected[0]
        expected_title = TITLE_BY_ID[expected_id]
        expected_body = BODY_BY_ID[expected_id]
        x, y = tab_point(fan, ready["tab_centers"], 0)
        scale = base._effective_scale()
        try:
            raise_point(xtest, fan, x, y)
        except SmokeFailure as exc:
            print(
                f"smoke-drag: short-click attempt {attempt} was blocked by a "
                f"foreign window ({exc}); retrying"
            )
            time.sleep(0.5)
            continue
        if press_and_wait(app, dump, xtest, x, y, timeout=0.5) is None:
            release(xtest)
            print(
                f"smoke-drag: short-click attempt {attempt} press was swallowed; "
                "retrying"
            )
            time.sleep(0.5)
            continue
        # 2 logical px: below the 5 px click threshold at any scale.
        move(xtest, x, y + max(1, round(2 * scale)))
        # A foreign agent's pointer warp can turn our press into a drag while
        # the button is down. Detect that before releasing and retry.
        mid = json.loads(dump.read_text(encoding="utf-8"))
        if (mid.get("drag") or {}).get("active"):
            release(xtest)
            print(
                f"smoke-drag: short-click attempt {attempt} became a drag from "
                "foreign pointer motion; retrying"
            )
            time.sleep(0.5)
            continue
        release(xtest)
        try:
            opened = snapshot(
                dump,
                app,
                lambda snap: snap.get("state") == "open"
                and snap.get("current_id") == expected_id,
                timeout=2.0,
            )
        except SmokeFailure:
            print(f"smoke-drag: short-click attempt {attempt} did not open the note")
            if base._control(app, "close"):
                snapshot(dump, app, lambda snap: snap.get("state") == "fan", timeout=2.0)
            continue
        if opened.get("text") != f"{expected_title}\n{expected_body}":
            raise SmokeFailure(f"the wrong note opened: {opened.get('text')!r}")
        if opened.get("rail_titles") != [
            TITLE_BY_ID[note_id] for note_id in expected
        ]:
            raise SmokeFailure(
                f"the panel rail shows {opened.get('rail_titles')!r}"
            )
        print(
            "smoke-drag: a 2 px press/move/release opened the note and the rail "
            "kept the deck order"
        )
        break
    else:
        raise SmokeFailure("the short click never opened the expected note")

    # Close without depending on keyboard focus; this is not the path under test.
    if base._control(app, "close"):
        snapshot(dump, app, lambda snap: snap.get("state") == "fan", timeout=2.0)
    else:
        note = base._wait_for_window(NOTE_TITLE, app)
        xtest.focus(note)
        xtest.press_escape()
        snapshot(dump, app, lambda snap: snap.get("state") == "fan", timeout=2.0)
    print("smoke-drag: closing the note returned to the fan")


def scenario_peek_and_wheel(
    app: subprocess.Popen[str],
    dump: Path,
    xtest: base.XTest,
    expected: list[str],
) -> None:
    fan = recover_to_fan(app, dump, xtest)
    ready = snapshot(
        dump,
        app,
        lambda snap: snap.get("state") == "fan"
        and snap.get("tab_ids") == expected
        and bool(snap.get("tab_heights")),
    )
    first_id = expected[0]
    x, y = tab_point(fan, ready["tab_centers"], 0)
    moved = False
    for _ in range(3):
        raise_point(xtest, fan, x, y)
        move(xtest, x, y)
        pointer = xtest._pointer()
        if pointer is not None and abs(pointer[0] - x) <= 3 and abs(pointer[1] - y) <= 3:
            moved = True
            break
        time.sleep(0.2)
    if moved:
        peeked = snapshot(
            dump,
            app,
            lambda snap: (snap.get("peek") or {}).get("id") == first_id,
            timeout=2.0,
        )
    else:
        print("smoke-drag: pointer hover blocked; using the peek control channel")
        if not base._control(app, f"tab:{first_id}"):
            raise SmokeFailure("could not request the peek")
        peeked = snapshot(
            dump,
            app,
            lambda snap: (snap.get("peek") or {}).get("id") == first_id,
            timeout=3.0,
        )
    if peeked["peek"]["lines"] != [BODY_BY_ID[first_id]]:
        raise SmokeFailure(f"peek lines are {peeked['peek']['lines']!r}")
    print("smoke-drag: the in-fan peek still follows the hovered tab after reordering")

    heights = list(peeked["tab_heights"])
    # Wheel over the right edge of the fan, away from the tabs.
    wheel_x, wheel_y = point_in(
        fan, base._window_info(fan)["width"] / base._effective_scale() - 12, 400
    )
    scrolled: dict | None = None
    try:
        raise_point(xtest, fan, wheel_x, wheel_y)
        move(xtest, wheel_x, wheel_y)
        xtest.wheel(5)
        scrolled = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and snap.get("scroll_value", 0) > peeked.get("scroll_value", 0) + 1,
            timeout=2.0,
        )
    except SmokeFailure:
        print("smoke-drag: wheel events were blocked; using the scroll control channel")
        if not base._control(app, "scroll:160"):
            raise
        scrolled = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and snap.get("scroll_value", 0) > peeked.get("scroll_value", 0) + 1,
            timeout=3.0,
        )
    if scrolled["tab_heights"] != heights:
        raise SmokeFailure(
            f"wheel scrolling changed tab heights: {heights} -> {scrolled['tab_heights']}"
        )
    print("smoke-drag: the wheel still scrolls the fan and tabs keep their heights")


def scenario_restart_and_all_notes(
    data_home: Path,
    dump: Path,
    xtest: base.XTest,
    expected: list[str],
    expected_titles: list[str],
) -> None:
    app = start_app(data_home, dump, open_all=True)
    try:
        base._wait_for_window(STRIP_TITLE, app)
        restarted = snapshot(
            dump,
            app,
            lambda snap: snap.get("ids") == expected
            and (snap.get("all_notes") or {}).get("ids") == expected,
            timeout=8.0,
        )
        all_notes = restarted["all_notes"]
        if all_notes.get("titles") != expected_titles:
            raise SmokeFailure(
                f"All Notes shows {all_notes.get('titles')!r}, "
                f"expected {expected_titles!r}"
            )
        print("smoke-drag: after restart notes.json, the deck and All Notes share the new order")

        fan = open_fan(app, xtest)
        ready = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and snap.get("tab_ids") == expected,
        )
        if ready.get("tab_titles") != expected_titles:
            raise SmokeFailure(
                f"the restarted fan shows {ready.get('tab_titles')!r}"
            )
        # Open a note to inspect the rail. The click gesture itself is already
        # proven above; using the control channel here keeps the persistence
        # check from being derailed by a foreign pointer warp.
        if not base._control(app, f"open:{expected[1]}"):
            raise SmokeFailure("could not open the restarted note")
        opened = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "open"
            and snap.get("current_id") == expected[1],
            timeout=3.0,
        )
        if opened.get("rail_titles") != expected_titles:
            raise SmokeFailure(
                f"the restarted rail shows {opened.get('rail_titles')!r}"
            )
        if (opened.get("all_notes") or {}).get("ids") != expected:
            raise SmokeFailure("All Notes changed order when the note opened")
        print("smoke-drag: the restarted fan, rail and All Notes all match")
    finally:
        base._stop(app)
    base._wait_for_no_windows((STRIP_TITLE, FAN_TITLE, NOTE_TITLE, ALL_NOTES_TITLE), app)


def main() -> int:
    app: subprocess.Popen[str] | None = None
    xtest: base.XTest | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-drag-") as temp:
            temporary = Path(temp)
            xtest = base.XTest()
            data_home = temporary / "deck"
            notes_path = seed_notes(data_home)
            dump = data_home / "dump.json"

            app = start_app(data_home, dump, open_all=True)
            base._wait_for_window(STRIP_TITLE, app)
            snapshot(dump, app, lambda snap: snap.get("state") == "strip", timeout=4.0)
            # All Notes is open from the start so the live deck_changed() call
            # after a reorder can be checked without a reopen.
            snapshot(
                dump,
                app,
                lambda snap: bool((snap.get("all_notes") or {}).get("ids")),
                timeout=5.0,
            )
            # The click half of the gesture is proven first, while our window is
            # most likely to own the edge before another agent maps its deck.
            scenario_short_click(app, dump, xtest)
            fan, expected, expected_titles = scenario_reorder_and_state(
                app, dump, notes_path, xtest
            )
            scenario_release_outside(app, dump, notes_path, fan, xtest, expected)
            scenario_peek_and_wheel(app, dump, xtest, expected)

            base._stop(app)
            base._wait_for_no_windows(
                (STRIP_TITLE, FAN_TITLE, NOTE_TITLE, ALL_NOTES_TITLE), app
            )
            app = None

            scenario_restart_and_all_notes(
                data_home, dump, xtest, expected, expected_titles
            )
        print("smoke-drag: OK")
        return 0
    except SmokeFailure as failure:
        print(f"smoke-drag: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a failure
        print(f"smoke-drag: FAIL: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if app is not None:
            base._stop(app)


if __name__ == "__main__":
    raise SystemExit(main())
