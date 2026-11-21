"""``position`` must follow the deck, not the server's idea of it.

The bug this covers: `assign_positions` existed and was never called, so
every note carried `position: 0`. Sorting by it then fell back to array order,
and the first pull could reorder the deck under the user.
"""

from __future__ import annotations

from lurkn.merge import assign_positions, merge_pulled, sort_by_position
from lurkn.notes import Note


def note(note_id: str, position: int | None = None, *, version: str | None = None) -> Note:
    return Note(
        id=note_id,
        text=note_id,
        created=1.0,
        updated=1.0,
        position=position,
        server_updated_at=version,
    )


def test_renumbering_makes_position_follow_the_array() -> None:
    deck = [note("c"), note("a"), note("b")]

    assign_positions(deck)

    assert [(n.id, n.position) for n in deck] == [("c", 0), ("a", 1), ("b", 2)]


def test_the_deck_order_survives_a_sort_after_renumbering() -> None:
    deck = [note("c"), note("a"), note("b")]
    assign_positions(deck)

    assert [n.id for n in sort_by_position(deck)] == ["c", "a", "b"]


def test_equal_positions_fall_back_to_array_order_instead_of_scrambling() -> None:
    # What the bug looked like: every note at 0.
    deck = [note("b", 0), note("a", 0), note("c", 0)]

    assert [n.id for n in sort_by_position(deck)] == ["b", "a", "c"]


def test_a_pull_that_brings_positions_is_sorted_after_the_merge() -> None:
    local = [note("a", 0, version="v1"), note("b", 1, version="v1")]
    remote = [
        {"id": "a", "text": "a", "position": 1, "server_updated_at": "v2", "deleted": False},
        {"id": "b", "text": "b", "position": 0, "server_updated_at": "v2", "deleted": False},
    ]

    merged, _changed = merge_pulled(local, remote)
    ordered = sort_by_position(merged)
    assign_positions(ordered)

    assert [n.id for n in ordered] == ["b", "a"]
    assert [n.position for n in ordered] == [0, 1]
