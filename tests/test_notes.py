"""The Note model: JSON mapping, titles, and array-index ordering."""

from __future__ import annotations

import json
import uuid

from lurkn.notes import (
    Note,
    add_at_top,
    cycle_id,
    discard_if_untouched,
    find_note,
    index_of,
)
from lurkn.store import Store

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
    # Spec §5.4: the first non-empty line, whitespace-trimmed.
    note = make_note(str(uuid.uuid4()), "\n   \n  Groceries  \nmilk")

    assert note.title() == "Groceries"


def test_title_of_an_empty_note_is_untitled():
    assert make_note(str(uuid.uuid4()), " \n\t\n").title() == "Untitled"


def test_title_of_a_60_character_line_is_kept_whole():
    title = "x" * 60

    assert make_note(str(uuid.uuid4()), title).title() == title


def test_title_longer_than_60_characters_ends_with_an_ellipsis_at_60():
    # Spec §5.4: 60 characters *including* the ellipsis, not 60 plus it.
    note = make_note(str(uuid.uuid4()), "a" * 59 + "bcdef")

    title = note.title()

    assert len(title) == 60
    assert title == "a" * 59 + "…"


def test_title_is_trimmed_before_truncation():
    note = make_note(str(uuid.uuid4()), "   " + "b" * 70 + "   ")

    title = note.title()

    assert len(title) == 60
    assert title == "b" * 59 + "…"


def test_preview_of_an_empty_note_is_empty():
    assert make_note(str(uuid.uuid4()), "").preview() == []


def test_preview_of_a_title_only_note_is_empty():
    assert make_note(str(uuid.uuid4()), "Groceries").preview() == []


def test_preview_has_the_lines_after_the_title():
    note = make_note(str(uuid.uuid4()), "Groceries\nmilk\neggs")

    assert note.preview() == ["milk", "eggs"]


def test_preview_shows_at_most_six_lines_after_the_title():
    note = make_note(
        str(uuid.uuid4()),
        "Groceries\n" + "\n".join(f"line {number}" for number in range(1, 7)),
    )

    assert note.preview() == [f"line {number}" for number in range(1, 7)]


def test_preview_truncates_a_seventh_line():
    note = make_note(
        str(uuid.uuid4()),
        "Groceries\n" + "\n".join(f"line {number}" for number in range(1, 8)),
    )

    assert note.preview() == [f"line {number}" for number in range(1, 7)]


def test_preview_skips_blank_lines_before_the_body():
    note = make_note(str(uuid.uuid4()), "\nGroceries\n\nmilk\neggs\n")

    assert note.preview() == ["milk", "eggs"]


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


def test_duplicate_titles_are_distinct_notes_identified_by_id():
    first = make_note("one", "Same title")
    second = make_note("two", "Same title")
    notes = [first, second]

    assert first.title() == second.title() == "Same title"
    assert find_note(notes, "one") is first
    assert find_note(notes, "two") is second

    add_at_top(notes, make_note("three", "Same title"))

    assert [note.id for note in notes] == ["three", "one", "two"]


def test_a_note_created_now_is_untouched():
    note = Note.create(now=123.0)

    assert note.is_untouched() is True


def test_a_note_with_text_is_not_untouched():
    note = make_note("edited", "hello", created=1.0, updated=1.0)

    assert note.is_untouched() is False


def test_a_note_edited_after_creation_is_not_untouched():
    note = make_note("edited", "", created=1.0, updated=2.0)

    assert note.is_untouched() is False


def test_closing_an_untouched_note_created_this_session_discards_it():
    note = Note.create(now=123.0)
    notes = [note]

    assert discard_if_untouched(notes, note.id, {note.id}) is note
    assert notes == []


def test_closing_an_empty_note_loaded_from_the_file_keeps_it():
    loaded = make_note("loaded", "", created=1.0, updated=1.0)
    notes = [loaded]

    assert discard_if_untouched(notes, loaded.id, set()) is None
    assert notes == [loaded]


def test_switching_away_from_an_untouched_note_discards_only_that_note():
    untouched = Note.create(now=123.0)
    kept = make_note("kept", "still here", created=1.0, updated=1.0)
    notes = [untouched, kept]

    discard_if_untouched(notes, untouched.id, {untouched.id})

    assert notes == [kept]


def test_closing_the_last_untouched_note_leaves_a_saved_empty_deck(tmp_path):
    store = Store(tmp_path / "notes.json")
    store.save([make_note("loaded", "something")])
    untouched = Note.create(now=123.0)
    notes = [untouched]
    store.save(notes)

    discard_if_untouched(notes, untouched.id, {untouched.id})
    store.save(notes)

    assert notes == []
    assert store.load().notes == []
    assert json.loads((tmp_path / "notes.json").read_text(encoding="utf-8")) == {
        "version": 1,
        "notes": [],
    }


def test_add_at_top_writes_the_new_order_through_the_store(tmp_path):
    # Order is the array index (spec §5.1), so "top" must survive a reload.
    store = Store(tmp_path / "notes.json")
    old = make_note("old", "older")
    fresh = Note.create(now=10.0, note_id="fresh")
    notes = [old]

    add_at_top(notes, fresh)
    store.save(notes)

    assert [note.id for note in store.load().notes] == ["fresh", "old"]


def test_cycle_wraps_forward_and_backward():
    notes = [make_note("a", "a"), make_note("b", "b"), make_note("c", "c")]

    assert cycle_id(notes, "c", 1) == "a"
    assert cycle_id(notes, "a", -1) == "c"
    assert cycle_id(notes, "a", 1) == "b"
    assert cycle_id(notes, "b", -1) == "a"


def test_cycle_from_no_open_note_opens_either_end():
    notes = [make_note("a", "a"), make_note("b", "b")]

    assert cycle_id(notes, None, 1) == "a"
    assert cycle_id(notes, None, -1) == "b"
    assert cycle_id([], None, 1) is None
