"""The Note model: JSON mapping, titles, and array-index ordering."""

from __future__ import annotations

import uuid

from lurkn.notes import Note, find_note, index_of

SPEC_NOTE = {
    "id": "0f0c2f4e-6a1b-4c3d-9e8f-1a2b3c4d5e6f",
    "text": "Groceries\nmilk\neggs\nbread",
    "created": 1793025619.33,
    "updated": 1793025900.12,
}


def make_note(note_id: str, text: str, created: float = 1.0, updated: float = 2.0) -> Note:
    return Note(id=note_id, text=text, created=created, updated=updated)


def test_note_maps_to_the_documented_json_shape():
    # Spec §5.1: exactly id/text/created/updated, no order/title/color.
    note = Note.from_dict(SPEC_NOTE)

    assert note.to_dict() == SPEC_NOTE
    assert list(note.to_dict()) == ["id", "text", "created", "updated"]


def test_note_round_trips_through_a_json_dict():
    note = Note.from_dict(SPEC_NOTE)

    assert Note.from_dict(note.to_dict()) == note


def test_title_is_the_first_non_empty_line():
    # Spec §5.4; the 60-character ellipsis rule belongs to ticket 03.
    note = make_note(str(uuid.uuid4()), "\n   \n  Groceries  \nmilk")

    assert note.title() == "Groceries"


def test_title_of_an_empty_note_is_empty():
    assert make_note(str(uuid.uuid4()), " \n\t\n").title() == ""


def test_created_note_gets_uuid4_and_shared_timestamps():
    note = Note.create("hello", now=123.5)

    assert uuid.UUID(note.id).version == 4
    assert note.text == "hello"
    assert note.created == note.updated == 123.5


def test_notes_are_ordered_by_array_index():
    first = make_note("first", "one")
    second = make_note("second", "two")

    assert index_of([first, second], "second") == 1
    assert index_of([second, first], "first") == 1
    assert find_note([first, second], "second") is second
    assert index_of([first, second], "missing") == -1
    assert find_note([first, second], "missing") is None
