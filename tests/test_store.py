"""Store contract: spec §5.1 JSON, missing file, backup, atomic replace."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lurkn.notes import Note
from lurkn.store import CorruptData, Store, UnsupportedVersion, default_path


def note(note_id: str, text: str, created: float = 1.0, updated: float = 2.0) -> Note:
    return Note(id=note_id, text=text, created=created, updated=updated)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_load_missing_file_returns_an_empty_list_and_creates_nothing(tmp_path):
    store = Store(tmp_path / "notes.json")

    assert store.load() == []
    assert not (tmp_path / "notes.json").exists()
    assert not (tmp_path / "notes.bak.json").exists()
    assert not (tmp_path / "notes.json.tmp").exists()


def test_save_writes_version_one_and_the_spec_note_shape(tmp_path):
    store = Store(tmp_path / "notes.json")
    notes = [note("a", "Groceries\nmilk")]

    store.save(notes)

    payload = read_json(tmp_path / "notes.json")
    assert payload == {
        "version": 1,
        "notes": [
            {
                "id": "a",
                "text": "Groceries\nmilk",
                "created": 1.0,
                "updated": 2.0,
            }
        ],
    }


def test_save_then_load_round_trips_notes_in_array_order(tmp_path):
    store = Store(tmp_path / "notes.json")
    notes = [note("b", "second"), note("a", "first")]

    store.save(notes)

    assert store.load() == notes


def test_save_over_an_existing_file_backs_up_the_previous_content(tmp_path):
    store = Store(tmp_path / "notes.json")
    store.save([note("old", "before")])
    previous_bytes = (tmp_path / "notes.json").read_bytes()

    store.save([note("new", "after")])

    backup = tmp_path / "notes.bak.json"
    assert backup.exists()
    assert backup.read_bytes() == previous_bytes
    assert read_json(backup)["notes"][0]["text"] == "before"
    assert read_json(tmp_path / "notes.json")["notes"][0]["text"] == "after"


def test_first_save_does_not_create_a_backup(tmp_path):
    store = Store(tmp_path / "notes.json")

    store.save([note("a", "first")])

    assert not (tmp_path / "notes.bak.json").exists()


def test_save_leaves_no_temp_file_and_writes_valid_json(tmp_path):
    store = Store(tmp_path / "notes.json")

    store.save([note("a", "text")])

    assert not (tmp_path / "notes.json.tmp").exists()
    assert read_json(tmp_path / "notes.json")["version"] == 1


def test_save_creates_the_data_directory_on_first_write(tmp_path):
    store = Store(tmp_path / "lurknotes" / "notes.json")

    store.save([note("a", "text")])

    assert (tmp_path / "lurknotes" / "notes.json").exists()


def test_a_failed_replace_leaves_the_previous_file_intact(tmp_path, monkeypatch):
    store = Store(tmp_path / "notes.json")
    store.save([note("a", "safe")])

    def explode(*_args, **_kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        store.save([note("a", "lost")])

    assert store.load() == [note("a", "safe")]


def test_load_rejects_a_malformed_file(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CorruptData):
        Store(path).load()


def test_load_rejects_wrong_note_structure(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps({"version": 1, "notes": [{"id": "a"}]}), encoding="utf-8")

    with pytest.raises(CorruptData):
        Store(path).load()


def test_load_refuses_an_unknown_version(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps({"version": 99, "notes": []}), encoding="utf-8")

    with pytest.raises(UnsupportedVersion):
        Store(path).load()


def test_default_path_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert default_path() == tmp_path / "lurknotes" / "notes.json"
