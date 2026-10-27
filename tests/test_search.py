"""Deck search rules (the fan's search box).

Pure Python so the matching rule is specified independently of GTK.
"""

from __future__ import annotations

from conftest import make_note

from lurkn.search import search_notes


def ids(notes) -> list[str]:
    return [note.id for note in notes]


def test_empty_query_returns_every_note_in_manual_deck_order():
    # Order is the array index, never the updated timestamp (spec §5.1).
    oldest = make_note("oldest", "one", updated=900.0)
    newest = make_note("newest", "two", updated=100.0)

    assert ids(search_notes([newest, oldest], "")) == ["newest", "oldest"]


def test_empty_query_on_an_empty_deck_has_no_results():
    assert search_notes([], "") == []


def test_blank_query_returns_every_note_too():
    notes = [make_note("a", "one"), make_note("b", "two")]

    assert ids(search_notes(notes, "   ")) == ["a", "b"]


def test_search_is_case_insensitive():
    note = make_note("note", "Eggs and Bacon")

    assert ids(search_notes([note], "eggs")) == ["note"]
    assert ids(search_notes([note], "EGGS")) == ["note"]
    assert ids(search_notes([note], "EgGs")) == ["note"]


def test_search_matches_a_substring_anywhere_in_the_text():
    note = make_note("groceries", "Groceries\nmilk\neggs\nbread")

    for query in ("egg", "ggs", "milk", "read"):
        assert ids(search_notes([note], query)) == ["groceries"], query

    assert search_notes([note], "butter") == []


def test_search_matches_a_later_line_not_only_the_title():
    note = make_note("retro", "Retro\nWhat went well\nplenty of EGGS everywhere")

    assert ids(search_notes([note], "eggs")) == ["retro"]


def test_filtered_results_keep_manual_order_not_update_order():
    first = make_note("first", "needle one", updated=300.0)
    second = make_note("second", "needle two", updated=100.0)
    skipped = make_note("skipped", "haystack", updated=200.0)

    assert ids(search_notes([first, skipped, second], "needle")) == [
        "first",
        "second",
    ]


def test_duplicate_titles_are_distinct_hits_in_deck_order():
    first = make_note("first", "Same title\none")
    second = make_note("second", "Same title\ntwo")

    assert ids(search_notes([second, first], "same")) == ["second", "first"]


def test_query_is_a_literal_substring_not_a_pattern():
    note = make_note("note", "price is 10$ (net)")

    assert ids(search_notes([note], "10$")) == ["note"]
    assert ids(search_notes([note], "(net)")) == ["note"]
    assert search_notes([note], ".*") == []


def test_search_reads_the_live_note_object():
    note = make_note("note", "Title\nold line")
    assert search_notes([note], "needle") == []

    note.text = "Title\nnew line with needle"

    assert ids(search_notes([note], "needle")) == ["note"]
