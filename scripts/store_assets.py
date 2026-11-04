#!/usr/bin/env python3
"""Build the Snap Store listing images into ``packaging/store/``.

The Store wants 16:9 screenshots (1600x900), a square app icon and an
optional 1920x1080 featured banner. The README screenshots in
``docs/screenshots/`` are portrait captures of the real windows, so each one is
placed on a dark card with a caption instead of being uploaded as-is.

Everything is drawn with Pillow and the DejaVu fonts that ship with Ubuntu; the
icon is rendered from ``packaging/lurknotes.svg`` by rasterising the rounded
rectangles it is made of, so no SVG rasteriser has to be installed.

Usage::

    .venv/bin/python scripts/store_assets.py

Output::

    packaging/store/icon.png              512x512
    packaging/store/banner.png            1920x1080
    packaging/store/screenshot-{1..6}.png 1600x900
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover - developer tool
    raise SystemExit("install Pillow first: .venv/bin/pip install pillow")

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
ICON_SVG = ROOT / "packaging" / "lurknotes.svg"
OUT = ROOT / "packaging" / "store"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

# The window captures are 380-390 x 928. A card keeps them readable while the
# caption occupies the rest of the 16:9 frame.
CARD = (1600, 900)
BANNER = (1920, 1080)
ICON = 512

BACKGROUND = (24, 24, 28)
BACKGROUND_EDGE = (13, 13, 16)
TEXT = (233, 233, 241)
MUTED = (169, 169, 184)
ACCENT = (140, 180, 255)

# (source, caption, sub-caption) in the order they tell the story: what the
# deck is, how you peek, how you find, how you edit, how you order, how you
# start.
SCREENSHOTS = [
    (
        "fan.png",
        "A deck at the edge of the screen",
        "Hover the strip to unfold your notes, then get back to work",
    ),
    (
        "fan-peek.png",
        "Peek without opening",
        "Hover a tab to read the first lines; the deck stays out of the way",
    ),
    (
        "fan-search.png",
        "Find as you type",
        "The deck filters while you type, no mode to switch",
    ),
    (
        "note.png",
        "One note, rail and editor",
        "Edits autosave after 400 ms; nothing to save by hand",
    ),
    (
        "drag.png",
        "Drag to reorder",
        "Rows make room for the dragged tab",
    ),
    (
        "empty.png",
        "Start with a single note",
        "Notes live in one local JSON file, with a backup",
    ),
]


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = FONT_DIR / name
    if not path.is_file():
        raise SystemExit(f"missing font {path}; install fonts-dejavu-core")
    return ImageFont.truetype(str(path), size)


def background(size: tuple[int, int]) -> Image.Image:
    """A soft vertical wash, dark at the edges and slightly lighter mid-frame."""
    width, height = size
    image = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        # Cosine falloff keeps the centre subtle instead of a visible band.
        import math

        t = (math.cos((y / height) * math.pi) + 1) / 2
        blend = 0.35 * t
        colour = tuple(
            round(edge + (base - edge) * blend)
            for edge, base in zip(BACKGROUND_EDGE, BACKGROUND)
        )
        draw.line([(0, y), (width, y)], fill=colour)
    return image


def rounded_shadow(
    image: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    *,
    blur: int = 24,
) -> None:
    """Drop a soft shadow behind a rounded rectangle."""
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle(box, radius=radius, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    image.paste(shadow, (0, 0), shadow)


def paste_window(
    canvas: Image.Image,
    window: Image.Image,
    top_centre: tuple[int, int],
    *,
    max_height: int,
) -> tuple[int, int, int, int]:
    """Scale the capture so its height fits and centre it above a caption."""
    scale = min(1.0, max_height / window.height)
    width = round(window.width * scale)
    height = round(window.height * scale)
    if scale != 1.0:
        window = window.resize((width, height), Image.LANCZOS)
    x = top_centre[0] - width // 2
    y = top_centre[1]
    box = (x - 12, y - 12, x + width + 12, y + height + 12)
    rounded_shadow(canvas, box, radius=20)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=20, fill=(43, 43, 53))
    canvas.paste(window, (x, y))
    return box


def caption(
    canvas: Image.Image,
    centre_x: int,
    top: int,
    title: str,
    subtitle: str,
) -> None:
    draw = ImageDraw.Draw(canvas)
    title_font = font(46, bold=True)
    subtitle_font = font(27)

    for text, face, size, colour, offset in (
        (title, title_font, 46, TEXT, 0),
        (subtitle, subtitle_font, 27, MUTED, 66),
    ):
        width = draw.textlength(text, font=face)
        draw.text(
            (centre_x - width / 2, top + offset),
            text,
            font=face,
            fill=colour,
        )


def screenshot_card(
    source: Path,
    title: str,
    subtitle: str,
    index: int,
) -> Path:
    window = Image.open(source).convert("RGB")
    canvas = background(CARD)
    width, height = CARD

    # Leave room for the caption at the bottom; the window keeps its aspect.
    caption_height = 170
    max_height = height - caption_height - 90
    top = 60
    paste_window(canvas, window, (width // 2, top), max_height=max_height)

    # The strip in fan.png sits at the right edge; the caption stays centred
    # under the whole card so cards read as a set.
    caption(canvas, width // 2, top + max_height + 34, title, subtitle)

    # A quiet index in the corner helps ordering inside the Store carousel.
    draw = ImageDraw.Draw(canvas)
    label = f"0{index}"
    draw.text(
        (width - 96, 44),
        label,
        font=font(28, bold=True),
        fill=(72, 72, 84),
    )
    return _save(canvas, OUT / f"screenshot-{index}.png")


def banner() -> Path:
    window = Image.open(SHOTS / "fan.png").convert("RGB")
    canvas = background(BANNER)
    width, height = BANNER

    # The deck sits on the right; the copy column on the left stays well
    # above the bottom third, where store fronts overlay their own chrome.
    max_height = height - 300
    scale = min(2.0, max_height / window.height)
    scaled = window.resize(
        (round(window.width * scale), round(window.height * scale)),
        Image.LANCZOS,
    )
    x = width - scaled.width - 170
    y = (height - scaled.height) // 2 - 30
    box = (x - 16, y - 16, x + scaled.width + 16, y + scaled.height + 16)
    rounded_shadow(canvas, box, radius=26, blur=34)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=26, fill=(43, 43, 53))
    canvas.paste(scaled, (x, y))

    # Keep the copy inside the left column so it never runs under the deck.
    draw = ImageDraw.Draw(canvas)
    draw.text((150, 236), "LurkNotes", font=font(104, bold=True), fill=TEXT)
    draw.line([(156, 388), (376, 388)], fill=ACCENT, width=6)
    draw.text(
        (156, 430),
        "Your notes, kept at the edge",
        font=font(38),
        fill=MUTED,
    )
    draw.text(
        (156, 482),
        "of the screen",
        font=font(38),
        fill=MUTED,
    )

    body = [
        "Hover to unfold,",
        "peek without opening,",
        "search as you type.",
        "",
        "Local only: one JSON file,",
        "a backup, no account,",
        "no network.",
    ]
    y_text = 560
    for line in body:
        if line:
            draw.text((156, y_text), line, font=font(27), fill=(200, 200, 212))
        y_text += 38

    if y_text > height - 240:  # pragma: no cover - layout guard
        raise SystemExit("banner copy runs into the bottom third; shorten it")

    return _save(canvas, OUT / "banner.png")


def _save(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    print(f"store assets: wrote {path.relative_to(ROOT)} ({image.width}x{image.height})")
    return path


def icon() -> Path:
    """Rasterise packaging/lurknotes.svg.

    The icon is a handful of rounded rectangles, so the SVG is parsed with a
    regular expression and drawn directly: no rasteriser dependency, and the
    output stays crisp at 512 px because every coordinate is scaled.
    """
    svg = ICON_SVG.read_text(encoding="utf-8")
    view = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if not view:
        raise SystemExit(f"no viewBox in {ICON_SVG}")
    base_w, base_h = float(view.group(1)), float(view.group(2))
    scale = ICON / base_w

    canvas = Image.new("RGBA", (ICON, ICON), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for match in re.finditer(r"<rect\b([^>]*)/>", svg):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', match.group(1)))
        x = float(attrs.get("x", 0)) * scale
        y = float(attrs.get("y", 0)) * scale
        w = float(attrs["width"]) * scale
        h = float(attrs["height"]) * scale
        radius = float(attrs.get("rx", 0)) * scale
        fill = attrs.get("fill", "#000000")
        draw.rounded_rectangle(
            (x, y, x + w - 1, y + h - 1),
            radius=radius,
            fill=_colour(fill),
        )

    path = OUT / "icon.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, optimize=True)
    print(f"store assets: wrote {path.relative_to(ROOT)} ({ICON}x{ICON})")
    return path


def _colour(value: str) -> tuple[int, int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return (red, green, blue, 255)


def main() -> int:
    missing = [name for name, _, _ in SCREENSHOTS if not (SHOTS / name).is_file()]
    if missing:
        raise SystemExit(
            "missing screenshots: "
            + ", ".join(missing)
            + "; run scripts/screenshots.py first"
        )

    icon()
    banner()
    for index, (name, title, subtitle) in enumerate(SCREENSHOTS, start=1):
        screenshot_card(SHOTS / name, title, subtitle, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
