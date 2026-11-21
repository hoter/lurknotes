"""Applying a push response to the deck (sync spec §6.2).

This is the regression that would silently lose edits: the server returns the
new version once, and if it is not stored the next push sends a stale base and
is refused.
"""

from __future__ import annotations

from lurkn.notes import Note
from lurkn.syncapply import apply_applied, apply_rejected

V1 = "2026-11-21T09:00:00.000001Z"
V2 = "2026-11-21T09:05:00.000002Z"


def note(note_id: str = "a", **kwargs) -> Note:
    base = Note(id=note_id, text="t", created=1.0, updated=1.0)
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


def test_the_new_version_from_the_push_is_stored() -> None:
    deck = [note(server_updated_at=None, synced=False)]

    changed = apply_applied(deck, [{"id": "a", "server_updated_at": V1}])

    assert changed is True
    assert deck[0].server_updated_at == V1
    assert deck[0].synced is True


def test_a_second_push_therefore_sends_the_fresh_base() -> None:
    deck = [note(server_updated_at=None, synced=False)]
    apply_applied(deck, [{"id": "a", "server_updated_at": V1}])

    deck[0].text = "edited again"
    deck[0].synced = False
    # The base for the next push is the version the server just confirmed.
    assert deck[0].server_updated_at == V1


def test_an_entry_for_a_note_that_left_the_deck_is_ignored() -> None:
    deck = [note("a")]

    changed = apply_applied(deck, [{"id": "gone", "server_updated_at": V2}])

    assert changed is False


def test_a_deletion_the_server_accepted_does_not_keep_the_note_dirty() -> None:
    deck = [note("a", synced=False)]

    apply_rejected(deck, [{"id": "a", "reason": "stale"}])

    assert deck[0].synced is True


def test_applying_the_same_versions_twice_is_a_no_op() -> None:
    deck = [note(server_updated_at=V1)]
    apply_applied(deck, [{"id": "a", "server_updated_at": V1}])

    assert apply_applied(deck, [{"id": "a", "server_updated_at": V1}]) is False
