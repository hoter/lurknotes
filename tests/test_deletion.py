"""Deleting a note reaches the server only when the undo window closes.

Before this, `enqueue_delete` existed and was never called: a deletion stayed
local, and the next pull resurrected the note from the server.
"""

from __future__ import annotations

from lurkn.deletion import PendingRemoval, should_announce, tombstone_payload
from lurkn.notes import Note


def note(*, version: str | None = "v1") -> Note:
    n = Note(id="a", text="x", created=1.0, updated=1.0)
    n.server_updated_at = version
    return n


def test_a_note_the_server_knows_gets_a_tombstone() -> None:
    removal = PendingRemoval(note=note(version="v1"), base="v1")

    assert should_announce(removal) is True
    payload = tombstone_payload(removal)
    assert payload["deleted"] is True
    assert payload["base"] == "v1"
    assert payload["id"] == "a"


def test_a_never_synced_note_needs_no_tombstone() -> None:
    # Nothing exists on the other side to remove.
    removal = PendingRemoval(note=note(version=None), base=None)

    assert should_announce(removal) is False
