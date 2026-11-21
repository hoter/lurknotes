"""The on-demand dump: what the buffer holds versus what was saved.

Written for a bug where typed text vanished with sync on. The dump exists to
answer one question in one shot: at this instant, does the editor contain more
than the note object does?
"""

from __future__ import annotations

import json
from pathlib import Path

from lurkn import sigdump
from lurkn.notes import Note


class FakeEditor:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class FakePanel:
    def __init__(self, text: str) -> None:
        self.note = FakeEditor(text)


class FakeDeck:
    state = "open"

    def __init__(self, notes: list[Note], current: str | None, buffer: str | None) -> None:
        self.notes = notes
        self.current_id = current
        self.panel = FakePanel(buffer) if buffer is not None else None


def note(note_id: str, text: str) -> Note:
    return Note(id=note_id, text=text, created=1.0, updated=1.0, server_updated_at="v1")


def test_the_dump_shows_a_buffer_that_is_ahead_of_the_saved_text(tmp_path: Path) -> None:
    deck = FakeDeck(
        [note("a", "Проверка зам"), note("b", "other")], "a", "Проверка замени полный"
    )
    target = tmp_path / "deck.json"

    sigdump.snapshot(deck, target)

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["current_id"] == "a"
    assert document["buffer_length"] == len("Проверка замени полный")
    assert document["buffer_text"] == "Проверка замени полный"
    saved = next(item for item in document["notes"] if item["id"] == "a")
    assert saved["length"] == len("Проверка зам")
    assert saved["buffer_differs"] is True


def test_an_in_sync_note_is_reported_as_equal(tmp_path: Path) -> None:
    deck = FakeDeck([note("a", "same")], "a", "same")
    target = tmp_path / "deck.json"

    sigdump.snapshot(deck, target)

    saved = json.loads(target.read_text(encoding="utf-8"))["notes"][0]
    assert saved["buffer_differs"] is False


def test_no_open_note_dumps_without_a_buffer(tmp_path: Path) -> None:
    deck = FakeDeck([note("a", "x")], None, None)
    target = tmp_path / "deck.json"

    sigdump.snapshot(deck, target)

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["buffer_text"] is None
    assert document["buffer_length"] is None


def test_the_dump_is_written_atomically(tmp_path: Path) -> None:
    target = tmp_path / "deck.json"
    target.write_text("old", encoding="utf-8")

    sigdump.snapshot(FakeDeck([], None, None), target)

    assert json.loads(target.read_text(encoding="utf-8"))["state"] == "open"
    assert not (tmp_path / "deck.json.tmp").exists()


def test_a_relative_path_lands_beside_the_notes_file(tmp_path: Path, monkeypatch) -> None:
    # XDG_DATA_HOME wins, matching where notes.json lives; falling back to the
    # bare snap home put the dump outside the write area.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("SNAP_USER_DATA", str(tmp_path / "snap"))

    resolved = sigdump._resolve(Path("deck.json"))

    assert resolved == tmp_path / "lurknotes" / "deck.json"


def test_without_xdg_the_snap_data_dir_is_used(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("SNAP_USER_DATA", str(tmp_path))

    resolved = sigdump._resolve(Path("deck.json"))

    assert resolved == tmp_path / ".local" / "share" / "lurknotes" / "deck.json"


def test_install_is_off_without_the_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(sigdump.DUMP_ENV, raising=False)

    assert sigdump.install(object()) is None


def test_install_registers_a_handler_when_asked(tmp_path: Path, monkeypatch) -> None:
    import signal

    monkeypatch.setenv(sigdump.DUMP_ENV, str(tmp_path / "deck.json"))
    original = signal.getsignal(signal.SIGUSR1)
    try:
        destination = sigdump.install(object())
        assert destination == tmp_path / "deck.json"
        assert signal.getsignal(signal.SIGUSR1) is not original
    finally:
        signal.signal(signal.SIGUSR1, original)
