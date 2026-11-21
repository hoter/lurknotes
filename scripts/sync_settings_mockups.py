#!/usr/bin/env python3
"""Render mockups of the sync settings in the deck.

This is a throwaway design tool for the wayfinder prototype ticket
(``.scratch/sync/issues/09-prototype-settings-ui.md``): it draws the fan at its
real width (380 px, spec §6) with the real palette from ``theme.css``, so the
four candidate placements can be compared as pictures instead of prose.

It renders a 2x scale and downsamples, matching ``scripts/screenshots.py``, so
text stays crisp. Nothing here ships; the real widget is written after a
variant is chosen.

Usage::

    .venv/bin/python scripts/sync_settings_mockups.py

Output: ``.scratch/sync/prototype/mockups/variant-{a,b,c,d}-*.png``
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - developer tool
    raise SystemExit("install Pillow first: .venv/bin/pip install pillow")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".scratch" / "sync" / "prototype" / "mockups"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

SCALE = 2

# Palette, verbatim from src/lurkn/ui/theme.css (spec §6.4).
WINDOW = "#1c1c22"
STRIP = "#24242c"
TAB = "#2b2b35"
TAB_HOVER = "#353542"
TAB_DRAG = "#3d3d4c"
RAIL = "#17171d"
TEXT = "#e9e9f1"
TEXT_2 = "#a9a9b8"
TEXT_3 = "#6f6f7e"
TOAST = "#3a3a46"

# Status colours are not in the v1 palette; these are new and need a decision.
SYNC_ON = "#7bb489"
SYNC_OFF = "#6f6f7e"
SYNC_ERR = "#c98a6b"

FAN_WIDTH = 380
FAN_HEIGHT = 720


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size * SCALE)


def box(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    colour: str,
    *,
    radius: int = 6,
) -> None:
    scaled = tuple(int(value * SCALE) for value in rect)
    draw.rounded_rectangle(scaled, radius=radius * SCALE, fill=colour)


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    *,
    size: int = 13,
    bold: bool = False,
    colour: str = TEXT,
) -> None:
    draw.text(
        (xy[0] * SCALE, xy[1] * SCALE),
        value,
        font=font(size, bold=bold),
        fill=colour,
    )


def base_fan(notes: list[str], *, rows_top: int = 102) -> Image.Image:
    """The fan as it is today: header, search, hint, tabs, peek pane."""
    image = Image.new("RGB", (FAN_WIDTH * SCALE, FAN_HEIGHT * SCALE), WINDOW)
    draw = ImageDraw.Draw(image)

    # Header bar: title, +, », ×.
    text(draw, (10, 12), "LURK NOTES", size=12, bold=True)
    text(draw, (300, 12), "+   »   ×", size=13, colour=TEXT_2)
    box(draw, (10, 34, 370, 35), TAB)

    # Search entry.
    box(draw, (10, 44, 370, 74), TAB)
    text(draw, (20, 54), "⌕  Search notes", size=13, colour=TEXT_3)

    text(
        draw,
        (10, rows_top - 20),
        "hover a note to peek · drag to reorder",
        size=11,
        colour=TEXT_3,
    )

    y = rows_top
    for index, note in enumerate(notes):
        colour = TAB_HOVER if index == 0 else TAB
        box(draw, (10, y, 370, y + 38), colour)
        text(draw, (20, y + 11), note, size=13)
        y += 44

    # Peek pane, pinned to the bottom.
    box(draw, (10, FAN_HEIGHT - 150, 370, FAN_HEIGHT - 18), TAB)
    text(draw, (20, FAN_HEIGHT - 140), "Groceries", size=13, bold=True)
    for line in ("milk", "eggs", "bread"):
        text(draw, (20, FAN_HEIGHT - 118 + ("milk", "eggs", "bread").index(line) * 22),
             line, size=12, colour=TEXT_2)

    return image


NOTES = [
    "Groceries",
    "Standup",
    "Lisbon trip",
    "Reading list",
    "Ideas",
    "Recipe",
    "Workout",
    "Gifts",
    "Home",
]


def variant_a() -> Image.Image:
    """A gear in the header opens a dialog over the fan."""
    image = base_fan(NOTES)
    draw = ImageDraw.Draw(image)

    # Header gains a gear between » and ×.
    text(draw, (300, 12), "+   »   ⚙   ×", size=13, colour=SYNC_ON)

    # Dialog panel over the deck.
    box(draw, (24, 150, 356, 500), TAB, radius=10)
    text(draw, (40, 166), "Sync", size=16, bold=True)

    text(draw, (40, 200), "Sync notes with LurkNotes", size=13)
    text(draw, (40, 220), "Off — the deck stays local", size=11, colour=TEXT_3)

    # Toggle, off.
    box(draw, (40, 246, 92, 272), TAB_HOVER, radius=13)
    box(draw, (44, 250, 66, 268), TEXT_2, radius=9)
    text(draw, (104, 250), "Off", size=13, colour=TEXT_2)

    # Fields, disabled while off.
    box(draw, (40, 296, 340, 324), WINDOW)
    text(draw, (50, 302), "email", size=12, colour=TEXT_3)
    box(draw, (40, 330, 340, 358), WINDOW)
    text(draw, (50, 336), "password", size=12, colour=TEXT_3)

    box(draw, (270, 370, 340, 398), TAB_HOVER)
    text(draw, (292, 376), "Sign in", size=12, colour=TEXT_3)

    text(draw, (40, 420), "Last sync: never", size=11, colour=TEXT_3)
    text(draw, (270, 460), "Close", size=12, colour=TEXT_2)
    return image


def variant_b() -> Image.Image:
    """A always-visible section under the tabs, above the peek pane."""
    image = base_fan(NOTES)
    draw = ImageDraw.Draw(image)

    top = 486
    box(draw, (10, top, 370, top + 1), TAB)
    text(draw, (14, top + 10), "SYNC", size=10, bold=True, colour=TEXT_3)
    box(draw, (14, top + 30, 58, top + 52), TAB_HOVER, radius=11)
    box(draw, (17, top + 33, 35, top + 49), TEXT_2, radius=8)
    text(draw, (66, top + 33), "Off — notes stay on this machine", size=11, colour=TEXT_2)
    text(draw, (14, top + 60), "Turn on to sync with LurkNotes", size=10, colour=TEXT_3)
    return image


def variant_c() -> Image.Image:
    """Ctrl+, opens a settings mode inside the panel, like GNOME apps."""
    image = Image.new("RGB", (FAN_WIDTH * SCALE, FAN_HEIGHT * SCALE), RAIL)
    draw = ImageDraw.Draw(image)

    # A rail on the left, settings on the right — same frame as the panel.
    box(draw, (0, 0, 112, FAN_HEIGHT), RAIL)
    for index, label in enumerate(("‹ Back", "Groceries", "Standup", "Lisbon trip")):
        y = 20 + index * 44
        if index == 0:
            text(draw, (12, y), label, size=13, colour=TEXT_2)
        else:
            box(draw, (8, y - 6, 104, y + 26), TAB)
            text(draw, (16, y), label, size=12)

    box(draw, (112, 0, FAN_WIDTH, FAN_HEIGHT), WINDOW)
    text(draw, (128, 24), "Sync", size=18, bold=True)
    text(draw, (128, 56), "Keep your deck on every machine.", size=12, colour=TEXT_2)

    text(draw, (128, 96), "Synchronisation", size=13, bold=True)
    box(draw, (128, 122, 180, 148), TAB_HOVER, radius=13)
    box(draw, (132, 126, 154, 144), TEXT_2, radius=9)
    text(draw, (192, 126), "Off", size=13, colour=TEXT_2)
    text(draw, (128, 156), "Nothing leaves this machine.", size=11, colour=TEXT_3)

    text(draw, (128, 196), "Account", size=13, bold=True)
    box(draw, (128, 220, 356, 248), TAB)
    text(draw, (138, 226), "email@example.com", size=12, colour=TEXT_3)
    box(draw, (128, 254, 356, 282), TAB)
    text(draw, (138, 260), "••••••••", size=12, colour=TEXT_3)
    box(draw, (244, 294, 356, 320), TAB_HOVER)
    text(draw, (270, 299), "Sign in", size=12, colour=TEXT_3)

    text(draw, (128, 340), "Status", size=13, bold=True)
    text(draw, (128, 362), "●  Off — never synced", size=12, colour=SYNC_OFF)
    return image


def variant_d() -> Image.Image:
    """A single toggle line in the fan plus a status chip in the header."""
    image = base_fan(NOTES, rows_top=136)
    draw = ImageDraw.Draw(image)

    # The header gains a small status dot before the buttons.
    draw.ellipse(
        (int(286 * SCALE), int(17 * SCALE), int(294 * SCALE), int(25 * SCALE)),
        fill=SYNC_OFF,
    )
    text(draw, (300, 12), "+   »   ×", size=13, colour=TEXT_2)

    # One row under the search, above the hint.
    box(draw, (10, 82, 370, 108), TAB)
    box(draw, (18, 86, 62, 104), TAB_HOVER, radius=9)
    box(draw, (21, 89, 37, 101), TEXT_2, radius=6)
    text(draw, (70, 87), "Sync off · local only", size=12, colour=TEXT_2)
    text(draw, (318, 87), "Set up", size=12, colour=SYNC_ON)

    return image


def error_state() -> Image.Image:
    """The same chip in D, with a failed token — the state that must be obvious."""
    image = variant_d()
    draw = ImageDraw.Draw(image)
    box(draw, (10, 82, 370, 108), TAB)
    draw.ellipse(
        (int(286 * SCALE), int(17 * SCALE), int(294 * SCALE), int(25 * SCALE)),
        fill=SYNC_ERR,
    )
    box(draw, (18, 86, 62, 104), TAB_HOVER, radius=9)
    box(draw, (21, 89, 37, 101), SYNC_ERR, radius=6)
    text(draw, (70, 87), "Signed out · notes not syncing", size=12, colour=SYNC_ERR)
    text(draw, (302, 87), "Sign in", size=12, colour=SYNC_ON)
    return image


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rendered = {
        "variant-a-dialog": variant_a(),
        "variant-b-section": variant_b(),
        "variant-c-settings-mode": variant_c(),
        "variant-d-inline-toggle": variant_d(),
        "variant-d-error-state": error_state(),
    }
    for name, image in rendered.items():
        path = OUT / f"{name}.png"
        image.resize(
            (FAN_WIDTH, FAN_HEIGHT), Image.LANCZOS
        ).save(path, optimize=True)
        print(f"mockups: wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
