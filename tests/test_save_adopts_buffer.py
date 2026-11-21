"""A save must take the editor's text, not the note's last snapshot.

The bug: the 400 ms debounce fired mid-sentence, `_save_notes` wrote the note
as it was when the debounce started, and with sync on that prefix went to the
server. A `kill -USR1` dump caught it: the buffer held 74 characters, the note
5, and the server had the 5.

`_save_notes` now adopts the buffer first, so every save path — debounce,
collapse, shutdown, sync — writes what the user actually typed.
"""

from __future__ import annotations

import time
from pathlib import Path

from lurkn.app import LurkNotesApp
from lurkn.notes import Note
from lurkn.store import Store


class FakeEditor:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class FakePanel:
    def __init__(self, text: str) -> None:
        self.note = FakeEditor(text)

    def refresh_notes(self, *_args) -> None:
        pass

    def show_save_failed(self, *_args) -> None:
        pass


class NoopRetrier:
    def failed(self) -> None:
        pass

    def succeeded(self) -> None:
        pass


def make_app(tmp_path: Path, *, note_text: str, buffer_text: str) -> LurkNotesApp:
    note = Note.create(note_text, now=1.0)
    store = Store(tmp_path / "notes.json")
    store.save([note])

    app = LurkNotesApp.__new__(LurkNotesApp)
    app.notes = [note]
    app.store = store
    app.current_id = note.id
    app.panel = FakePanel(buffer_text)
    app.session_ids = set()
    app.unsaved = False
    app.read_only = False
    app.overwrite_blocked = False
    app.save_source = 0
    app._retrier = NoopRetrier()
    app._hooks = type(
        "H", (), {"schedule_dump": lambda self, delay=0: None}
    )()
    app.deck_changed = lambda: None
    app._sync_controller = None
    app._sync_config = None
    app._sync_row_visible = False
    return app


def test_saving_takes_the_editor_text_not_the_stale_note(tmp_path: Path) -> None:
    typed = "Проверка удаления текста в заметки\n\nЭто вторая строка\n\nИ еще одна!\n\nКонец!"
    app = make_app(tmp_path, note_text="Прове", buffer_text=typed)

    assert app._save_notes() is True

    assert Store(tmp_path / "notes.json").load().notes[0].text == typed


def test_the_queue_gets_the_full_text_too(tmp_path: Path) -> None:
    # The prefix reached the server this way: the queue was filled from
    # note.text after a save that had not adopted the buffer.
    typed = "Проверка удаления текста в заметке"
    app = make_app(tmp_path, note_text="Прове", buffer_text=typed)

    captured = []

    class FakeSyncer:
        def enqueue_note(self, **kwargs):
            captured.append(kwargs)

    class FakeController:
        syncer = FakeSyncer()

        def sync_now(self):
            pass

    app._sync_controller = FakeController()
    app._sync_enabled = lambda: True

    app._save_notes()

    assert captured and captured[0]["text"] == typed


def test_an_unchanged_buffer_leaves_the_note_alone(tmp_path: Path) -> None:
    app = make_app(tmp_path, note_text="same", buffer_text="same")
    before = app.notes[0].updated

    assert app._adopt_buffer_text() is False
    assert app.notes[0].updated == before


def test_no_open_note_is_not_an_error(tmp_path: Path) -> None:
    app = make_app(tmp_path, note_text="x", buffer_text="y")
    app.current_id = None

    assert app._adopt_buffer_text() is False
    assert app.notes[0].text == "x"


def test_adopting_marks_the_note_dirty_for_sync(tmp_path: Path) -> None:
    app = make_app(tmp_path, note_text="old", buffer_text="new text")

    app._adopt_buffer_text()

    note = app.notes[0]
    assert note.text == "new text"
    assert note.updated >= 1.0
    assert time.time() - note.updated < 5
