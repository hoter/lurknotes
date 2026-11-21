"""Merging a pull into the deck (sync spec §5).

Two rules the merge must never break: a pull never overwrites a local edit the
server has not seen, and a tombstone never deletes a note with unsent changes.
"""

from __future__ import annotations

from lurkn.merge import assign_positions, merge_pulled, sort_by_position
from lurkn.notes import Note


def local(note_id: str, text: str = "text", **kwargs) -> Note:
    base = Note(id=note_id, text=text, created=1.0, updated=1.0)
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


def wire(note_id: str, text: str = "text", *, version: str = "v1", **kwargs) -> dict:
    payload = {
        "id": note_id,
        "text": text,
        "position": 0,
        "created": 1.0,
        "server_updated_at": version,
        "deleted": False,
    }
    payload.update(kwargs)
    return payload


def test_a_new_note_from_another_machine_is_created() -> None:
    deck, changed = merge_pulled([], [wire("a", "from laptop")], now=5.0)

    assert changed is True
    assert [note.id for note in deck] == ["a"]
    assert deck[0].text == "from laptop"
    assert deck[0].server_updated_at == "v1"
    assert deck[0].synced is True


def test_a_clean_note_takes_the_server_text_and_version() -> None:
    deck, changed = merge_pulled(
        [local("a", "old", server_updated_at="v1")], [wire("a", "new", version="v2")]
    )

    assert changed is True
    assert deck[0].text == "new"
    assert deck[0].server_updated_at == "v2"


def test_an_identical_pull_is_a_no_op() -> None:
    deck, changed = merge_pulled(
        [local("a", "same", server_updated_at="v1")], [wire("a", "same", version="v1")]
    )

    assert changed is False


def test_a_locally_edited_note_is_not_overwritten_by_a_pull() -> None:
    deck, changed = merge_pulled(
        [local("a", "mine, unsent", synced=False)],
        [wire("a", "theirs", version="v9")],
    )

    assert changed is False
    assert deck[0].text == "mine, unsent"


def test_a_tombstone_removes_a_clean_note() -> None:
    deck, changed = merge_pulled(
        [local("a"), local("b")], [wire("a", "", deleted=True)]
    )

    assert changed is True
    assert [note.id for note in deck] == ["b"]


def test_a_tombstone_keeps_a_note_with_unsent_edits() -> None:
    deck, changed = merge_pulled(
        [local("a", synced=False)], [wire("a", "", deleted=True)]
    )

    assert changed is False
    assert [note.id for note in deck] == ["a"]


def test_a_tombstone_for_an_unknown_note_is_ignored() -> None:
    deck, changed = merge_pulled([local("a")], [wire("gone", "", deleted=True)])

    assert changed is False
    assert [note.id for note in deck] == ["a"]


def test_position_from_the_server_is_applied() -> None:
    deck, _changed = merge_pulled(
        [local("a", server_updated_at="v1")], [wire("a", "t", version="v2", position=7)]
    )

    assert deck[0].position == 7


def test_sort_by_position_keeps_unpositioned_notes_last_in_array_order() -> None:
    notes = [local("c", position=None), local("a", position=2), local("b", position=0)]

    ordered = sort_by_position(notes)

    assert [note.id for note in ordered] == ["b", "a", "c"]


def test_assign_positions_writes_the_array_index() -> None:
    notes = [local("a"), local("b"), local("c")]

    assign_positions(notes)

    assert [note.position for note in notes] == [0, 1, 2]
