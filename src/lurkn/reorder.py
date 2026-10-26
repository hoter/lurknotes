"""Drag-reorder math and session state (spec §4.4, §7.2).

Pure Python on purpose: the fan feeds this module the *rendered* vertical spans
of its tabs and the pointer offset from the active ``Gtk.GestureDrag``. Nothing
here needs a display, so the click/drag threshold, the target mapping, clamping
and "released outside" can be tested exactly.

The deck's order is the note array (spec §5.1); a reorder is a single pop and
insert on that list. The app owns the mutation and the save, this module owns
the decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

# Spec §7.2: a release closer than 5 px to the press is a click; 5 px or more
# is a drag. The offset is compared per axis, in logical (GTK) pixels, so a
# small diagonal jitter (4 px on each axis) stays a click.
DRAG_THRESHOLD_PX = 5.0

CLICK = "click"
REORDER = "reorder"
CANCEL = "cancel"


def is_drag(dx: float, dy: float) -> bool:
    """True when a press has moved far enough to be a drag, not a click.

    A click is a release within 5 logical px on **both** axes (the gesture
    model prototyped in PLATFORM §8); crossing the threshold on either axis
    makes it a reorder drag.
    """
    return abs(dx) >= DRAG_THRESHOLD_PX or abs(dy) >= DRAG_THRESHOLD_PX


def target_index(
    pointer_y: float, spans: Sequence[tuple[float, float]]
) -> int | None:
    """The deck index under *pointer_y* given each row's ``(top, bottom)``.

    ``spans`` are in the same logical coordinate space as the pointer and come
    from ``compute_bounds`` of the real widgets, so unequal row heights and a
    scrolled list are handled without a hardcoded row height. Above the first
    row and below the last clamp to 0 and ``len - 1``; inside a gap the nearer
    row wins (ties go to the earlier row).
    """
    if not spans:
        return None
    if pointer_y <= spans[0][0]:
        return 0
    if pointer_y >= spans[-1][1]:
        return len(spans) - 1

    nearest = 0
    nearest_distance = math.inf
    for index, (top, bottom) in enumerate(spans):
        if top <= pointer_y < bottom:
            return index
        distance = top - pointer_y if pointer_y < top else pointer_y - bottom
        if distance < nearest_distance:
            nearest_distance = distance
            nearest = index
    return nearest


@dataclass(frozen=True)
class DragResult:
    """What the release of one tab press means."""

    kind: str
    note_id: str
    source: int
    target: int | None = None


class DragSession:
    """One press on one tab, from ``drag-begin`` to ``drag-end``.

    ``Gtk.GestureDrag`` starts on press with no threshold (PLATFORM §8), so the
    session stays a candidate click until the pointer actually moves 5 px.
    ``finish`` is pure: it decides click/cancel/reorder from the release point
    and the rendered row spans.
    """

    def __init__(self, note_id: str, source_index: int) -> None:
        self.note_id = note_id
        self.source = source_index
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def update(self, dx: float, dy: float) -> bool:
        """Record movement; returns whether the gesture is now a drag."""
        if not self._active and is_drag(dx, dy):
            self._active = True
        return self._active

    def finish(
        self,
        *,
        released_inside: bool,
        released_on_tab: bool,
        pointer_y: float,
        spans: Sequence[tuple[float, float]],
    ) -> DragResult:
        """Classify the release without touching widgets or notes.

        A press that never crossed the threshold is a click only when it is
        released on its own tab (a normal button). An active drag released
        outside the deck is cancelled (spec §7.2); one released inside maps
        the pointer to a target index, which may equal the source row (a
        no-op for the caller to ignore).
        """
        if not self._active:
            kind = CLICK if released_on_tab else CANCEL
            return DragResult(kind, self.note_id, self.source)
        if not released_inside:
            return DragResult(CANCEL, self.note_id, self.source)
        return DragResult(
            REORDER,
            self.note_id,
            self.source,
            target_index(pointer_y, spans),
        )
