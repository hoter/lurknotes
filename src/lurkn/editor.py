"""Plain-text editing rules for the note editor (spec §7.3, decision 12).

The note stays ordinary Markdown text in ``notes.json``: these helpers only
insert or remove characters in the buffer. They are GTK-free so every rule —
selection wrapping, list continuation, marker backspace — is unit-tested
without a display; :mod:`lurkn.ui.note` maps the results onto a
``Gtk.TextBuffer``.

Offsets are Python string offsets. GTK's ``TextBuffer`` counts characters the
same way, so no conversion is needed at the boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BOLD = "**"
ITALIC = "*"

_BULLET = "- "
_TASK = "[ ] "
# A list marker at the start of a line, after optional indentation. Only the
# forms in spec §7.3 are recognised; ``*`` bullets would collide with the
# italic shortcut in a plain-text editor.
_MARKER_RE = re.compile(r"(?P<indent>[ \t]*)(?P<marker>- |(?P<number>\d+)\. |\[ \] )")


@dataclass(frozen=True)
class TextEdit:
    """A replacement buffer plus the selection/caret to restore afterwards.

    ``start == end`` means a collapsed caret. The GTK layer calls
    ``select_range`` for a real selection and ``place_cursor`` otherwise.
    """

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ListMarker:
    """One recognised list marker on the current line."""

    kind: str  # "bullet", "ordered" or "task"
    line_start: int
    marker_start: int  # first marker character (after indentation)
    content_start: int  # first character of the item text
    indent: str
    number: int | None = None
    number_width: int = 0


def wrap_selection(
    text: str, start: int, end: int, marker: str
) -> TextEdit:
    """Wrap the selection in *marker*, or insert an empty pair at the caret."""
    start, end = _bounds(text, start, end)
    if start == end:
        return TextEdit(
            text=text[:start] + marker + marker + text[start:],
            start=start + len(marker),
            end=start + len(marker),
        )
    wrapped = text[:start] + marker + text[start:end] + marker + text[end:]
    return TextEdit(
        text=wrapped,
        start=start + len(marker),
        end=end + len(marker),
    )


def continue_list(text: str, cursor: int) -> TextEdit | None:
    """Handle Enter inside a list, or return None for ordinary newlines.

    A non-empty item continues with the same kind of marker on the next line;
    an ordered marker increments its number. Pressing Enter on an empty item
    removes the marker and leaves a clean line, which is how a user exits the
    list without deleting text.
    """
    marker = marker_at(text, cursor)
    if marker is None or cursor < marker.content_start:
        return None

    line_end = text.find("\n", cursor)
    if line_end == -1:
        line_end = len(text)
    item = text[marker.content_start : line_end]
    if not item.strip():
        # Empty item: drop the marker (but keep any leading indentation).
        line_end_full = text.find("\n", marker.content_start)
        if line_end_full == -1:
            line_end_full = len(text)
        rest = text[marker.content_start : line_end_full]
        replacement = marker.indent if not rest.strip() else rest.lstrip()
        clean = (
            text[: marker.line_start]
            + replacement
            + text[line_end_full:]
        )
        caret = marker.line_start + len(replacement)
        return TextEdit(text=clean, start=caret, end=caret)

    inserted = "\n" + marker.indent + _next_marker(marker)
    caret = cursor + len(inserted)
    return TextEdit(
        text=text[:cursor] + inserted + text[cursor:],
        start=caret,
        end=caret,
    )


def remove_marker_before_cursor(
    text: str, cursor: int
) -> TextEdit | None:
    """Backspace immediately after a list marker removes the whole marker.

    ``- foo`` with the caret after ``- `` becomes ``foo`` with the caret where
    ``- `` used to start; indentation is preserved.
    """
    marker = marker_at(text, cursor)
    if marker is None or cursor != marker.content_start:
        return None
    return TextEdit(
        text=text[: marker.marker_start] + text[marker.content_start :],
        start=marker.marker_start,
        end=marker.marker_start,
    )


def marker_at(text: str, cursor: int) -> ListMarker | None:
    """The list marker of the line containing *cursor*, if any."""
    cursor = max(0, min(cursor, len(text)))
    line_start = text.rfind("\n", 0, cursor) + 1
    line_end = text.find("\n", cursor)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    match = _MARKER_RE.match(line)
    if match is None:
        return None

    indent = match.group("indent")
    number = match.group("number")
    if number is not None:
        kind = "ordered"
    elif match.group("marker") == _TASK:
        kind = "task"
    else:
        kind = "bullet"
    marker_start = line_start + len(indent)
    return ListMarker(
        kind=kind,
        line_start=line_start,
        marker_start=marker_start,
        content_start=line_start + match.end(),
        indent=indent,
        number=int(number) if number is not None else None,
        number_width=len(number) if number is not None else 0,
    )


def _next_marker(marker: ListMarker) -> str:
    if marker.kind == "ordered":
        number = (marker.number or 1) + 1
        return str(number).zfill(marker.number_width) + ". "
    if marker.kind == "task":
        return _TASK
    return _BULLET


def _bounds(text: str, start: int, end: int) -> tuple[int, int]:
    start = max(0, min(start, len(text)))
    end = max(0, min(end, len(text)))
    return (start, end) if start <= end else (end, start)
