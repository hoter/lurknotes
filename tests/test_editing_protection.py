"""`_editing_protection` decides whether the merge may touch the open note.

Getting this wrong is silent: an empty set means "no protection", the pull
overwrites the editor, and the text is gone at the next save. So each branch
is pinned here rather than left to the integration path.
"""

from __future__ import annotations

import pytest

from lurkn.app import LurkNotesApp
from lurkn.notes import Note


class FakeEditor:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class FakePanel:
    def __init__(self, text: str) -> None:
        self.note = FakeEditor(text)


def make_app(*, note_text: str, buffer_text: str, current: str | None) -> LurkNotesApp:
    app = LurkNotesApp.__new__(LurkNotesApp)
    app.notes = [
        Note(id="a", text=note_text, created=1.0, updated=1.0, server_updated_at="v1"),
        Note(id="b", text="other", created=1.0, updated=1.0),
    ]
    app.current_id = current
    app.panel = FakePanel(buffer_text)
    return app


def test_an_open_note_with_unsaved_typing_is_protected() -> None:
    app = make_app(note_text="Проверка зам", buffer_text="Проверка замени полный", current="a")

    assert app._editing_protection() == {"a"}


def test_an_open_note_without_changes_is_not_protected() -> None:
    # Nothing to lose: letting the pull through keeps the deck in step.
    app = make_app(note_text="same", buffer_text="same", current="a")

    assert app._editing_protection() == set()


def test_no_open_note_protects_nothing() -> None:
    app = make_app(note_text="x", buffer_text="y", current=None)

    assert app._editing_protection() == set()


def test_a_missing_panel_protects_nothing_instead_of_crashing() -> None:
    app = make_app(note_text="x", buffer_text="y", current="a")
    app.panel = None

    assert app._editing_protection() == set()


def test_a_panel_without_an_editor_protects_nothing() -> None:
    app = make_app(note_text="x", buffer_text="y", current="a")
    app.panel = object()

    assert app._editing_protection() == set()


def test_an_open_note_that_left_the_deck_protects_nothing() -> None:
    app = make_app(note_text="x", buffer_text="y", current="gone")

    assert app._editing_protection() == set()
