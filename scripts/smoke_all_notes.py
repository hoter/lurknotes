#!/usr/bin/env python3
"""Prove ticket 07 through the real X11 UI.

Run 1: ``LURKNOTES_TEST_OPEN_ALL`` opens All Notes; the window is a normal
720x560 resizable window centred on the workarea; the list is in manual deck
order; search narrows to the notes containing the substring and shows the
matching line with the match bolded; clearing restores every note; clicking a
row opens that note in the edge panel while All Notes stays mapped; text typed
in the panel appears in a fresh search without reopening All Notes; the menu's
"Quit LurkNotes" exits through the normal shutdown path and saves the text.

Run 2: closing All Notes with a WM_DELETE_WINDOW hides it and keeps the app
alive (the strip is still mapped), because closing the list is not quitting.

Everything runs against an isolated XDG tree and a unique application id, and
only windows owned by this process are touched. Exits 0 on success, 1 with a
clear message otherwise, and always stops the process it starts.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
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
    QUIT,
    STRIP_TITLE,
)

SmokeFailure = base.SmokeFailure

WIDTH = 720
HEIGHT = 560
BACKGROUND = (28, 28, 34)  # #1c1c22, spec §6.5
ALL_DESKTOPS = 4294967295
CENTER_TOLERANCE = 4  # physical px


def start_app(data_home: Path, dump: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_APP_ID": (
                f"dev.lurknotes.LurkNotes.allnotes-smoke.s{os.getpid()}"
            ),
            "LURKNOTES_TEST_DUMP": str(dump),
            "LURKNOTES_TEST_OPEN_ALL": "1",
            "LURKNOTES_TEST_PIN_DECK": "1",
        }
    )
    return subprocess.Popen(
        [str(ROOT / "lurknotes")],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def frame_extents(window: str) -> tuple[int, int, int, int]:
    """GTK's CSD shadow extents; they sit outside the visible window."""
    output = base._run("xprop", "-id", window, "_GTK_FRAME_EXTENTS")
    match = re.search(r"= (\d+), (\d+), (\d+), (\d+)", output)
    if match is None:
        raise SmokeFailure(f"All Notes has no _GTK_FRAME_EXTENTS: {output.strip()}")
    return tuple(int(value) for value in match.groups())


def visible_rect(window: str) -> tuple[int, int, int, int]:
    info = base._window_info(window)
    left, right, top, bottom = frame_extents(window)
    return (
        int(info["x"]) + left,
        int(info["y"]) + top,
        int(info["width"]) - left - right,
        int(info["height"]) - top - bottom,
    )


def wait_visible_rect(window: str, timeout: float = 5.0) -> tuple[int, int, int, int]:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = visible_rect(window)
        except SmokeFailure:
            time.sleep(0.05)
            continue
        if last[2] > 0 and last[3] > 0:
            return last
        time.sleep(0.05)
    raise SmokeFailure(f"All Notes never got a visible rect; last: {last}")


def click_center(
    xtest: base.XTest, window: str, center: list[float], label: str
) -> tuple[int, int]:
    """Click a GTK coordinate, compensating for CSD shadow extents."""
    left, top, _width, _height = wait_visible_rect(window)
    scale = base._effective_scale()
    x = left + round(center[0] * scale)
    y = top + round(center[1] * scale)
    # XTest clicks do not carry a user timestamp, so a click on an inactive
    # window may only activate it instead of reaching the widget. Focus first
    # (a real click does both in one step), then click.
    focus_window(xtest, window)
    base._raise_until_top(xtest, window, x, y, label)
    xtest.click(x, y)
    print(f"smoke-all-notes: clicked {label} at {x},{y}")
    return x, y


def focus_window(xtest: base.XTest, window: str) -> None:
    """Give *window* the keyboard focus without a WM click.

    XTest button events carry no user timestamp, so Mutter refuses to move the
    active window between windows of one application. A real mouse click does
    carry one; the smoke sets X input focus explicitly to type reliably.
    """
    xtest.xlib.XSetInputFocus.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_ulong,
    ]
    xtest.xlib.XSetInputFocus(
        xtest.display, int(window, 16), 2, 0  # RevertToParent, CurrentTime
    )
    xtest.xlib.XFlush(xtest.display)
    time.sleep(0.2)


def ctrl_a(xtest: base.XTest) -> None:
    control = xtest.xlib.XKeysymToKeycode(xtest.display, 0xFFE3)
    letter = xtest.xlib.XKeysymToKeycode(xtest.display, ord("a"))
    xtest.xtst.XTestFakeKeyEvent(xtest.display, control, 1, 0)
    xtest.xtst.XTestFakeKeyEvent(xtest.display, letter, 1, 0)
    xtest.xtst.XTestFakeKeyEvent(xtest.display, letter, 0, 0)
    xtest.xtst.XTestFakeKeyEvent(xtest.display, control, 0, 0)
    xtest.xlib.XFlush(xtest.display)


def ctrl_f(xtest: base.XTest) -> None:
    control = xtest.xlib.XKeysymToKeycode(xtest.display, 0xFFE3)
    letter = xtest.xlib.XKeysymToKeycode(xtest.display, ord("f"))
    xtest.xtst.XTestFakeKeyEvent(xtest.display, control, 1, 0)
    xtest.xtst.XTestFakeKeyEvent(xtest.display, letter, 1, 0)
    xtest.xtst.XTestFakeKeyEvent(xtest.display, letter, 0, 0)
    xtest.xtst.XTestFakeKeyEvent(xtest.display, control, 0, 0)
    xtest.xlib.XFlush(xtest.display)
    time.sleep(0.1)


def backspace(xtest: base.XTest) -> None:
    xtest._tap(0xFF08)


def wait_all_notes(
    dump: Path,
    app: subprocess.Popen[str],
    predicate,
    timeout: float = base.DUMP_TIMEOUT,
) -> dict:
    def matches(snapshot: dict) -> bool:
        block = snapshot.get("all_notes")
        return isinstance(block, dict) and predicate(block)

    return base._wait_dump(
        dump,
        app,
        lambda snapshot: matches(snapshot),
        timeout=timeout,
    )["all_notes"]


def window_ids() -> list[str]:
    tree = base._run("xwininfo", "-root", "-tree")
    return re.findall(r"^\s*(0x[0-9a-f]+)\s+", tree, re.MULTILINE)


def wait_menu_window(
    process: subprocess.Popen[str], timeout: float = 3.0
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for window in window_ids():
            if base._window_pid(window) != process.pid:
                continue
            kind = base._run(
                "xprop", "-id", window, "_NET_WM_WINDOW_TYPE"
            )
            if "_NET_WM_WINDOW_TYPE_MENU" in kind:
                return window
        time.sleep(0.05)
    raise SmokeFailure("the All Notes menu did not open")


def check_window_is_normal(window: str) -> None:
    """Spec §9.1: All Notes is an ordinary window, not a deck overlay."""
    properties = base._run(
        "xprop",
        "-id",
        window,
        "_NET_WM_STATE",
        "_NET_WM_DESKTOP",
        "_NET_WM_ALLOWED_ACTIONS",
        "_NET_WM_WINDOW_TYPE",
        "WM_HINTS",
    )
    for forbidden in (
        "_NET_WM_STATE_ABOVE",
        "_NET_WM_STATE_SKIP_TASKBAR",
        "_NET_WM_STATE_SKIP_PAGER",
        "_NET_WM_STATE_STICKY",
    ):
        if forbidden in properties:
            raise SmokeFailure(
                f"All Notes has the deck-only state {forbidden}; "
                "it would disappear from the dock/Alt+Tab"
            )
    if "Client accepts input or input focus: True" not in properties:
        raise SmokeFailure("All Notes cannot take keyboard focus")
    if "_NET_WM_ACTION_RESIZE" not in properties:
        raise SmokeFailure("All Notes is not resizable (no _NET_WM_ACTION_RESIZE)")
    if "_NET_WM_WINDOW_TYPE_NORMAL" not in properties:
        raise SmokeFailure("All Notes is not a normal window")
    desktop = re.search(r"_NET_WM_DESKTOP\(CARDINAL\) = (\d+)", properties)
    if desktop is None:
        raise SmokeFailure("All Notes has no _NET_WM_DESKTOP")
    if int(desktop.group(1)) == ALL_DESKTOPS:
        raise SmokeFailure("All Notes is sticky on all desktops; it should not be")


def check_geometry(window: str, snapshot: dict) -> None:
    if snapshot.get("decorated") is not True:
        raise SmokeFailure("All Notes is not decorated")
    if snapshot.get("resizable") is not True:
        raise SmokeFailure("All Notes reports resizable=False")
    if (snapshot.get("width"), snapshot.get("height")) != (WIDTH, HEIGHT):
        raise SmokeFailure(
            "All Notes GTK size is "
            f"{snapshot.get('width')}x{snapshot.get('height')}, "
            f"expected {WIDTH}x{HEIGHT}"
        )

    left, top, width, height = wait_visible_rect(window)
    scale = base._effective_scale()
    expected = (round(WIDTH * scale), round(HEIGHT * scale))
    if (width, height) != expected:
        raise SmokeFailure(
            f"All Notes visible size is {width}x{height}, expected {expected}"
        )
    info = base._window_info(window)
    if info.get("map_state") != "IsViewable":
        raise SmokeFailure(f"All Notes is not viewable: {info.get('map_state')}")

    workarea_x, workarea_y, workarea_w, workarea_h = base._workarea()
    center = (left + width / 2, top + height / 2)
    expected_center = (
        workarea_x + workarea_w / 2,
        workarea_y + workarea_h / 2,
    )
    if abs(center[0] - expected_center[0]) > CENTER_TOLERANCE or abs(
        center[1] - expected_center[1]
    ) > CENTER_TOLERANCE:
        raise SmokeFailure(
            f"All Notes centre {center} is not the workarea centre {expected_center}"
        )
    print(
        "smoke-all-notes: normal window "
        f"{width}x{height} at {left},{top}, centred on {expected_center}"
    )


def check_dark(xtest: base.XTest, window: str) -> None:
    # Keep every sampled point away from the right-hand panel overlay; the
    # left half of All Notes is never under it.
    left, top, width, height = wait_visible_rect(window)
    xid = int(window, 16)
    deadline = time.monotonic() + base.COVER_TIMEOUT
    while time.monotonic() < deadline:
        points = (
            (left + 4, top + 40),
            (left + width // 2, top + 40),
            (left + 4, top + height - 5),
            (left + width // 2, top + height - 5),
        )
        clear = True
        for x, y in points:
            xtest.move(x, y)
            xtest.raise_window(window)
            if xtest.top_window_at_pointer() != xid:
                clear = False
                break
        if clear:
            break
        time.sleep(0.1)
    else:
        raise SmokeFailure("another window covers All Notes; cannot capture pixels")

    image = base._xwd_image(window)
    pixel, image_width, image_height = base._pixel_sampler(image)
    extent_left, extent_right, _extent_top, extent_bottom = frame_extents(window)
    bottom = image_height - extent_bottom - 4
    for x in (extent_left + 4, image_width - extent_right - 4):
        observed = pixel(x, bottom)
        if observed != BACKGROUND:
            raise SmokeFailure(
                f"All Notes background is #{observed[0]:02x}{observed[1]:02x}"
                f"{observed[2]:02x}, expected #1c1c22"
            )

    half = extent_left + (image_width - extent_left - extent_right) // 2
    white = 0
    for y in range(40, image_height - extent_bottom, 8):
        for x in range(extent_left, half, 8):
            red, green, blue = pixel(x, y)
            if red > 245 and green > 245 and blue > 245:
                white += 1
    if white:
        raise SmokeFailure(
            f"All Notes has {white} near-white samples; dark theme failed"
        )


def write_payload(path: Path) -> dict:
    ids = {
        "groceries": "aaaaaaaa-1111-4111-8111-111111111111",
        "standup": "bbbbbbbb-2222-4222-8222-222222222222",
        "later": "cccccccc-3333-4333-8333-333333333333",
        "same_one": "dddddddd-4444-4444-8444-444444444444",
        "same_two": "eeeeeeee-5555-4555-8555-555555555555",
    }
    payload = {
        "version": 1,
        "notes": [
            {
                "id": ids["groceries"],
                "text": "Groceries\nmilk\neggs\nbread",
                "created": 100.0,
                "updated": 1793025900.12,
            },
            {
                "id": ids["standup"],
                "text": "Standup\nnotes",
                "created": 101.0,
                "updated": 1793025619.33,
            },
            {
                "id": ids["later"],
                "text": "Later match\nWhat went well\nplenty of EGGS everywhere",
                "created": 102.0,
                "updated": 1793025750.0,
            },
            {
                "id": ids["same_one"],
                "text": "Same title\nfirst copy",
                "created": 103.0,
                "updated": 1793025000.0,
            },
            {
                "id": ids["same_two"],
                "text": "Same title\nsecond copy\nEGGS in body",
                "created": 104.0,
                "updated": 1793025800.0,
            },
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ids


def run_search_and_quit(
    data_home: Path, notes_path: Path, dump: Path
) -> None:
    ids = {
        "groceries": "aaaaaaaa-1111-4111-8111-111111111111",
        "standup": "bbbbbbbb-2222-4222-8222-222222222222",
        "later": "cccccccc-3333-4333-8333-333333333333",
        "same_one": "dddddddd-4444-4444-8444-444444444444",
        "same_two": "eeeeeeee-5555-4555-8555-555555555555",
    }
    deck_order = [
        ids["groceries"],
        ids["standup"],
        ids["later"],
        ids["same_one"],
        ids["same_two"],
    ]
    app: subprocess.Popen[str] | None = None
    xtest: base.XTest | None = None
    try:
        app = start_app(data_home, dump)
        base._wait_for_window(STRIP_TITLE, app)
        all_notes = base._wait_for_window(ALL_NOTES_TITLE, app)
        xtest = base.XTest()

        snapshot = wait_all_notes(
            dump,
            app,
            lambda block: block.get("mapped") is True
            and block.get("ids") == deck_order,
        )
        if snapshot["titles"] != [
            "Groceries",
            "Standup",
            "Later match",
            "Same title",
            "Same title",
        ]:
            raise SmokeFailure(f"All Notes order is {snapshot['titles']}")
        if snapshot["snippets"] != [
            "milk",
            "notes",
            "What went well",
            "first copy",
            "second copy",
        ]:
            raise SmokeFailure(
                f"All Notes snippets are {snapshot['snippets']}"
            )
        for date in snapshot["dates"]:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", date) is None:
                raise SmokeFailure(f"unexpected updated date {date!r}")
        check_geometry(all_notes, snapshot)
        check_window_is_normal(all_notes)
        check_dark(xtest, all_notes)
        print("smoke-all-notes: list shows title, snippet and updated date in deck order")

        search_center = snapshot["search_center"]
        if search_center is None:
            raise SmokeFailure("All Notes search entry has no clickable centre")
        click_center(xtest, all_notes, search_center, "the search entry")
        focus_window(xtest, all_notes)
        ctrl_f(xtest)
        xtest.type_text("eggs")
        narrowed = wait_all_notes(
            dump,
            app,
            lambda block: block.get("query") == "eggs"
            and block.get("ids")
            == [ids["groceries"], ids["later"], ids["same_two"]],
        )
        if narrowed["snippets"] != [
            "eggs",
            "plenty of EGGS everywhere",
            "EGGS in body",
        ]:
            raise SmokeFailure(
                f"search snippets are {narrowed['snippets']}"
            )
        if "<b>EGGS</b>" not in narrowed["markups"][1]:
            raise SmokeFailure(
                "the uppercase match is not highlighted: "
                f"{narrowed['markups'][1]!r}"
            )
        print("smoke-all-notes: search narrowed to matches anywhere, match bolded")

        ctrl_a(xtest)
        backspace(xtest)
        cleared = wait_all_notes(
            dump,
            app,
            lambda block: block.get("query") == ""
            and block.get("ids") == deck_order,
        )
        print("smoke-all-notes: clearing the query restored every note")

        later_index = deck_order.index(ids["later"])
        later_center = cleared["row_centers"][later_index]
        if later_center is None:
            raise SmokeFailure("the Later match row has no clickable centre")
        opened = None
        for attempt in range(1, 4):
            x, y = click_center(
                xtest, all_notes, later_center, "the Later match row"
            )
            # The first synthetic click may only activate the window; a real
            # pointer click both activates and presses the row.
            time.sleep(0.2)
            xtest.click(x, y)
            try:
                opened = base._wait_dump(
                    dump,
                    app,
                    lambda value: value.get("state") == "open"
                    and value.get("current_id") == ids["later"]
                    and (value.get("all_notes") or {}).get("mapped") is True,
                    timeout=2.0,
                )
                break
            except SmokeFailure:
                print(
                    f"smoke-all-notes: row click attempt {attempt} did not open"
                )
        if opened is None:
            raise SmokeFailure("clicking the Later match row never opened it")
        if base._window_info(all_notes).get("map_state") != "IsViewable":
            raise SmokeFailure("All Notes closed when a row opened the panel")
        if opened["text"] != "Later match\nWhat went well\nplenty of EGGS everywhere":
            raise SmokeFailure(
                f"the row opened the wrong note text: {opened['text']!r}"
            )
        print("smoke-all-notes: row click opened the note and kept All Notes mapped")

        panel_typed = False
        for attempt in range(1, 4):
            try:
                current = json.loads(dump.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            if current.get("state") != "open" or current.get("current_id") != ids["later"]:
                # A concurrent agent's Esc/click can close our panel; reopen
                # the same note before typing again.
                click_center(
                    xtest, all_notes, later_center, "the Later match row"
                )
            note_window = base._wait_for_window(NOTE_TITLE, app)
            base._click_editor(xtest, note_window)
            focus_window(xtest, note_window)
            xtest.type_text("\nsmokeword")
            try:
                base._wait_dump(
                    dump,
                    app,
                    lambda value: value.get("state") == "open"
                    and value.get("current_id") == ids["later"]
                    and "smokeword" in (value.get("text") or ""),
                    timeout=3.0,
                )
                panel_typed = True
                break
            except SmokeFailure:
                print(
                    f"smoke-all-notes: panel typing attempt {attempt} was lost"
                )
        if not panel_typed:
            raise SmokeFailure("typing in the panel never reached the note")

        typed = None
        for attempt in range(1, 4):
            click_center(
                xtest, all_notes, cleared["search_center"], "the search entry"
            )
            focus_window(xtest, all_notes)
            ctrl_f(xtest)
            ctrl_a(xtest)
            backspace(xtest)
            xtest.type_text("smokeword")
            try:
                typed = wait_all_notes(
                    dump,
                    app,
                    lambda block: block.get("query") == "smokeword"
                    and block.get("ids") == [ids["later"]],
                    timeout=3.0,
                )
                break
            except SmokeFailure:
                print(
                    f"smoke-all-notes: search typing attempt {attempt} was lost"
                )
        if typed is None:
            raise SmokeFailure("typing in the search entry never narrowed the list")
        if "smokeword" not in typed["snippets"][0]:
            raise SmokeFailure(
                f"live typing is not in the snippet: {typed['snippets']}"
            )
        if "<b>smokeword</b>" not in typed["markups"][0]:
            raise SmokeFailure(
                f"live typed match is not highlighted: {typed['markups'][0]!r}"
            )
        if base._window_info(all_notes).get("map_state") != "IsViewable":
            raise SmokeFailure("All Notes unmapped while typing was reflected")
        print("smoke-all-notes: typing in the panel reached All Notes live")

        menu_center = typed["menu_center"]
        if menu_center is None:
            raise SmokeFailure("the All Notes menu button has no clickable centre")
        click_center(xtest, all_notes, menu_center, "the menu button")
        menu = wait_menu_window(app)
        menu_info = base._window_info(menu)
        menu_x = int(menu_info["x"]) + int(menu_info["width"]) // 2
        menu_y = int(menu_info["y"]) + int(menu_info["height"]) // 2
        if xtest.top_window_at_pointer() != int(menu, 16):
            xtest.move(menu_x, menu_y)
        if xtest.top_window_at_pointer() != int(menu, 16):
            raise SmokeFailure("the Quit menu item is covered")
        xtest.click(menu_x, menu_y)
        print(f"smoke-all-notes: clicked {QUIT!r} in the menu")
        base._wait_for_exit(app)
        base._wait_for_no_windows(
            (STRIP_TITLE, FAN_TITLE, NOTE_TITLE, ALL_NOTES_TITLE), app
        )

        saved = json.loads(notes_path.read_text(encoding="utf-8"))
        later_note = next(
            note for note in saved["notes"] if note["id"] == ids["later"]
        )
        if not later_note["text"].endswith("\nsmokeword"):
            raise SmokeFailure("menu Quit did not flush the typed text")
        print("smoke-all-notes: menu Quit exited cleanly and saved the panel text")
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if app is not None:
            base._stop(app)


def run_close_keeps_app_alive(data_home: Path, dump: Path) -> None:
    app: subprocess.Popen[str] | None = None
    xtest: base.XTest | None = None
    try:
        app = start_app(data_home, dump)
        strip = base._wait_for_window(STRIP_TITLE, app)
        all_notes = base._wait_for_window(ALL_NOTES_TITLE, app)
        xtest = base.XTest()
        wait_all_notes(dump, app, lambda block: block.get("mapped") is True)
        closed = False
        for attempt in range(1, 4):
            xtest.close_window(all_notes)
            try:
                wait_all_notes(
                    dump,
                    app,
                    lambda block: block.get("visible") is False
                    and block.get("mapped") is False,
                    timeout=2.0,
                )
                closed = True
                break
            except SmokeFailure:
                print(
                    f"smoke-all-notes: close attempt {attempt} was not delivered"
                )
        if not closed:
            raise SmokeFailure("All Notes did not hide on a WM close request")
        base._ensure_running(app)
        if base._window_info(strip).get("map_state") != "IsViewable":
            raise SmokeFailure("closing All Notes also unmapped the strip")
        print(
            "smoke-all-notes: closing All Notes kept the app alive and the strip mapped"
        )
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if app is not None:
            base._stop(app)


def main() -> int:
    try:
        base._assert_app_id_free(
            f"dev.lurknotes.LurkNotes.allnotes-smoke.s{os.getpid()}"
        )
        with tempfile.TemporaryDirectory(
            prefix="lurknotes-smoke-all-notes-"
        ) as temporary:
            data_home = Path(temporary)
            notes_dir = data_home / "lurknotes"
            notes_dir.mkdir()
            notes_path = notes_dir / "notes.json"
            write_payload(notes_path)

            run_search_and_quit(data_home, notes_path, data_home / "run1.json")
            run_close_keeps_app_alive(data_home, data_home / "run2.json")

            print("smoke-all-notes: OK")
            return 0
    except SmokeFailure as failure:
        print(f"smoke-all-notes: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a smoke failure
        print(
            f"smoke-all-notes: FAIL: {type(failure).__name__}: {failure}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
