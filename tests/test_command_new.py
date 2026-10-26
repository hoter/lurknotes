"""`new` reuses an untouched session note instead of stacking empties (§9.3)."""

from __future__ import annotations

from lurkn.notes import Note, session_untouched_note


def note(note_id: str, text: str = "", *, created: float = 10.0, updated: float = 10.0):
    return Note(id=note_id, text=text, created=created, updated=updated)


def test_a_session_created_untouched_note_is_the_new_target() -> None:
    current = note("current")
    notes = [note("older"), current]

    assert session_untouched_note(notes, current.id, {current.id}) is current


def test_a_loaded_empty_note_is_not_reused() -> None:
    # Timestamps look untouched, but this process did not create it (§5.4).
    loaded = note("loaded")

    assert session_untouched_note([loaded], loaded.id, set()) is None


def test_a_typed_note_is_not_reused() -> None:
    typed = note("typed", "hello", created=10.0, updated=11.0)

    assert session_untouched_note([typed], typed.id, {typed.id}) is None


def test_an_edited_but_still_empty_note_is_not_reused() -> None:
    edited = note("edited", "", created=10.0, updated=11.0)

    assert session_untouched_note([edited], edited.id, {edited.id}) is None


def test_no_open_note_has_nothing_to_reuse() -> None:
    current = note("current")
    assert session_untouched_note([current], None, {current.id}) is None
    assert session_untouched_note([current], "missing", {current.id}) is None
