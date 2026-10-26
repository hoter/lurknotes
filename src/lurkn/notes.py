"""Notes: the domain object and order-preserving list helpers.

Pure Python on purpose. The store serializes :class:`Note` to the JSON shape
from spec §5.1; the UI reads titles and text from the same object. The 60-char
title ellipsis and preview rules arrive with ticket 03.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Iterable


@dataclass
class Note:
    """One note. Position in the deck is the note's index in the list."""

    id: str
    text: str
    created: float
    updated: float

    @classmethod
    def create(
        cls,
        text: str = "",
        *,
        now: float | None = None,
        note_id: str | None = None,
    ) -> "Note":
        timestamp = time.time() if now is None else now
        return cls(
            id=note_id or str(uuid.uuid4()),
            text=text,
            created=timestamp,
            updated=timestamp,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        """Build a Note from the spec §5.1 shape, rejecting unusable values."""
        if not isinstance(data, dict):
            raise ValueError("note must be an object")
        note_id = data.get("id")
        text = data.get("text")
        created = data.get("created")
        updated = data.get("updated")
        if not isinstance(note_id, str) or not note_id:
            raise ValueError("note id must be a non-empty string")
        if not isinstance(text, str):
            raise ValueError("note text must be a string")
        timestamps = (created, updated)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in timestamps
        ):
            raise ValueError("note timestamps must be numbers")
        return cls(
            id=note_id,
            text=text,
            created=float(created),
            updated=float(updated),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "created": self.created,
            "updated": self.updated,
        }

    def title(self) -> str:
        """The first non-empty line; the tab label.

        Truncation to 60 characters with an ellipsis is ticket 03's rule, not
        applied here yet.
        """
        for line in self.text.splitlines():
            if line.strip():
                return line.strip()
        return ""


def index_of(notes: Iterable[Note], note_id: str) -> int:
    """Array index of *note_id*, or -1. Order is the list, not a field."""
    for index, note in enumerate(notes):
        if note.id == note_id:
            return index
    return -1


def find_note(notes: Iterable[Note], note_id: str) -> Note | None:
    for note in notes:
        if note.id == note_id:
            return note
    return None
