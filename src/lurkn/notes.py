"""Notes: the domain object and order-preserving list helpers.

Pure Python on purpose. The store serializes :class:`Note` to the JSON shape
from spec §5.1; the UI reads titles, previews and text from the same object.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Iterable

from . import strings

TITLE_LIMIT = 60
PREVIEW_LINES = 6


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
        """The first non-empty line, trimmed and capped at 60 characters.

        Spec §5.4: the cap counts the ellipsis as one of the 60 characters.
        An empty or whitespace-only note is shown as "Untitled"; duplicate
        titles are fine because the id, never the title, is the identity.
        """
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped:
                if len(stripped) > TITLE_LIMIT:
                    return stripped[: TITLE_LIMIT - 1] + "…"
                return stripped
        return strings.UNTITLED

    def preview(self) -> list[str]:
        """Up to six body lines for a read-only peek (spec §5.4).

        The title line is omitted. Blank lines at the edges of the body are
        dropped so a peek never starts with empty rows; blank lines inside the
        body are kept, and anything after the sixth line is not shown.
        """
        lines = self.text.splitlines()
        title_index = next(
            (index for index, line in enumerate(lines) if line.strip()), None
        )
        if title_index is None:
            return []
        body = lines[title_index + 1 :]
        start = 0
        end = len(body)
        while start < end and not body[start].strip():
            start += 1
        while end > start and not body[end - 1].strip():
            end -= 1
        return body[start:end][:PREVIEW_LINES]

    def is_untouched(self) -> bool:
        """Spec §5.4: no text and never edited since creation.

        The caller must also check that the note was created by this process
        session; timestamps alone cannot tell a loaded empty note apart.
        """
        return self.text == "" and self.created == self.updated


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


def add_at_top(notes: list[Note], note: Note) -> None:
    """Insert *note* at index 0; the array is the order (spec §5.1)."""
    notes.insert(0, note)


def session_untouched_note(
    notes: list[Note], current_id: str | None, session_ids: set[str]
) -> Note | None:
    """The open note if a repeated ``new`` should reuse it (spec §9.3).

    A note qualifies only when it is current, untouched *and* created by this
    session: a loaded empty note has untouched-looking timestamps but deserves
    to be left alone, not reused as the target of a hotkey (spec §5.4).
    """
    if current_id is None:
        return None
    note = find_note(notes, current_id)
    if note is None or note.id not in session_ids or not note.is_untouched():
        return None
    return note


def discard_if_untouched(
    notes: list[Note], note_id: str, session_ids: set[str]
) -> Note | None:
    """Remove the note if it is a session-created untouched note (spec §5.4).

    ``session_ids`` is what keeps a loaded empty note alive: its timestamps
    look untouched, but this process did not create it. Returns the removed
    note, or None when the note must stay.
    """
    note = find_note(notes, note_id)
    if note is None or note.id not in session_ids or not note.is_untouched():
        return None
    notes.remove(note)
    return note


def discard_all_untouched(notes: list[Note], session_ids: set[str]) -> list[Note]:
    """Remove every untouched note this session created; return the removed.

    Shutdown uses this instead of :func:`discard_if_untouched` so no session
    note can slip out of the process still untouched, whatever the deck state
    was. Loaded empty notes are not in ``session_ids`` and stay.
    """
    removed = [
        note for note in notes if note.id in session_ids and note.is_untouched()
    ]
    for note in removed:
        notes.remove(note)
    return removed


def cycle_id(notes: list[Note], current_id: str | None, step: int) -> str | None:
    """The id of the note *step* places away, wrapping at both ends.

    With no note open, forward starts at the first note and backward at the
    last. An empty deck has nothing to cycle to.
    """
    if not notes:
        return None
    if current_id is None:
        return notes[0].id if step >= 0 else notes[-1].id
    index = index_of(notes, current_id)
    if index == -1:
        return notes[0].id if step >= 0 else notes[-1].id
    return notes[(index + step) % len(notes)].id
