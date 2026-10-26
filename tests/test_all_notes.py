"""All Notes: full-text search, snippets, manual order, dates, live refresh.

The window itself is exercised by ``scripts/smoke_all_notes.py``; these tests
cover the pure view model so the search rules are specified independently of
GTK.
"""

from __future__ import annotations

import time

from lurkn.all_notes import (
    SNIPPET_LIMIT,
    AllNotesModel,
    format_updated,
    highlight_markup,
    search_notes,
)
from lurkn.events import DeckChanged
from lurkn.notes import Note


def make_note(
    note_id: str,
    text: str,
    *,
    created: float = 1.0,
    updated: float = 2.0,
) -> Note:
    return Note(id=note_id, text=text, created=created, updated=updated)


def ids(hits) -> list[str]:
    return [hit.note.id for hit in hits]


def test_empty_query_shows_every_note_in_manual_deck_order():
    # Order is the array index, never the updated timestamp (spec §5.1, §6.4).
    oldest = make_note("oldest", "one", updated=900.0)
    newest = make_note("newest", "two", updated=100.0)

    hits = search_notes([newest, oldest], "")

    assert ids(hits) == ["newest", "oldest"]


def test_empty_query_on_an_empty_deck_has_no_results():
    assert search_notes([], "") == []


def test_blank_query_shows_all_notes_too():
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

    hit = search_notes([note], "eggs")[0]

    assert hit.snippet == "plenty of EGGS everywhere"
    assert hit.highlight == (10, 14)


def test_filtered_results_keep_manual_order_not_update_order():
    first = make_note("first", "needle one", updated=300.0)
    second = make_note("second", "needle two", updated=100.0)
    skipped = make_note("skipped", "haystack", updated=200.0)

    hits = search_notes([first, skipped, second], "needle")

    assert ids(hits) == ["first", "second"]


def test_duplicate_titles_are_distinct_hits_in_deck_order():
    first = make_note("first", "Same title\none")
    second = make_note("second", "Same title\ntwo")

    hits = search_notes([second, first], "same")

    assert ids(hits) == ["second", "first"]
    assert [hit.note.title() for hit in hits] == ["Same title", "Same title"]


def test_snippet_without_a_query_is_the_first_body_line():
    note = make_note("groceries", "Groceries\nmilk\neggs")

    hit = search_notes([note], "")[0]

    assert hit.snippet == "milk"
    assert hit.highlight is None


def test_snippet_of_a_title_only_note_is_empty():
    note = make_note("title-only", "Groceries")

    hit = search_notes([note], "")[0]

    assert hit.snippet == ""
    assert hit.highlight is None


def test_snippet_is_the_matched_line_with_surrounding_whitespace_trimmed():
    note = make_note("note", "Title\n   find me here   \nafter")

    hit = search_notes([note], "find")[0]

    assert hit.snippet == "find me here"
    assert hit.highlight == (0, 4)


def test_snippet_for_a_title_match_is_the_title_line():
    note = make_note("groceries", "Groceries\nmilk")

    hit = search_notes([note], "groc")[0]

    assert hit.snippet == "Groceries"
    assert hit.highlight == (0, 4)


def test_long_line_snippet_keeps_the_match_visible_between_ellipses():
    line = "x" * 200 + "needle" + "y" * 200
    note = make_note("long", "Title\n" + line)

    hit = search_notes([note], "needle")[0]

    assert hit.snippet.startswith("…")
    assert hit.snippet.endswith("…")
    assert len(hit.snippet) <= SNIPPET_LIMIT + 2
    start, end = hit.highlight
    assert hit.snippet[start:end] == "needle"


def test_long_line_snippet_at_the_start_has_no_leading_ellipsis():
    line = "needle" + "y" * 200
    note = make_note("long", "Title\n" + line)

    hit = search_notes([note], "needle")[0]

    assert not hit.snippet.startswith("…")
    assert hit.snippet.endswith("…")
    start, end = hit.highlight
    assert hit.snippet[start:end] == "needle"


def test_markup_bolds_the_match_and_escapes_pango_markup():
    note = make_note("note", "<b>Eggs</b> & milk")

    hit = search_notes([note], "eggs")[0]

    assert hit.snippet == "<b>Eggs</b> & milk"
    assert highlight_markup(hit.snippet, hit.highlight) == (
        "&lt;b&gt;<b>Eggs</b>&lt;/b&gt; &amp; milk"
    )


def test_markup_without_a_highlight_escapes_only():
    assert highlight_markup("a < b & c", None) == "a &lt; b &amp; c"


def test_updated_date_is_local_time(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        assert format_updated(1793025900.12) == "2026-10-26 14:45"
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_model_refresh_picks_up_edits_made_after_it_opened():
    note = make_note("note", "Title\nold line")
    model = AllNotesModel(lambda: [note])
    assert model.refresh()[0].snippet == "old line"

    note.text = "Title\nnew line with needle"
    note.updated = 200.0

    hits = model.refresh()

    assert hits[0].snippet == "new line with needle"
    assert hits[0].note.updated == 200.0


def test_deck_changed_refreshes_subscribed_views_immediately():
    editor = make_note("editor", "Title\nold line")
    model = AllNotesModel(lambda: [editor])
    events = DeckChanged()
    events.subscribe(model.refresh)
    model.set_query("needle")
    assert model.hits == []

    editor.text = "Title\ntyped needle in the panel"
    events.notify()

    assert ids(model.hits) == ["editor"]
    assert model.hits[0].snippet == "typed needle in the panel"


def test_unsubscribed_views_stop_refreshing():
    note = make_note("note", "Title\nold")
    model = AllNotesModel(lambda: [note])
    events = DeckChanged()
    events.subscribe(model.refresh)
    model.set_query("needle")
    events.unsubscribe(model.refresh)

    note.text = "Title\nneedle after unsubscribe"
    events.notify()

    assert model.hits == []


def test_refresh_keeps_the_current_query():
    note = make_note("note", "Title\nneedle one")
    model = AllNotesModel(lambda: [note])
    model.set_query("NEEDLE")
    assert ids(model.hits) == ["note"]

    note.text = "Title\nneedle two"

    assert ids(model.refresh()) == ["note"]
    assert model.query == "NEEDLE"
