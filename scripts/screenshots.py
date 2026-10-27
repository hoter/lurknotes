#!/usr/bin/env python3
"""Regenerate the README screenshots from the real app.

Runs one isolated instance per scenario (temporary XDG tree, unique app id),
seeds a small readable deck, drives the real widgets through the existing test
control channel, captures the X11 windows with ``xwd`` and writes optimised
 PNGs into ``docs/screenshots/``.

The fan is full-height by design, so the captures are downscaled from the
2x surface to logical size (380 px wide); the hero also includes the strip
that lives to its right at the screen edge.

Usage::

    .venv/bin/python scripts/screenshots.py

Requires Pillow (``pip install pillow``) and an X11/XWayland display.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

try:
    from PIL import Image
except ImportError:  # pragma: no cover - developer tool
    raise SystemExit("install Pillow first: .venv/bin/pip install pillow")

import harness as h  # noqa: E402
import smoke_note as base  # noqa: E402
import smoke_hover as sh  # noqa: E402

OUT = ROOT / "docs" / "screenshots"

# A deck that reads like a real one instead of "Note 01".
SEED = [
    (
        "11111111-1111-4111-8111-111111111111",
        "Groceries\nmilk\neggs\nbread\nolive oil",
    ),
    (
        "22222222-2222-4222-8222-222222222222",
        "Standup\nblocked on the export bug\npair with Ana after lunch",
    ),
    (
        "33333333-3333-4333-8333-333333333333",
        "Lisbon trip\npack light\nbook the tram tour\ntry the pastéis",
    ),
    (
        "44444444-4444-4444-8444-444444444444",
        "Reading list\nThe Pragmatic Programmer\nA Philosophy of Software Design",
    ),
    (
        "55555555-5555-4555-8555-555555555555",
        "Ideas\nnotes deck at the edge\nsnap packaging\nsearch in the fan",
    ),
    (
        "66666666-6666-4666-8666-666666666666",
        "Recipe\nroast tomatoes\ngarlic\nbasil\nolive oil",
    ),
    (
        "77777777-7777-4777-8777-777777777777",
        "Workout\nsquats 3x8\nrows 3x10\nwalk 20 min",
    ),
    (
        "88888888-8888-4888-8888-888888888888",
        "Gifts\nMum: seeds\nDad: coffee\nNina: notebook",
    ),
    (
        "99999999-9999-4999-8999-999999999999",
        "Home\nfix the shelf\norder a lamp",
    ),
    (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "Books to buy\nDesigning Data-Intensive Applications",
    ),
    (
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "Meeting\nThursday 14:00\nbring the roadmap",
    ),
    (
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "Later\nrenew the domain\nbackup the laptop",
    ),
]


def seed(data_home: Path) -> dict[str, str]:
    notes_dir = data_home / "lurknotes"
    notes_dir.mkdir(parents=True)
    notes = [
        {
            "id": note_id,
            "text": text,
            "created": 100.0 + index,
            "updated": 100.0 + index,
        }
        for index, (note_id, text) in enumerate(SEED)
    ]
    (notes_dir / "notes.json").write_text(
        json.dumps({"version": 1, "notes": notes}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {text.splitlines()[0].lower(): note_id for note_id, text in SEED}


def start(data_home: Path, dump: Path, *, pin: bool = True) -> subprocess.Popen[str]:
    extra = {"LURKNOTES_TEST_CONTROL": "1"}
    if pin:
        extra["LURKNOTES_TEST_PIN_DECK"] = "1"
    h.mark_onboarded(data_home)
    env = h.make_env(
        data_home,
        h.app_id(f"shots.s{time.time_ns()}"),
        dump=dump,
        extra=extra,
    )
    return h.launch(["--autostart"], env)


def control(app: subprocess.Popen[str], command: str) -> None:
    if not sh.control(app, command):
        raise SystemExit(f"test control {command!r} failed")


def open_fan(app: subprocess.Popen[str], dump: Path) -> str:
    sh.snapshot(dump, app, lambda s: s.get("state") == "strip", timeout=8.0)
    control(app, "strip")
    fan, _ = sh.wait_fan_viewable(app, timeout=3.0)
    sh.snapshot(dump, app, lambda s: s.get("state") == "fan", timeout=3.0)
    return fan


def grab(window: str, path: Path, scale: float = 0.5) -> Image.Image:
    """Read one X11 window with xwd and return the decoded PIL image."""
    result = subprocess.run(
        ["xwd", "-id", window, "-silent"], capture_output=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(
            f"xwd failed for {window}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    data = result.stdout
    header = struct.unpack(">25I", data[:100])
    width, height = header[4], header[5]
    bits, order, bpl = header[11], header[7], header[12]
    masks = (header[14], header[15], header[16])
    if bits != 32 or masks != (0xFF0000, 0xFF00, 0xFF):
        raise SystemExit(
            f"unsupported xwd format: {bits} bpp, masks {masks!r}"
        )
    offset = header[0] + header[19] * 12
    raw = data[offset : offset + bpl * height]
    image = Image.frombuffer("RGB", (width, height), raw, "raw", "BGRX", bpl, 1)
    image = image.resize(
        (round(width * scale), round(height * scale)),
        Image.LANCZOS,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    print(f"screenshots: {path.relative_to(ROOT)}")
    return image


def raise_for_shot(xtest: base.XTest, window: str, label: str) -> None:
    info = base._window_info(window)
    x = int(info["x"]) + int(info["width"]) // 2
    y = int(info["y"]) + 12
    base._raise_until_top(xtest, window, x, y, label)
    xtest.move(*base._away_point())
    time.sleep(0.35)


def shot_fan(
    xtest: base.XTest,
    app: subprocess.Popen[str],
    dump: Path,
    ids: dict[str, str],
) -> None:
    fan = open_fan(app, dump)
    xtest.move(*base._away_point())
    time.sleep(0.3)
    raise_for_shot(xtest, fan, "the fan")
    image = grab(fan, OUT / "fan.png")
    # The strip is the 10 px edge bar to the right of the fan. Both windows
    # are full workarea height, so the pair reproduces the real left/right
    # relationship on screen.
    strip = base._wait_for_window(base.STRIP_TITLE, app)
    xtest.raise_window(strip)
    strip_path = OUT / ".strip.tmp.png"
    strip_image = grab(strip, strip_path)
    strip_path.unlink(missing_ok=True)
    hero = Image.new("RGB", (image.width + strip_image.width, image.height))
    hero.paste(image, (0, 0))
    hero.paste(strip_image, (image.width, 0))
    hero.save(OUT / "fan.png", optimize=True)
    print(f"screenshots: composed {OUT / 'fan.png'}")

    # Peek: the same fan with one tab hovered through the control channel.
    note_id = ids["standup"]
    control(app, f"tab:{note_id}")
    sh.snapshot(
        dump,
        app,
        lambda s: note_id in ((s.get("peek") or {}).get("visible") or []),
        timeout=3.0,
    )
    raise_for_shot(xtest, fan, "the fan with a peek")
    grab(fan, OUT / "fan-peek.png")

    # Search: click the field, type, settle the 150 ms filter rebuild.
    control(app, f"untab:{note_id}")
    time.sleep(0.2)
    ready = sh.snapshot(
        dump,
        app,
        lambda s: s.get("state") == "fan" and s.get("search_center") is not None,
    )
    sh.click_center(xtest, fan, ready["search_center"], "the search field")
    xtest.focus(fan)
    xtest.type_text("lis")
    sh.snapshot(
        dump,
        app,
        lambda s: s.get("search_text") == "lis"
        and ids["lisbon trip"] in (s.get("tab_ids") or []),
        timeout=3.0,
    )
    raise_for_shot(xtest, fan, "the filtered fan")
    time.sleep(0.25)  # let the 150 ms filter rebuild settle
    grab(fan, OUT / "fan-search.png")

    # Esc in the field clears the query; the next state is the editor.
    xtest.press_escape()
    sh.snapshot(dump, app, lambda s: s.get("search_text") == "", timeout=3.0)
    control(app, f"open:{ids['lisbon trip']}")
    sh.snapshot(
        dump,
        app,
        lambda s: s.get("state") == "open"
        and s.get("current_id") == ids["lisbon trip"],
        timeout=3.0,
    )
    raise_for_shot(xtest, fan, "the open note")
    time.sleep(0.2)
    grab(fan, OUT / "note.png")

    # Back to the fan and a live drag (button held while the shot is taken).
    xtest.focus(fan)
    xtest.press_escape()
    sh.snapshot(dump, app, lambda s: s.get("state") == "fan", timeout=3.0)
    ready = sh.snapshot(
        dump,
        app,
        lambda s: s.get("state") == "fan"
        and len(s.get("tab_centers") or []) >= 4,
    )
    centers = ready["tab_centers"]
    sx, sy = sh.point_in(fan, *centers[0])
    tx, ty = sh.point_in(fan, *centers[2])
    base._raise_until_top(xtest, fan, sx, sy, "the dragged tab")
    xtest.move(sx, sy)
    xtest.press()
    xtest.move(sx, sy + round(10 * base._effective_scale()))
    xtest.move(tx, ty)
    sh.snapshot(
        dump,
        app,
        lambda s: (s.get("drag") or {}).get("target_index") == 2
        and (s.get("drag") or {}).get("translating") is True,
        timeout=3.0,
    )
    # Stop between rows: the ghost then visibly hovers above the gap instead
    # of sitting exactly in it, which reads as a drag without a cursor glyph.
    xtest.move(tx, ty - round(15 * base._effective_scale()))
    sh.snapshot(
        dump,
        app,
        lambda s: (s.get("drag") or {}).get("target_index") == 2
        and (s.get("drag") or {}).get("translating") is True,
        timeout=3.0,
    )
    time.sleep(0.3)  # let the 150 ms row transition settle
    xtest.raise_window(fan)
    grab(fan, OUT / "drag.png")
    xtest.release()


def shot_empty(xtest: base.XTest, temporary: Path) -> None:
    data_home = temporary / "empty"
    data_home.mkdir(parents=True)
    dump = data_home / "dump.json"
    app = start(data_home, dump)
    try:
        fan = open_fan(app, dump)
        xtest.move(*base._away_point())
        time.sleep(0.35)
        raise_for_shot(xtest, fan, "the empty fan")
        grab(fan, OUT / "empty.png")
    finally:
        base._stop(app)


def main() -> int:
    xtest: base.XTest | None = None
    app: subprocess.Popen[str] | None = None
    try:
        xtest = base.XTest()
        with tempfile.TemporaryDirectory(prefix="lurknotes-shots-") as temp:
            temporary = Path(temp)
            data_home = temporary / "deck"
            ids = seed(data_home)
            dump = data_home / "dump.json"
            app = start(data_home, dump)
            shot_fan(xtest, app, dump, ids)
            base._stop(app)
            app = None
            shot_empty(xtest, temporary)
        print("screenshots: OK")
        return 0
    except sh.SmokeFailure as failure:
        print(f"screenshots: FAIL: {failure}", file=sys.stderr)
        return 1
    except Exception as failure:  # noqa: BLE001 - report anything as a failure
        print(f"screenshots: FAIL: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    finally:
        if xtest is not None:
            xtest.restore()
            xtest.close()
        if app is not None:
            base._stop(app)


if __name__ == "__main__":
    raise SystemExit(main())
