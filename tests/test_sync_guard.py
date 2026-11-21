"""The pull-after-push race that lost a user's text.

Sequence that broke: type 49 characters, the debounce pushes an earlier 12,
the server acknowledges, the immediate pull returns those 12 as the truth,
`merge_pulled` wrote them over the note, and collapsing the deck saved 12.

These tests pin the guard: a protected note is never overwritten, however
authoritative the server looks.
"""

from __future__ import annotations

from lurkn.merge import merge_pulled
from lurkn.notes import Note


def note(note_id: str, text: str, *, version: str | None = "v1") -> Note:
    return Note(
        id=note_id, text=text, created=1.0, updated=1.0, server_updated_at=version
    )


def pull(note_id: str, text: str, *, version: str = "v2") -> dict:
    return {
        "id": note_id,
        "text": text,
        "position": 0,
        "created": 1.0,
        "server_updated_at": version,
        "deleted": False,
    }


def test_a_protected_note_keeps_what_the_user_typed() -> None:
    editor_text = "Проверка замени полный текст этой заметки"
    deck = [note("a", editor_text, version="v1")]

    merged, changed = merge_pulled(
        deck, [pull("a", "Проверка зам", version="v2")], protected={"a"}
    )

    assert merged[0].text == editor_text
    assert changed is False


def test_a_protected_note_is_not_resurrected_or_deleted() -> None:
    deck = [note("a", "still typing")]

    merged, changed = merge_pulled(
        deck,
        [pull("a", "", version="v2") | {"deleted": True}],
        protected={"a"},
    )

    assert [n.id for n in merged] == ["a"]
    assert changed is False


def test_other_notes_in_the_same_pull_still_merge() -> None:
    deck = [note("a", "mine"), note("b", "old")]

    merged, changed = merge_pulled(
        deck,
        [pull("a", "server wins?"), pull("b", "from phone")],
        protected={"a"},
    )

    assert changed is True
    assert merged[0].text == "mine"
    assert merged[1].text == "from phone"


def test_without_protection_the_merge_still_works_as_before() -> None:
    deck = [note("a", "old")]

    merged, changed = merge_pulled(deck, [pull("a", "new")])

    assert changed is True
    assert merged[0].text == "new"


def test_the_exact_reported_scenario_keeps_the_typed_text() -> None:
    """Type a note, sync pushes an older save, the pull must not revert it.

    Reproduced from the user's report: the text survived with sync off and
    was truncated with it on.
    """
    typed = "Проверка замени полный текст этой заметки"
    deck = [note("a", typed, version="v1")]

    merged, changed = merge_pulled(
        deck, [pull("a", "Проверка зам", version="v2")], protected={"a"}
    )

    assert merged[0].text == typed
    assert changed is False
