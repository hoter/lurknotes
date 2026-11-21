"""Tests for the sync building blocks that need no network and no GTK.

``sync.json`` and ``queue.json`` decide whether a crash loses a note edit, so
the tests here are about durability and trust, not about happy paths: file
modes, atomic replacement, a symlink squatting on the temp name, and what
happens when the files are corrupt.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from lurkn.atomic import atomic_write
from lurkn.queue import PendingChange, Queue, QueueError
from lurkn.syncsettings import (
    OFF,
    ON,
    PAUSED,
    SyncConfig,
    SyncConfigError,
    SyncSettings,
)


# -- atomic ----------------------------------------------------------------


def test_atomic_write_replaces_content_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "file.json"
    atomic_write(target, "one")
    atomic_write(target, "two")

    assert target.read_text(encoding="utf-8") == "two"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["file.json"]


def test_atomic_write_applies_mode_on_every_write(tmp_path: Path) -> None:
    target = tmp_path / "secret.json"
    atomic_write(target, "first", mode=0o600)
    # A previous version (or a manual copy) may have loosened it.
    target.chmod(0o644)

    atomic_write(target, "second", mode=0o600)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_write_refuses_to_follow_a_symlink_at_the_temp_name(
    tmp_path: Path,
) -> None:
    target = tmp_path / "secret.json"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("original", encoding="utf-8")
    (tmp_path / "secret.json.tmp").symlink_to(elsewhere)

    with pytest.raises(OSError):
        atomic_write(target, "new", mode=0o600)

    assert elsewhere.read_text(encoding="utf-8") == "original"


# -- settings --------------------------------------------------------------


def test_absent_file_means_never_configured(tmp_path: Path) -> None:
    settings = SyncSettings(tmp_path / "sync.json")

    config = settings.load()

    assert config.state() == OFF
    assert settings.exists is False
    assert settings.last_error is None


def test_saving_writes_a_private_file_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "sync.json"
    settings = SyncSettings(path)

    settings.save(
        SyncConfig(
            enabled=True,
            server="https://notes.example.com",
            email="user@example.com",
            token="1|abc",
            cursor="2026-11-21T09:00:00.000000Z",
        )
    )
    reloaded = SyncSettings(path).load()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert reloaded.state() == ON
    assert reloaded.email == "user@example.com"
    assert reloaded.cursor == "2026-11-21T09:00:00.000000Z"


def test_a_token_without_enabled_is_paused(tmp_path: Path) -> None:
    settings = SyncSettings(tmp_path / "sync.json")
    settings.save(SyncConfig(token="1|abc", enabled=False))

    assert settings.load().state() == PAUSED


def test_update_changes_one_field_without_losing_the_token(tmp_path: Path) -> None:
    settings = SyncSettings(tmp_path / "sync.json")
    settings.save(SyncConfig(token="1|abc", enabled=True))

    updated = settings.update(enabled=False)

    assert updated.token == "1|abc"
    assert updated.enabled is False


def test_corrupt_file_is_an_error_not_a_silent_reset(tmp_path: Path) -> None:
    path = tmp_path / "sync.json"
    path.write_text("{not json", encoding="utf-8")
    settings = SyncSettings(path)

    config = settings.load()

    assert config.state() == OFF
    assert isinstance(settings.last_error, SyncConfigError)
    # The file is left alone: the token inside cannot be recovered elsewhere.
    assert path.read_text(encoding="utf-8") == "{not json"


def test_unsupported_version_is_rejected_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "sync.json"
    path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    settings = SyncSettings(path)

    settings.load()

    assert settings.last_error is not None
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 99


def test_forget_returns_to_never_configured(tmp_path: Path) -> None:
    path = tmp_path / "sync.json"
    settings = SyncSettings(path)
    settings.save(SyncConfig(token="1|abc", enabled=True))

    settings.forget()

    assert not path.exists()
    assert settings.load().state() == OFF


# -- queue -----------------------------------------------------------------


def _change(note_id: str, text: str, *, base: str | None = None) -> PendingChange:
    return PendingChange(
        id=note_id, text=text, position=0, created=1.0, base=base
    )


def test_an_absent_queue_is_empty(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "queue.json")

    assert queue.load() == []
    assert not queue
    assert queue.last_error is None


def test_enqueue_replaces_the_earlier_state_of_the_same_note(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "queue.json")

    queue.enqueue(_change("a", "first"))
    queue.enqueue(_change("a", "second"))
    queue.enqueue(_change("b", "other"))

    texts = {item.id: item.text for item in queue.load()}
    assert texts == {"a": "second", "b": "other"}


def test_enqueue_keeps_the_original_base_version(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "queue.json")
    queue.enqueue(_change("a", "first", base="2026-11-21T09:00:00.000000Z"))

    queue.enqueue(_change("a", "second", base=None))

    assert queue.load()[0].base == "2026-11-21T09:00:00.000000Z"


def test_remove_and_clear_persist(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    queue = Queue(path)
    queue.enqueue(_change("a", "one"))
    queue.enqueue(_change("b", "two"))

    queue.remove("a")
    assert [item.id for item in Queue(path).load()] == ["b"]

    queue.clear()
    assert not path.exists()


def test_queue_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    Queue(path).enqueue(_change("a", "text"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_deleted_change_survives_the_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    queue = Queue(path)
    queue.enqueue(
        PendingChange(id="a", text="", position=0, created=1.0, deleted=True)
    )

    reloaded = Queue(path).load()[0]

    assert reloaded.deleted is True


def test_corrupt_queue_reads_as_empty_and_reports_the_error(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    path.write_text("[]", encoding="utf-8")
    queue = Queue(path)

    assert queue.load() == []
    assert queue.last_error is not None


def test_concurrent_enqueues_do_not_lose_changes(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "queue.json")
    threads = [
        threading.Thread(target=queue.enqueue, args=(_change(f"n{index}", "x"),))
        for index in range(24)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(queue.load()) == 24


def test_pending_change_rejects_a_non_object(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    path.write_text(
        json.dumps({"version": 1, "changes": ["nope"]}), encoding="utf-8"
    )

    queue = Queue(path)

    assert queue.load() == []
    assert isinstance(queue.last_error, QueueError)


def test_a_null_position_in_the_queue_does_not_poison_the_list(tmp_path: Path) -> None:
    # The queue writes `position: null` for a note with no sort order yet, and
    # int(None) used to make the whole file unreadable — every change vanished
    # even though the bytes were on disk.
    path = tmp_path / "queue.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "changes": [
                    {"id": "a", "text": "x", "position": None, "created": None, "base": None},
                    {"id": "b", "text": "y", "position": 3, "created": 1.0, "base": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    queue = Queue(path)

    loaded = queue.load()

    assert queue.last_error is None
    assert [item.id for item in loaded] == ["a", "b"]
    assert loaded[0].position == 0
