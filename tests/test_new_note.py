"""New-note persistence rules (spec §5.2, §5.4).

Creation is in memory: nothing is written until the 400 ms debounce, a switch,
close or shutdown. A crash right after ``lurknotes new`` must not leave a
permanent empty note in ``notes.json``.
"""

from __future__ import annotations

from conftest import make_app, make_note


def test_creating_a_note_does_not_write_the_file() -> None:
    existing = make_note("existing", "old")
    app = make_app([existing])

    app.new_note()

    assert len(app.notes) == 2
    assert app.notes[0] is not existing
    assert app.store.saved == []


def test_typing_then_flushing_saves_the_new_top_note() -> None:
    existing = make_note("existing", "old")
    app = make_app([existing])
    app.new_note()
    note_id = app.current_id
    app.panel.note._text = "new text"

    app._flush_current()

    assert app.store.saved[-1] == [note_id, "existing"]


def test_closing_an_untouched_new_note_discards_it_and_saves_the_deck() -> None:
    existing = make_note("existing", "old")
    app = make_app([existing])
    app.new_note()

    app.close_note()

    assert [note.id for note in app.notes] == ["existing"]
    assert app.store.saved[-1] == ["existing"]


def test_switching_away_from_an_untouched_new_note_discards_it() -> None:
    existing = make_note("existing", "old")
    app = make_app([existing])
    app.new_note()

    app.open_note("existing")

    assert [note.id for note in app.notes] == ["existing"]
    assert app.store.saved[-1] == ["existing"]
