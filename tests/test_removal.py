"""The deck's side of deletion: undo cancels, expiry announces.

The behaviour a user notices: pressing undo within ten seconds must leave the
server untouched. Expiring must send one tombstone.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from lurkn.app import LurkNotesApp
from lurkn.deletion import PendingRemoval
from lurkn.notes import Note
from lurkn.queue import Queue
from lurkn.store import Store
from lurkn.syncsettings import SyncConfig, SyncSettings


class FakeSyncer:
    def __init__(self, queue: Queue) -> None:
        self.queue = queue
        self.deletions: list[tuple[str, str | None]] = []

    def enqueue_delete(self, *, note_id: str, base: str | None) -> None:
        self.deletions.append((note_id, base))


class FakeController:
    def __init__(self, syncer: FakeSyncer) -> None:
        self.syncer = syncer
        self.kicks = 0

    def sync_now(self) -> None:
        self.kicks += 1


@pytest.fixture()
def wired(tmp_path: Path):
    settings = SyncSettings(tmp_path / "sync.json")
    settings.save(SyncConfig(enabled=True, token="t", server="http://n"))
    queue = Queue(tmp_path / "queue.json")
    syncer = FakeSyncer(queue)
    app = LurkNotesApp.__new__(LurkNotesApp)
    app._sync_controller = FakeController(syncer)
    app._pending_removal = None
    app._hooks = type("H", (), {"schedule_dump": lambda self, delay=0: None})()
    app._show_sync_state = lambda *_a: None
    return app, syncer


def test_expiry_queues_the_tombstone(wired) -> None:
    app, syncer = wired
    app._pending_removal = PendingRemoval(note=Note(id="a", text="x", created=1.0, updated=1.0), base="v1")

    app._announce_removal()

    assert syncer.deletions == [("a", "v1")]
    assert app._pending_removal is None


def test_expiry_twice_sends_only_one_tombstone(wired) -> None:
    app, syncer = wired
    app._pending_removal = PendingRemoval(note=Note(id="a", text="x", created=1.0, updated=1.0), base="v1")

    app._announce_removal()
    app._announce_removal()

    assert syncer.deletions == [("a", "v1")]


def test_a_never_synced_note_sends_nothing(wired) -> None:
    app, syncer = wired
    app._pending_removal = PendingRemoval(
        note=Note(id="a", text="x", created=1.0, updated=1.0), base=None
    )

    app._announce_removal()

    assert syncer.deletions == []


def test_no_pending_removal_is_a_no_op(wired) -> None:
    app, syncer = wired
    app._announce_removal()

    assert syncer.deletions == []
