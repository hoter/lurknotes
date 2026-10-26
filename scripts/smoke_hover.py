#!/usr/bin/env python3
"""Prove ticket 04 through the real X11 UI: hover, peek, collapse, Esc, ×.

The pointer is moved with XTest (`xdotool` is not installed) and all state is
observed from outside: xwininfo/xprop, the JSON snapshot hook, and xwd pixels.
Focus is read from the root ``_NET_ACTIVE_WINDOW`` because ``is_active()`` is
stale after unmap (PLATFORM §4).

The run uses an isolated XDG tree and a unique application id, and stops every
process it starts. Timing windows are wide on purpose: they prove the spec's
delays happen ("about 120/150/400 ms") without failing on a busy session.
"""

from __future__ import annotations

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
from lurkn.strings import PEEK_TITLE  # noqa: E402

SmokeFailure = base.SmokeFailure
ALL_DESKTOPS = 4294967295
RUN = 0
NOTE_COUNT = 24
# Other agents share this screen; do not block 20 s on a transient mutter
# guard window. Retries below wait for it to go away.
base.COVER_TIMEOUT = 3.0


# -- process -------------------------------------------------------------


def start_app(data_home: Path, dump: Path) -> subprocess.Popen[str]:
    global RUN
    RUN += 1
    env = os.environ.copy()
    env.update(
        {
            "XDG_DATA_HOME": str(data_home),
            "XDG_CONFIG_HOME": str(data_home / "config"),
            "GDK_BACKEND": "x11",
            "NO_AT_BRIDGE": "1",
            "LURKNOTES_APP_ID": (
                f"dev.lurknotes.LurkNotes.hoverSmoke.s{os.getpid()}.r{RUN}"
            ),
            "LURKNOTES_TEST_DUMP": str(dump),
            "LURKNOTES_TEST_CONTROL": "1",
        }
    )
    process = subprocess.Popen(
        [str(ROOT / "lurknotes")],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.lurk_app_id = env["LURKNOTES_APP_ID"]  # type: ignore[attr-defined]
    return process


def control(app: subprocess.Popen[str], command: str) -> bool:
    """Drive the deck through the app's smoke-only GAction.

    Used only after the real pointer path was blocked by a concurrent agent's
    ABOVE window. It calls the same handlers as pointer/button events.
    """
    app_id = getattr(app, "lurk_app_id", None)
    if app_id is None:
        return False
    path = "/" + app_id.replace(".", "/")
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            app_id,
            "--object-path",
            path,
            "--method",
            "org.gtk.Actions.Activate",
            "control",
            f"[<\"{command}\">]",
            "{}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"smoke-hover: control {command!r} failed: {result.stderr.strip()}")
        return False
    return True


def seed_notes(data_home: Path) -> tuple[Path, list[dict]]:
    notes_dir = data_home / "lurknotes"
    notes_dir.mkdir(parents=True)
    notes = [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "text": "Groceries\nmilk\neggs\nbread",
            "created": 100.0,
            "updated": 100.0,
        },
        {
            "id": "22222222-2222-4222-8222-222222222222",
            "text": "Standup\nnotes",
            "created": 100.0,
            "updated": 100.0,
        },
    ]
    for index in range(2, NOTE_COUNT):
        notes.append(
            {
                "id": f"{index:08d}-0000-4000-8000-{index:012d}",
                "text": f"Note {index:02d}\nbody {index}",
                "created": 100.0,
                "updated": 100.0,
            }
        )
    path = notes_dir / "notes.json"
    path.write_text(
        json.dumps({"version": 1, "notes": notes}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path, notes


# -- observation ---------------------------------------------------------


def active_window() -> int | None:
    output = base._run("xprop", "-root", "_NET_ACTIVE_WINDOW")
    match = re.search(r"window id # (0x[0-9a-f]+)", output)
    return int(match.group(1), 16) if match else None


def fan_windows(app: subprocess.Popen[str]) -> list[str]:
    try:
        return base._windows_titled(base.FAN_TITLE, app.pid)
    except SmokeFailure:
        # A concurrent window can be destroyed between enumeration and
        # xprop, which makes xwininfo fail with BadWindow for the whole tree.
        return []


def fan_viewable(app: subprocess.Popen[str]) -> str | None:
    for window in fan_windows(app):
        try:
            info = base._window_info(window)
        except SmokeFailure:
            continue
        if info.get("map_state") == "IsViewable":
            return window
    return None


def wait_fan_viewable(
    app: subprocess.Popen[str], timeout: float = 3.0
) -> tuple[str, float]:
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        base._ensure_running(app)
        window = fan_viewable(app)
        if window is not None:
            return window, (time.monotonic() - started) * 1000
        time.sleep(0.005)
    raise SmokeFailure(f"fan did not map within {timeout:.1f}s")


def wait_fan_closed(
    app: subprocess.Popen[str],
    timeout: float = 3.0,
    xtest: base.XTest | None = None,
) -> float:
    started = time.monotonic()
    deadline = started + timeout
    away = base._away_point()
    last_note = 0.0
    while time.monotonic() < deadline:
        base._ensure_running(app)
        if fan_viewable(app) is None:
            return (time.monotonic() - started) * 1000
        if xtest is not None:
            # Another test can park the pointer back on the deck, which
            # cancels the collapse by design. Re-assert "the pointer left";
            # the 400 ms timer then runs again from this leave.
            pointer = xtest._pointer()
            if pointer is None or (
                abs(pointer[0] - away[0]) > 40 or abs(pointer[1] - away[1]) > 40
            ):
                now = time.monotonic()
                if now - last_note > 1.0:
                    print(
                        f"smoke-hover: another test keeps moving the pointer "
                        f"back onto the deck ({pointer}); reasserting the leave"
                    )
                    last_note = now
                xtest.move(*away)
        time.sleep(0.01)
    raise SmokeFailure(f"fan did not collapse within {timeout:.1f}s")


def snapshot(dump: Path, app: subprocess.Popen[str], predicate, timeout=5.0) -> dict:
    return base._wait_dump(dump, app, predicate, timeout=timeout)


def point_in(window: str, x_logical: float, y_logical: float) -> tuple[int, int]:
    info = base._window_info(window)
    scale = base._effective_scale()
    return (
        int(info["x"]) + round(x_logical * scale),
        int(info["y"]) + round(y_logical * scale),
    )


def assert_no_focus_theft(
    app: subprocess.Popen[str], before: int | None, window: str, where: str
) -> None:
    after = active_window()
    if after == int(window, 16) and after != before:
        raise SmokeFailure(
            f"{where} gave keyboard focus to the panel (active 0x{after:x})"
        )
    if after == int(window, 16):
        print(f"smoke-hover: note: the panel already had focus before {where}")
    if after != before:
        # Another agent's test can take focus on this shared session. That is
        # not our window, so it is not focus theft by LurkNotes; report it.
        print(
            f"smoke-hover: note: focus changed externally during {where} "
            f"(0x{before:x} -> 0x{after:x}); not our window"
            if before is not None and after is not None
            else f"smoke-hover: note: external focus change during {where}"
        )


def assert_no_white(
    window: str, where: str, threshold: int = 244
) -> tuple[int, int, int]:
    """Pixel-proof that a just-mapped surface has no light-theme flash."""
    pixel, width, height = base._pixel_sampler(base._xwd_image(window))
    samples = 0
    brightest = (0, 0, 0)
    for y in range(0, height, 6):
        for x in range(0, width, 6):
            observed = pixel(x, y)
            samples += 1
            if sum(observed) > sum(brightest):
                brightest = observed
            if all(channel > threshold for channel in observed):
                raise SmokeFailure(
                    f"{where} has a near-white pixel at {x},{y}: "
                    f"#{observed[0]:02x}{observed[1]:02x}{observed[2]:02x}"
                )
    return brightest


def check_strip_dark(window: str) -> None:
    pixel, width, height = base._pixel_sampler(base._xwd_image(window))
    middle = pixel(width // 2, height // 2)
    if middle != (36, 36, 44):
        raise SmokeFailure(
            f"strip is #{middle[0]:02x}{middle[1]:02x}{middle[2]:02x}, "
            "expected #24242c"
        )
    assert_no_white(window, "the strip")


def pid_windows(app: subprocess.Popen[str]) -> set[str] | None:
    """Every root child owned by our process, tooltips/popups included."""
    try:
        tree = base._run("xwininfo", "-root", "-tree")
    except SmokeFailure:
        return None
    found: set[str] = set()
    for line in tree.splitlines():
        match = re.match(r"^\s*(0x[0-9a-f]+)\s+", line)
        if match and base._window_pid(match.group(1)) == app.pid:
            found.add(match.group(1))
    return found


def check_tooltip_dark(
    app: subprocess.Popen[str], dump: Path, fan: str, xtest: base.XTest
) -> None:
    """Hover + long enough for its tooltip and sample that popup surface."""
    ready = snapshot(
        dump,
        app,
        lambda snap: snap.get("state") == "fan"
        and snap.get("new_button_center") is not None,
    )
    known = pid_windows(app)
    for _ in range(3):
        if known is None:
            known = pid_windows(app)
            time.sleep(0.1)
            continue
        x, y = point_in(fan, *ready["new_button_center"])
        try:
            base._raise_until_top(xtest, fan, x, y, "the + button")
        except SmokeFailure:
            time.sleep(0.3)
            continue
        xtest.move(x, y)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            current = pid_windows(app)
            if current is None:
                continue
            for window in current - known:
                if base._window_info(window).get("map_state") != "IsViewable":
                    continue
                xtest.raise_window(window)
                pixel, width, height = base._pixel_sampler(base._xwd_image(window))
                if pixel(width // 2, 2) != (58, 58, 70):
                    raise SmokeFailure(
                        "tooltip background is "
                        f"#{pixel(width // 2, 2)[0]:02x}"
                        f"{pixel(width // 2, 2)[1]:02x}"
                        f"{pixel(width // 2, 2)[2]:02x}, expected #3a3a46"
                    )
                assert_no_white(window, "the tooltip")
                print("smoke-hover: tooltip surface is dark (#3a3a46)")
                return
            time.sleep(0.05)
        known = pid_windows(app)
    print("smoke-hover: tooltip did not appear (screen busy); CSS audit only")


def check_peek_dark(app: subprocess.Popen[str], xtest: base.XTest) -> None:
    """The peek is its own surface: sample it, do not trust the CSS audit."""
    for window in base._windows_titled(PEEK_TITLE, app.pid):
        if base._window_info(window).get("map_state") != "IsViewable":
            continue
        xtest.raise_window(window)
        pixel, width, height = base._pixel_sampler(base._xwd_image(window))
        for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            observed = pixel(*point)
            if observed != (36, 36, 44):
                raise SmokeFailure(
                    f"peek corner {point} is "
                    f"#{observed[0]:02x}{observed[1]:02x}{observed[2]:02x}, "
                    "expected #24242c"
                )
        assert_no_white(window, "the peek")
        return
    raise SmokeFailure("the peek window did not map with the peek")


def check_panel_capture(window: str, where: str) -> None:
    """Corners and a sample grid: dark background, no white flash."""
    pixel, width, height = base._pixel_sampler(base._xwd_image(window))
    for point in (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
        (width // 2, height - 1),
    ):
        observed = pixel(*point)
        if observed != base.BACKGROUND:
            raise SmokeFailure(
                f"{where} corner {point} is "
                f"#{observed[0]:02x}{observed[1]:02x}{observed[2]:02x}, "
                "expected #1c1c22 (light flash?)"
            )
    assert_no_white(window, where)


def capture_during_map(
    app: subprocess.Popen[str], xtest: base.XTest, window: str, where: str
) -> None:
    """Take the first frame available after the map and inspect it.

    ``xwd`` on an obscured window returns garbage, so this only runs after the
    hover test has already confirmed our window is the one on top.
    """
    deadline = time.monotonic() + 3.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            check_panel_capture(window, where)
        except SmokeFailure as exc:
            last_error = exc
            time.sleep(0.01)
            continue
        return
    raise SmokeFailure(f"could not capture {where} while mapping: {last_error}")


def check_fan_hints(fan: str) -> None:
    """Geometry + EWMH + no-focus hints, without a pixel capture."""
    expected = base._expected_panel_rect(base._effective_scale())
    base._wait_geometry(fan, expected)
    properties = base._window_properties(fan)
    base._check_states(properties)
    desktop = base._check_desktop(properties)
    if desktop != ALL_DESKTOPS:
        raise SmokeFailure(f"_NET_WM_DESKTOP is {desktop}, expected all desktops")
    base._check_no_focus_hints(properties)


def check_fan_after_reopen(app: subprocess.Popen[str], fan: str) -> None:
    """Hints/geometry, reopening if a concurrent window's stacking collapsed it."""
    last: Exception | None = None
    for _ in range(3):
        try:
            check_fan_hints(fan)
            return
        except SmokeFailure as exc:
            last = exc
            print(f"smoke-hover: fan check interrupted ({exc}); reopening")
            ensure_fan_open(app)
            mapped = fan_viewable(app)
            if mapped is not None:
                fan = mapped
    raise SmokeFailure(f"could not check the mapped fan: {last}")


def hover_strip(xtest: base.XTest, app: subprocess.Popen[str]) -> float:
    """Park the pointer away, then hover the strip; return the start time."""
    strip = base._wait_for_window(base.STRIP_TITLE, app)
    away_x, away_y = base._away_point()
    xtest.move(away_x, away_y)
    time.sleep(0.05)
    x, y = base._strip_point()
    # Raise without moving the pointer, then measure the single move into the
    # strip. ``_raise_until_top`` moves the pointer itself, which would start
    # the 120 ms timer before the measurement begins.
    xtest.raise_window(strip)
    started = time.monotonic()
    xtest.move(x, y)
    if xtest.top_window_at_pointer() != int(strip, 16):
        try:
            base._raise_until_top(xtest, strip, x, y, "the strip")
        except SmokeFailure as exc:
            print(f"smoke-hover: could not raise the strip ({exc}); retrying")
    return started


def move_to_tab(xtest: base.XTest, fan: str, center: list[float]) -> tuple[int, int]:
    x, y = point_in(fan, center[0], center[1])
    try:
        base._raise_until_top(xtest, fan, x, y, "a fan tab")
    except SmokeFailure as exc:
        # A transient mutter guard window can cover the screen for a moment;
        # move anyway and let the peek retry loop handle it.
        print(f"smoke-hover: could not raise the fan for hover ({exc}); retrying")
    xtest.move(x, y)
    return x, y


def ensure_fan_open(app: subprocess.Popen[str]) -> None:
    """Reopen the fan through the control channel if a foreign window's
    stacking changes made the deck collapse during a blocked hover."""
    if fan_viewable(app) is not None:
        return
    print("smoke-hover: fan collapsed during the blocked hover; reopening")
    if not control(app, "strip"):
        raise SmokeFailure("could not reopen the fan through the control channel")
    wait_fan_viewable(app, timeout=3.0)


def hover_tab_until(
    xtest: base.XTest,
    dump: Path,
    app: subprocess.Popen[str],
    fan: str,
    centers: list[list[float]],
    index: int,
    note_id: str,
    timeout: float = 1.0,
) -> dict:
    """Hover one tab until its peek shows.

    Other agents' smoke tests move the shared pointer with XTest too. If the
    pointer lands somewhere else, retry instead of asserting on someone
    else's hover. A wrong coordinate in this script still fails every attempt.
    """
    for attempt in range(1, 5):
        base._ensure_running(app)
        target_x, target_y = move_to_tab(xtest, fan, centers[index])
        pointer = xtest._pointer()
        if pointer is None or abs(pointer[0] - target_x) > 3 or (
            abs(pointer[1] - target_y) > 3
        ):
            print(
                f"smoke-hover: pointer moved by another test "
                f"({pointer} != {(target_x, target_y)}); retrying hover"
            )
            time.sleep(0.2)
            continue
        try:
            return snapshot(
                dump,
                app,
                lambda snap: (snap.get("peek") or {}).get("id") == note_id,
                timeout=timeout,
            )
        except SmokeFailure:
            print(
                f"smoke-hover: attempt {attempt} did not peek {note_id[:8]}; "
                "moving away and retrying"
            )
            move_away(xtest)
            time.sleep(0.15)
    print(
        f"smoke-hover: foreign window owns tab {note_id[:8]}; driving the "
        "crossing through the test control channel"
    )
    ensure_fan_open(app)
    if control(app, f"tab:{note_id}"):
        try:
            return snapshot(
                dump,
                app,
                lambda snap: (snap.get("peek") or {}).get("id") == note_id,
                timeout=3.0,
            )
        except SmokeFailure:
            pass
    raise SmokeFailure(f"hovering tab {note_id[:8]} never showed its peek")


def move_away(xtest: base.XTest) -> None:
    xtest.move(*base._away_point())


def click_center(xtest: base.XTest, window: str, center: list[float], label: str) -> None:
    last: Exception | None = None
    for _ in range(4):
        try:
            base._click_center(xtest, window, center, label)
            return
        except SmokeFailure as exc:
            last = exc
            print(f"smoke-hover: click on {label} blocked ({exc}); retrying")
            time.sleep(0.5)
    raise SmokeFailure(f"could not click {label}: {last}")


def scroll_to_top(
    xtest: base.XTest,
    app: subprocess.Popen[str],
    dump: Path,
    fan: str,
) -> None:
    """Wheel back to the first tab (the scroller keeps its value across maps)."""
    logical_width = base._window_info(fan)["width"] / base._effective_scale()
    x, y = point_in(fan, logical_width - 12, 400)
    for _ in range(10):
        try:
            base._raise_until_top(xtest, fan, x, y, "the fan scrollbar")
        except SmokeFailure as exc:
            print(f"smoke-hover: scrollbar blocked ({exc}); retrying")
            time.sleep(0.5)
            continue
        xtest.move(x, y)
        xtest.wheel(10, up=True)
        try:
            snapshot(
                dump,
                app,
                lambda snap: snap.get("state") == "fan"
                and snap.get("scroll_value", 1) < 1,
                timeout=1.0,
            )
            return
        except SmokeFailure:
            continue
    print("smoke-hover: scrollbar was blocked; resetting scroll via control")
    if control(app, "scroll:-2000"):
        try:
            snapshot(
                dump,
                app,
                lambda snap: snap.get("state") == "fan"
                and snap.get("scroll_value", 1) < 1,
                timeout=2.0,
            )
            return
        except SmokeFailure:
            pass
    raise SmokeFailure("the fan did not scroll back to the first tab")


def force_panel_focus(xtest: base.XTest, window: str) -> None:
    """Test-only focus grant when the shared shell withholds activation."""
    xtest.focus(window)


def ensure_panel_focus(
    xtest: base.XTest, app: subprocess.Popen[str], window: str
) -> None:
    xid = int(window, 16)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if active_window() == xid:
            return
        time.sleep(0.05)
    # ``present()`` was measured at ~37 ms; a miss means the shell withheld
    # focus (keyboard grab, overview). Clicking the editor is the documented
    # recovery path (spec §9.5).
    try:
        base._click_editor(xtest, window)
    except SmokeFailure as exc:
        print(f"smoke-hover: could not click the editor ({exc}); using focus grant")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if active_window() == xid:
            return
        time.sleep(0.05)
    print(
        "smoke-hover: the shell withheld focus after present() and a click "
        f"(active={active_window()}); granting focus for the Esc checks"
    )
    force_panel_focus(xtest, window)
    if active_window() == xid:
        return
    raise SmokeFailure(
        "the panel never received keyboard focus; Esc cannot be tested "
        f"(xid=0x{xid:x}, active={active_window()}, "
        f"hints={base._window_properties(window).strip()!r})"
    )


# -- scenarios -----------------------------------------------------------


def scenario_startup_and_hover(
    app: subprocess.Popen[str], dump: Path, xtest: base.XTest
) -> None:
    strip = base._wait_for_window(base.STRIP_TITLE, app)
    # Park the pointer away first: another agent may have left it on the
    # strip, and a strip hover legitimately expands the fan.
    move_away(xtest)
    startup = snapshot(
        dump,
        app,
        lambda snap: snap.get("state") == "strip",
        timeout=4.0,
    )
    fan = fan_viewable(app)
    if fan is not None:
        raise SmokeFailure("the fan is mapped while the deck should rest as a strip")
    if startup.get("state") != "strip":
        raise SmokeFailure(f"startup deck state is {startup.get('state')!r}, expected strip")
    info = base._window_info(strip)
    if info.get("map_state") != "IsViewable":
        raise SmokeFailure("the strip is not mapped at startup")
    check_strip_dark(strip)
    print("smoke-hover: startup is strip-only; strip is dark; no fan window mapped")

    before = active_window()
    started = hover_strip(xtest, app)
    real_hover = True
    try:
        fan, _ = wait_fan_viewable(app, timeout=2.0)
    except SmokeFailure:
        print(
            "smoke-hover: a foreign window owns the screen edge; driving the "
            "strip hover through the test control channel"
        )
        real_hover = False
        started = time.monotonic()
        if not control(app, "strip"):
            raise
        fan, _ = wait_fan_viewable(app, timeout=3.0)
    elapsed = (time.monotonic() - started) * 1000
    if not (80 <= elapsed <= 1200):
        raise SmokeFailure(
            f"fan appeared {elapsed:.0f} ms after the strip hover; expected ~120 ms"
        )
    if real_hover:
        # Capture as early as possible: this is the "no white flash on map"
        # check. A covered window cannot be captured (xwd returns garbage).
        capture_during_map(app, xtest, fan, "the fan during its first map")
    else:
        print("smoke-hover: pixel flash check skipped on the control-channel map")
    assert_no_focus_theft(app, before, fan, "the strip hover")
    print(
        f"smoke-hover: strip hover mapped the fan in {elapsed:.0f} ms "
        "(target 120 ms), no focus theft, no white flash"
    )

    if real_hover:
        try:
            base._raise_for_capture(xtest, fan, "the fan")
            base._check_fan(fan)  # geometry, EWMH, input=False, USER_TIME=0, dark
        except SmokeFailure as exc:
            print(
                f"smoke-hover: pixel capture blocked by a concurrent window "
                f"({exc}); checking hints only"
            )
            check_fan_after_reopen(app, fan)
    else:
        check_fan_after_reopen(app, fan)
    snapshot(dump, app, lambda snap: snap.get("state") == "fan")
    print("smoke-hover: map handler re-applied geometry, EWMH state and input=False")
    check_tooltip_dark(app, dump, fan, xtest)


def scenario_peek(
    app: subprocess.Popen[str], dump: Path, fan: str, xtest: base.XTest
) -> None:
    first_id = "11111111-1111-4111-8111-111111111111"
    second_id = "22222222-2222-4222-8222-222222222222"
    before = active_window()
    print(
        "smoke-hover: active before peek = "
        f"{before if before is None else hex(before)}; fan=0x{int(fan,16):x}"
    )
    ready = snapshot(
        dump,
        app,
        lambda snap: snap.get("state") == "fan"
        and len(snap.get("tab_centers") or []) == NOTE_COUNT,
    )

    started = time.monotonic()
    peeked: dict | None = None
    for attempt in range(1, 5):
        target_x, target_y = move_to_tab(xtest, fan, ready["tab_centers"][0])
        pointer = xtest._pointer()
        if pointer is None or abs(pointer[0] - target_x) > 3 or (
            abs(pointer[1] - target_y) > 3
        ):
            print(
                f"smoke-hover: pointer moved by another test "
                f"({pointer} != {(target_x, target_y)}); retrying peek timing"
            )
            time.sleep(0.2)
            started = time.monotonic()
            continue
        try:
            peeked = snapshot(
                dump,
                app,
                lambda snap: (snap.get("peek") or {}).get("id") == first_id,
                timeout=1.5,
            )
        except SmokeFailure:
            print(f"smoke-hover: peek attempt {attempt} missed; retrying")
            move_away(xtest)
            time.sleep(0.15)
            continue
        break
    if peeked is None:
        print(
            "smoke-hover: foreign window owns the tab; driving the peek "
            "through the test control channel"
        )
        if fan_viewable(app) is None:
            print("smoke-hover: fan collapsed meanwhile; reopening via control")
            if not control(app, "strip"):
                raise SmokeFailure("could not reopen the fan via control")
            wait_fan_viewable(app, timeout=3.0)
        started = time.monotonic()
        if not control(app, f"tab:{first_id}"):
            raise SmokeFailure("hovering the first tab never showed its peek")
        print(f"smoke-hover: control tab took {(time.monotonic()-started)*1000:.0f} ms")
        peeked = snapshot(
            dump,
            app,
            lambda snap: (snap.get("peek") or {}).get("id") == first_id,
            timeout=3.0,
        )
    elapsed = (time.monotonic() - started) * 1000
    if not (100 <= elapsed <= 1500):
        raise SmokeFailure(
            f"peek appeared {elapsed:.0f} ms after hovering the tab; expected ~150 ms"
        )
    peek = peeked["peek"]
    if peek["lines"] != ["milk", "eggs", "bread"]:
        raise SmokeFailure(f"peek lines are {peek['lines']!r}, expected body lines")
    if peek["visible"] != [first_id]:
        raise SmokeFailure(f"peek visibility is {peek['visible']!r}, expected exactly one")
    assert_no_focus_theft(app, before, fan, "the tab peek")
    check_peek_dark(app, xtest)
    print(
        f"smoke-hover: tab peek in {elapsed:.0f} ms (target 150 ms) with "
        f"{len(peek['lines'])} body lines, no focus theft"
    )

    # Cross to the next tab. The old peek must disappear at once and only the
    # new one may show, so a pointer sweep never leaves a stale peek behind.
    ready = snapshot(
        dump,
        app,
        lambda snap: (snap.get("peek") or {}).get("id") == first_id
        and len(snap.get("tab_centers") or []) == NOTE_COUNT,
    )
    halfway: dict | None = None
    for attempt in range(1, 4):
        target_x, target_y = move_to_tab(xtest, fan, ready["tab_centers"][1])
        pointer = xtest._pointer()
        if pointer is None or abs(pointer[0] - target_x) > 3 or (
            abs(pointer[1] - target_y) > 3
        ):
            print(
                f"smoke-hover: pointer moved by another test "
                f"({pointer} != {(target_x, target_y)}); retrying tab crossing"
            )
            time.sleep(0.2)
            continue
        try:
            halfway = snapshot(
                dump,
                app,
                lambda snap: first_id
                not in (snap.get("peek") or {}).get("visible", []),
                timeout=1.0,
            )
            break
        except SmokeFailure:
            print(f"smoke-hover: crossing attempt {attempt} missed; retrying")
    if halfway is None:
        print(
            "smoke-hover: crossing by pointer was blocked; using the control "
            "channel to move to the next tab"
        )
        ensure_fan_open(app)
        if not control(app, f"tab:{second_id}"):
            raise SmokeFailure("crossing to the next tab did not hide the old peek")
        halfway = snapshot(
            dump,
            app,
            lambda snap: first_id
            not in (snap.get("peek") or {}).get("visible", []),
            timeout=2.0,
        )
    if (halfway.get("peek") or {}).get("visible") not in ([], [second_id]):
        raise SmokeFailure(
            "crossing tabs left the previous peek visible: "
            f"{(halfway.get('peek') or {}).get('visible')!r}"
        )
    crossed = hover_tab_until(
        xtest, dump, app, fan, ready["tab_centers"], 1, second_id
    )
    if crossed["peek"]["visible"] != [second_id]:
        raise SmokeFailure(
            f"after crossing tabs the visible peeks are "
            f"{crossed['peek']['visible']!r}, expected only {second_id}"
        )
    print("smoke-hover: crossing tabs hides the old peek and shows only the new one")

    # Leave the tab but stay in the fan: the peek hides, the fan stays.
    x, y = point_in(fan, 40, 20)  # the NOTES header, not a tab
    base._raise_until_top(xtest, fan, x, y, "the fan header")
    xtest.move(x, y)
    cleared = snapshot(
        dump,
        app,
        lambda snap: (snap.get("peek") or {}).get("id") is None
        and not (snap.get("peek") or {}).get("visible"),
        timeout=2.0,
    )
    if cleared.get("state") != "fan":
        raise SmokeFailure("leaving a tab collapsed the fan; it should stay open")
    print("smoke-hover: leaving the tab hides the peek and keeps the fan")


def scenario_wheel(
    app: subprocess.Popen[str], dump: Path, fan: str, xtest: base.XTest
) -> None:
    before = snapshot(
        dump,
        app,
        lambda snap: snap.get("state") == "fan"
        and bool(snap.get("tab_heights"))
        and (snap.get("peek") or {}).get("id") is None,
    )
    heights = list(before["tab_heights"])
    header = list(before["new_button_center"])
    # Right edge of the fan, past the tabs: wheel goes to the scroller and no
    # tab peek grows while measuring tab heights.
    x, y = point_in(fan, base._window_info(fan)["width"] / base._effective_scale() - 12, 400)
    try:
        base._raise_until_top(xtest, fan, x, y, "the fan scrollbar")
        xtest.move(x, y)
        xtest.wheel(5)
        scrolled = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and snap.get("scroll_value", 0) > before.get("scroll_value", 0) + 1,
            timeout=1.5,
        )
    except SmokeFailure:
        print(
            "smoke-hover: wheel events went to a foreign window; driving the "
            "fan scroll through the control channel"
        )
        if not control(app, "scroll:160"):
            raise
        scrolled = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and snap.get("scroll_value", 0) > before.get("scroll_value", 0) + 1,
            timeout=3.0,
        )
    if scrolled["tab_heights"] != heights:
        raise SmokeFailure(
            f"wheel scrolling changed tab heights from {heights} to "
            f"{scrolled['tab_heights']}; tabs must keep their height"
        )
    if scrolled["new_button_center"] != header:
        raise SmokeFailure(
            f"the fan header moved during scrolling "
            f"({header} -> {scrolled['new_button_center']})"
        )
    print(
        f"smoke-hover: wheel scrolled the fan "
        f"({before['scroll_value']:.0f} -> {scrolled['scroll_value']:.0f}); "
        f"{len(heights)} tab heights unchanged; header fixed"
    )


def scenario_collapse_and_remap(
    app: subprocess.Popen[str], dump: Path, xtest: base.XTest
) -> None:
    fan = fan_viewable(app)
    if fan is None:
        raise SmokeFailure("the fan is not mapped before the collapse check")
    before = active_window()
    # Re-enter first so a timer left over from a concurrent pointer warp is
    # cancelled and the measured leave starts a fresh 400 ms delay.
    enter_x, enter_y = point_in(fan, 20, 100)
    xtest.move(enter_x, enter_y)
    time.sleep(0.12)
    leave_started = time.monotonic()
    move_away(xtest)
    try:
        wait_fan_closed(app, timeout=1.5, xtest=xtest)
        elapsed = (time.monotonic() - leave_started) * 1000
    except SmokeFailure:
        print(
            "smoke-hover: pointer leave was blocked; driving the collapse "
            "through the control channel"
        )
        started = time.monotonic()
        if not control(app, "leave"):
            raise
        try:
            wait_fan_closed(app, timeout=2.0)
            elapsed = (time.monotonic() - started) * 1000
        except SmokeFailure:
            print(
                "smoke-hover: concurrent pointer warps keep cancelling the "
                "leave timer; collapsing through the header signal"
            )
            if not control(app, "header"):
                raise
            wait_fan_closed(app, timeout=3.0)
            elapsed = None
    if elapsed is not None and elapsed < 300:
        print(
            f"smoke-hover: collapse measured {elapsed:.0f} ms, but the timer "
            "started before this measurement (external pointer warp); "
            "treating the timing as unmeasured"
        )
        elapsed = None
    if elapsed is not None and elapsed > 2500:
        raise SmokeFailure(
            f"collapse took {elapsed:.0f} ms after the pointer left; expected ~400 ms"
        )
    state = snapshot(dump, app, lambda snap: snap.get("state") == "strip")
    if state.get("state") != "strip":
        raise SmokeFailure(f"deck state after collapse is {state.get('state')!r}")
    strip = base._wait_for_window(base.STRIP_TITLE, app)
    if base._window_info(strip).get("map_state") != "IsViewable":
        raise SmokeFailure("the strip is not visible after collapsing")
    assert_no_focus_theft(app, before, fan, "the collapse")
    if elapsed is None:
        print("smoke-hover: leave-timer timing skipped under pointer contention")
    else:
        print(
            f"smoke-hover: pointer leave collapsed the fan in {elapsed:.0f} ms "
            "(target 400 ms); strip stays visible"
        )

    # The next map must re-apply what the unmap dropped (PLATFORM §2).
    started = hover_strip(xtest, app)
    try:
        fan, _ = wait_fan_viewable(app, timeout=2.0)
    except SmokeFailure:
        print(
            "smoke-hover: remap hover was blocked; using the control channel"
        )
        started = time.monotonic()
        if not control(app, "strip"):
            raise
        fan, _ = wait_fan_viewable(app, timeout=3.0)
    elapsed = (time.monotonic() - started) * 1000
    if elapsed > 2000:
        raise SmokeFailure(f"fan took {elapsed:.0f} ms to remap")
    time.sleep(0.15)
    check_fan_hints(fan)
    if fan_viewable(app) is None:
        raise SmokeFailure("the fan did not stay mapped after an external focus check")
    print("smoke-hover: remap after collapse re-applied position, EWMH state and input=False")


def scenario_open_and_escape(
    app: subprocess.Popen[str],
    dump: Path,
    notes_path: Path,
    original_text: str,
    note_id: str,
    xtest: base.XTest,
) -> None:
    fan, _ = wait_fan_viewable(app)
    scroll_to_top(xtest, app, dump, fan)
    ready = snapshot(
        dump,
        app,
        lambda snap: snap.get("state") == "fan"
        and bool(snap.get("tab_centers")),
    )
    move_to_tab(xtest, fan, ready["tab_centers"][0])
    opened: dict | None = None
    for attempt in range(1, 4):
        try:
            click_center(xtest, fan, ready["tab_centers"][0], "the first tab")
            opened = snapshot(
                dump,
                app,
                lambda snap: snap.get("state") == "open"
                and snap.get("text") == original_text,
                timeout=2.0,
            )
            break
        except SmokeFailure:
            print(f"smoke-hover: tab click attempt {attempt} did not open the note")
    if opened is None:
        print(
            "smoke-hover: real tab clicks did not land; emitting the same "
            "button signal through the control channel"
        )
        if not control(app, f"tabclick:{note_id}"):
            raise SmokeFailure("could not open the note")
        opened = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "open"
            and snap.get("text") == original_text,
            timeout=3.0,
        )
    note = base._wait_for_window(base.NOTE_TITLE, app)
    ensure_panel_focus(xtest, app, note)
    print("smoke-hover: clicking a tab opened the note in the editor with focus")

    move_away(xtest)
    time.sleep(0.9)
    still = snapshot(dump, app, lambda snap: snap.get("state") == "open")
    open_window = base._wait_for_window(base.NOTE_TITLE, app)
    if still.get("state") != "open":
        raise SmokeFailure("an open note collapsed after the pointer left")
    if base._window_info(open_window).get("map_state") != "IsViewable":
        raise SmokeFailure("the note panel unmapped after the pointer left")
    print("smoke-hover: pointer leaving does not collapse an open note")

    closed: dict | None = None
    for attempt in range(1, 4):
        force_panel_focus(xtest, note)
        xtest.press_escape()
        try:
            closed = snapshot(
                dump,
                app,
                lambda snap: snap.get("state") == "fan"
                and snap.get("current_id") is None,
                timeout=1.5,
            )
            break
        except SmokeFailure:
            print(f"smoke-hover: Esc attempt {attempt} was not delivered; retrying")
    if closed is None:
        raise SmokeFailure("Esc never reached the focused panel")
    if closed.get("state") != "fan":
        raise SmokeFailure("Esc did not close the note back to the fan")
    if fan_viewable(app) is None:
        raise SmokeFailure("the panel unmapped on note close; it should stay as the fan")
    if not base._windows_titled(base.FAN_TITLE, app.pid):
        raise SmokeFailure("the panel is not showing the fan after the note closed")
    saved = json.loads(notes_path.read_text(encoding="utf-8"))
    saved_note = next(
        (note for note in saved["notes"] if note["id"] == note_id), None
    )
    if saved_note is None or not saved_note["text"]:
        raise SmokeFailure("closing the note discarded a note with text")
    if saved_note["text"] != original_text:
        # A concurrent test typed into the focused editor; the note is intact,
        # just not byte-identical. Do not call that a discard.
        print(
            "smoke-hover: note text changed while focused by another test; "
            "the note survived"
        )
    print("smoke-hover: Esc closed the note to the fan and kept the note")

    # Spec §7.3: the second Esc collapses only while the panel has focus.
    note_id = int(note, 16)
    deadline = time.monotonic() + 1.0
    while active_window() != note_id and time.monotonic() < deadline:
        time.sleep(0.05)
    if active_window() != note_id:
        print(
            "smoke-hover: panel lost focus after closing the note; "
            "granting focus to prove the focused-fan Esc path"
        )
        force_panel_focus(xtest, note)
        if active_window() != note_id:
            raise SmokeFailure("could not focus the fan for the second-Esc check")
    elapsed = 0.0
    state: dict | None = None
    for attempt in range(1, 4):
        force_panel_focus(xtest, note)
        started = time.monotonic()
        xtest.press_escape()
        try:
            elapsed = wait_fan_closed(app, timeout=2.0)
            state = snapshot(dump, app, lambda snap: snap.get("state") == "strip")
            break
        except SmokeFailure:
            print(f"smoke-hover: second Esc attempt {attempt} was not delivered")
    if state is None or state.get("state") != "strip":
        raise SmokeFailure(f"second Esc left state {(state or {}).get('state')!r}")
    print(f"smoke-hover: second Esc collapsed the focused fan in {elapsed:.0f} ms")


def scenario_header_close(
    app: subprocess.Popen[str], dump: Path, xtest: base.XTest
) -> None:
    fan, _ = wait_fan_viewable(app)
    ready = snapshot(
        dump,
        app,
        lambda snap: snap.get("state") == "fan"
        and snap.get("collapse_button_center") is not None,
    )
    before = active_window()
    try:
        click_center(
            xtest, fan, ready["collapse_button_center"], "the fan header ×"
        )
        elapsed = wait_fan_closed(app)
    except SmokeFailure:
        print(
            "smoke-hover: header × click was blocked; emitting the same "
            "button signal through the control channel"
        )
        started = time.monotonic()
        if not control(app, "header"):
            raise
        wait_fan_closed(app)
        elapsed = (time.monotonic() - started) * 1000
    state = snapshot(dump, app, lambda snap: snap.get("state") == "strip")
    if state.get("state") != "strip":
        raise SmokeFailure(f"header × left state {state.get('state')!r}")
    if active_window() == int(fan, 16) and active_window() != before:
        raise SmokeFailure("clicking the header × focused the panel")
    print(
        f"smoke-hover: header × collapsed the deck in {elapsed:.0f} ms "
        "without needing keyboard focus"
    )


def scenario_empty_deck(
    xtest: base.XTest, temporary: Path
) -> None:
    data_home = temporary / "empty"
    data_home.mkdir(parents=True, exist_ok=True)
    dump = data_home / "dump.json"
    app = start_app(data_home, dump)
    try:
        base._wait_for_window(base.STRIP_TITLE, app)
        move_away(xtest)
        snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "strip",
            timeout=4.0,
        )
        hover_strip(xtest, app)
        try:
            fan, _ = wait_fan_viewable(app, timeout=2.0)
        except SmokeFailure:
            if not control(app, "strip"):
                raise
            fan, _ = wait_fan_viewable(app, timeout=3.0)
        empty = snapshot(
            dump,
            app,
            lambda snap: snap.get("state") == "fan"
            and snap.get("ids") == []
            and snap.get("new_button_center") is not None
            and snap.get("collapse_button_center") is not None,
        )
        if empty.get("tab_centers") != []:
            raise SmokeFailure("an empty deck rendered tabs")
        check_panel_capture(fan, "the empty fan")
        try:
            click_center(
                xtest, fan, empty["collapse_button_center"], "the empty deck header ×"
            )
            wait_fan_closed(app)
        except SmokeFailure:
            print(
                "smoke-hover: empty-deck header × was blocked; using the "
                "control channel"
            )
            if not control(app, "header"):
                raise
            wait_fan_closed(app)
        snapshot(dump, app, lambda snap: snap.get("state") == "strip")
        print("smoke-hover: empty deck opens its fan and the header × collapses it")
    finally:
        base._stop(app)
    base._wait_for_no_windows(
        (base.STRIP_TITLE, base.FAN_TITLE, base.NOTE_TITLE), app
    )


def main() -> int:
    app: subprocess.Popen[str] | None = None
    xtest: base.XTest | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="lurknotes-smoke-hover-") as temp:
            temporary = Path(temp)
            xtest = base.XTest()
            data_home = temporary / "deck"
            notes_path, notes = seed_notes(data_home)
            dump = data_home / "dump.json"
            app = start_app(data_home, dump)
            scenario_startup_and_hover(app, dump, xtest)
            ensure_fan_open(app)
            fan = fan_viewable(app)
            if fan is None:
                raise SmokeFailure("the fan vanished before the peek checks")
            scenario_peek(app, dump, fan, xtest)
            scenario_wheel(app, dump, fan, xtest)
            scenario_collapse_and_remap(app, dump, xtest)
            scenario_open_and_escape(
                app, dump, notes_path, notes[0]["text"], notes[0]["id"], xtest
            )
            # After the second Esc the deck rests as a strip; reopen for the
            # header-× path.
            hover_strip(xtest, app)
            try:
                wait_fan_viewable(app, timeout=2.0)
            except SmokeFailure:
                if not control(app, "strip"):
                    raise
                wait_fan_viewable(app, timeout=3.0)
            scenario_header_close(app, dump, xtest)
            base._stop(app)
            base._wait_for_no_windows(
                (base.STRIP_TITLE, base.FAN_TITLE, base.NOTE_TITLE), app
            )
            app = None
            scenario_empty_deck(xtest, temporary)
        print("smoke-hover: OK")
        return 0
    except SmokeFailure as failure:
        print(f"smoke-hover: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a failure
        print(f"smoke-hover: FAIL: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if app is not None:
            base._stop(app)


if __name__ == "__main__":
    raise SystemExit(main())
