"""Store contract: spec §5.1 JSON, atomic writes, backup and recovery (§5.3)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lurkn.notes import Note
from lurkn.store import (
    LOAD_CORRUPT,
    LOAD_OK,
    LOAD_RECOVERED,
    LOAD_UNSUPPORTED,
    OverwriteBlocked,
    ReadOnlyError,
    Store,
    default_path,
)

CORRUPT_TEXT = "{not json"


def note(note_id: str, text: str, created: float = 1.0, updated: float = 2.0) -> Note:
    return Note(id=note_id, text=text, created=created, updated=updated)


def payload(*notes: Note) -> dict:
    return {"version": 1, "notes": [item.to_dict() for item in notes]}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def corrupt_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("notes.corrupt-*.json"))


# -- happy path ----------------------------------------------------------


def test_load_missing_file_returns_an_empty_ok_result_and_creates_nothing(tmp_path):
    result = Store(tmp_path / "notes.json").load()

    assert result.notes == []
    assert result.status == LOAD_OK
    assert result.read_only is False
    assert result.overwrite_blocked is False
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

    result = store.load()
    assert result.status == LOAD_OK
    assert result.notes == notes


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


def test_a_failed_replace_leaves_previous_main_and_backup_valid(tmp_path, monkeypatch):
    store = Store(tmp_path / "notes.json")
    store.save([note("a", "old")])
    store.save([note("a", "safe")])
    before_main = (tmp_path / "notes.json").read_bytes()

    def explode(*_args, **_kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        store.save([note("a", "lost")])

    assert (tmp_path / "notes.json").read_bytes() == before_main
    assert read_json(tmp_path / "notes.bak.json")["notes"][0]["text"] == "safe"
    assert not (tmp_path / "notes.json.tmp").exists()
    assert store.load().notes == [note("a", "safe")]


def test_a_failed_tmp_write_leaves_old_file_and_no_temp(tmp_path, monkeypatch):
    store = Store(tmp_path / "notes.json")
    store.save([note("a", "safe")])
    store.save([note("a", "older")])
    before_main = (tmp_path / "notes.json").read_bytes()
    before_backup = (tmp_path / "notes.bak.json").read_bytes()

    def explode(_descriptor):
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", explode)

    with pytest.raises(OSError):
        store.save([note("a", "lost")])

    assert (tmp_path / "notes.json").read_bytes() == before_main
    assert (tmp_path / "notes.bak.json").read_bytes() == before_backup
    assert not (tmp_path / "notes.json.tmp").exists()
    assert store.load().notes == [note("a", "older")]
    assert read_json(tmp_path / "notes.bak.json")["notes"][0]["text"] == "safe"


# -- corrupt main, no usable backup -------------------------------------


@pytest.mark.parametrize(
    "backup_text",
    [
        None,  # no backup at all
        CORRUPT_TEXT,  # invalid JSON
        '{"version": 1, "notes": "nope"}',  # wrong shape
        '{"notes": []}',  # missing version
        '{"version": 99, "notes": []}',  # a future backup is unusable
        '{"version": 1, "notes": [{"id": "a"}]}',  # invalid note
    ],
    ids=["absent", "invalid-json", "wrong-shape", "missing-version", "future", "bad-note"],
)
def test_corrupt_main_without_a_usable_backup_never_writes_before_action(
    tmp_path, backup_text
):
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    path.write_text(CORRUPT_TEXT, encoding="utf-8")
    original_main = path.read_bytes()
    if backup_text is not None:
        backup.write_text(backup_text, encoding="utf-8")
        original_backup = backup.read_bytes()
    store = Store(path)

    result = store.load()

    assert result.notes == []
    assert result.status == LOAD_CORRUPT
    assert result.read_only is False
    assert result.overwrite_blocked is True
    assert path.read_bytes() == original_main
    assert not (tmp_path / "notes.json.tmp").exists()
    assert corrupt_files(tmp_path) == []
    if backup_text is not None:
        assert backup.read_bytes() == original_backup
    else:
        assert not backup.exists()

    with pytest.raises(OverwriteBlocked):
        store.save([note("new", "never written")])

    assert path.read_bytes() == original_main
    assert corrupt_files(tmp_path) == []
    if backup_text is not None:
        assert backup.read_bytes() == original_backup


def test_confirming_overwrite_preserves_the_corrupt_file_then_writes(tmp_path):
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    path.write_text(CORRUPT_TEXT, encoding="utf-8")
    backup.write_text("also corrupt", encoding="utf-8")
    original_main = path.read_bytes()
    original_backup = backup.read_bytes()
    store = Store(path)
    store.load()

    store.confirm_overwrite()
    store.save([note("new", "fresh deck")])

    saved = read_json(path)
    assert saved == payload(note("new", "fresh deck"))
    quarantined = corrupt_files(tmp_path)
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == original_main
    assert backup.read_bytes() == original_backup
    assert not (tmp_path / "notes.json.tmp").exists()


# -- corrupt main, valid backup -----------------------------------------


def test_corrupt_main_recovers_from_backup_quarantines_it_and_persists(tmp_path):
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    recovered = [note("a", "from backup"), note("b", "second")]
    path.write_text(CORRUPT_TEXT, encoding="utf-8")
    original_main = path.read_bytes()
    write_json(backup, payload(*recovered))
    original_backup = backup.read_bytes()
    store = Store(path)

    result = store.load()

    assert result.status == LOAD_RECOVERED
    assert result.notes == recovered
    assert result.read_only is False
    assert result.overwrite_blocked is False
    assert result.save_error is None
    assert result.corrupt_path is not None
    assert result.corrupt_path.read_bytes() == original_main
    assert result.corrupt_path.name.startswith("notes.corrupt-")
    # The recovered deck is on disk, so a restart does not fall back to empty.
    assert read_json(path) == payload(*recovered)
    assert backup.read_bytes() == original_backup
    assert not (tmp_path / "notes.json.tmp").exists()

    restart = Store(path).load()
    assert restart.status == LOAD_OK
    assert restart.notes == recovered
    assert len(corrupt_files(tmp_path)) == 1


def test_a_second_corruption_in_the_same_second_gets_a_unique_name(
    tmp_path, monkeypatch
):
    """Two quarantine moves must not overwrite each other (spec §5.3)."""
    import lurkn.store as store_module

    monkeypatch.setattr(
        store_module.time, "strftime", lambda *_args: "20260101T000000"
    )
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    write_json(backup, payload(note("a", "from backup")))

    path.write_text("{first corruption", encoding="utf-8")
    first = Store(path).load()
    assert first.corrupt_path == tmp_path / "notes.corrupt-20260101T000000.json"
    assert first.corrupt_path.read_text(encoding="utf-8") == "{first corruption"

    path.write_text("{second corruption", encoding="utf-8")
    second = Store(path).load()
    assert (
        second.corrupt_path == tmp_path / "notes.corrupt-20260101T000000-1.json"
    )
    assert second.corrupt_path.read_text(encoding="utf-8") == "{second corruption"

    assert [item.read_text(encoding="utf-8") for item in (
        tmp_path / "notes.corrupt-20260101T000000.json",
        tmp_path / "notes.corrupt-20260101T000000-1.json",
    )] == ["{first corruption", "{second corruption"]
    assert read_json(path) == payload(note("a", "from backup"))


@pytest.mark.parametrize(
    "main_text",
    [
        '{"version": 1, "notes": "nope"}',
        '{"notes": []}',
        '{"version": 1, "notes": [{"id": "a"}]}',
    ],
    ids=["wrong-shape", "missing-version", "bad-note"],
)
def test_any_unreadable_main_shape_recovers_from_a_valid_backup(tmp_path, main_text):
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    recovered = [note("a", "still recovered")]
    path.write_text(main_text, encoding="utf-8")
    original_main = path.read_bytes()
    write_json(backup, payload(*recovered))

    result = Store(path).load()

    assert result.status == LOAD_RECOVERED
    assert result.notes == recovered
    assert result.corrupt_path is not None
    assert result.corrupt_path.read_bytes() == original_main
    assert read_json(path) == payload(*recovered)


def test_recovered_notes_stay_in_memory_when_persisting_them_fails(tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    recovered = [note("a", "from backup")]
    path.write_text(CORRUPT_TEXT, encoding="utf-8")
    write_json(backup, payload(*recovered))
    store = Store(path)

    def explode(*_args, **_kwargs):
        raise OSError("data dir is read-only")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", explode)
        result = store.load()

    assert result.status == LOAD_RECOVERED
    assert result.notes == recovered
    assert isinstance(result.save_error, OSError)
    assert path.read_text(encoding="utf-8") == CORRUPT_TEXT
    assert corrupt_files(tmp_path) == []

    # A later retry (after permissions return) quarantines and persists.
    store.save(result.notes)

    assert read_json(path) == payload(*recovered)
    assert len(corrupt_files(tmp_path)) == 1


def test_a_missing_main_is_restored_from_a_valid_backup(tmp_path):
    """Covers a crash between quarantining the corrupt file and persisting."""
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    recovered = [note("a", "still here")]
    write_json(backup, payload(*recovered))
    original_backup = backup.read_bytes()

    result = Store(path).load()

    assert result.status == LOAD_RECOVERED
    assert result.notes == recovered
    assert read_json(path) == payload(*recovered)
    assert backup.read_bytes() == original_backup


def test_a_valid_main_ignores_a_corrupt_backup(tmp_path):
    path = tmp_path / "notes.json"
    backup = tmp_path / "notes.bak.json"
    good = [note("a", "fine")]
    write_json(path, payload(*good))
    original_main = path.read_bytes()
    backup.write_text(CORRUPT_TEXT, encoding="utf-8")
    original_backup = backup.read_bytes()

    result = Store(path).load()

    assert result.status == LOAD_OK
    assert result.notes == good
    assert path.read_bytes() == original_main
    assert backup.read_bytes() == original_backup
    assert corrupt_files(tmp_path) == []


# -- unknown future version ---------------------------------------------


def test_future_version_is_read_only_and_never_written(tmp_path):
    path = tmp_path / "notes.json"
    future = [note("a", "newer build note")]
    write_json(path, {"version": 99, "notes": [future[0].to_dict()]})
    original = path.read_bytes()
    store = Store(path)

    result = store.load()

    assert result.status == LOAD_UNSUPPORTED
    assert result.read_only is True
    assert result.overwrite_blocked is False
    assert result.notes == future
    assert path.read_bytes() == original
    assert not (tmp_path / f"notes.bak.json").exists()
    assert corrupt_files(tmp_path) == []

    for deck in ([note("new", "clobber")], result.notes):
        with pytest.raises(ReadOnlyError):
            store.save(deck)
        assert path.read_bytes() == original
        assert not (tmp_path / "notes.json.tmp").exists()
        assert corrupt_files(tmp_path) == []

    # Explicit action does not turn a future file writable.
    store.confirm_overwrite()
    with pytest.raises(ReadOnlyError):
        store.save(result.notes)
    assert path.read_bytes() == original


def test_future_version_with_unreadable_notes_is_still_read_only(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text('{"version": 99, "items": []}', encoding="utf-8")
    original = path.read_bytes()
    store = Store(path)

    result = store.load()

    assert result.status == LOAD_UNSUPPORTED
    assert result.notes == []
    assert result.read_only is True
    assert path.read_bytes() == original


# -- unwritable directory ------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_save_into_an_unwritable_directory_fails_then_succeeds_after_chmod(tmp_path):
    directory = tmp_path / "lurknotes"
    directory.mkdir()
    path = directory / "notes.json"
    store = Store(path)
    store.save([note("a", "old")])
    store.save([note("a", "older")])
    before_main = path.read_bytes()
    before_backup = (directory / "notes.bak.json").read_bytes()
    directory.chmod(0o500)
    try:
        with pytest.raises(OSError):
            store.save([note("a", "new")])
        assert path.read_bytes() == before_main
        assert (directory / "notes.bak.json").read_bytes() == before_backup
        assert not (directory / "notes.json.tmp").exists()
        assert store.load().notes == [note("a", "older")]
    finally:
        directory.chmod(0o700)

    store.save([note("a", "new")])

    assert store.load().notes == [note("a", "new")]
    assert read_json(directory / "notes.bak.json")["notes"][0]["text"] == "older"


def test_default_path_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert default_path() == tmp_path / "lurknotes" / "notes.json"
