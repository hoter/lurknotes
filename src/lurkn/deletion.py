"""Deleting a note has to reach the server, and undo has to take it back.

The rule the deck follows: a deletion is announced only when the undo window
closes. Until then the note may come back, and a tombstone the user then
cancels would have deleted it on every other machine for nothing.

So the queue is touched at three points:

* delete -> remember the note as "pending removal", no tombstone yet;
* undo -> forget it, nothing travels;
* the 10 s timer expiring -> queue the tombstone.

A note the server never saw needs no tombstone at all: there is nothing to
remove on the other side.
"""

from __future__ import annotations

from dataclasses import dataclass

from .notes import Note


@dataclass(frozen=True)
class PendingRemoval:
    """A deleted note whose undo window is still open."""

    note: Note
    # The version the server last confirmed, i.e. the base of the tombstone.
    base: str | None


def should_announce(removal: PendingRemoval) -> bool:
    """Only a note the server knows about needs a tombstone."""
    return removal.base is not None


def tombstone_payload(removal: PendingRemoval) -> dict:
    """The wire shape of a deletion, matching the push contract."""
    return {
        "id": removal.note.id,
        "text": "",
        "position": 0,
        "created": 0.0,
        "base": removal.base,
        "deleted": True,
    }
