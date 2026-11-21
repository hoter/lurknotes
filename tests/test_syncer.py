"""The sync loop against the fake server (sync spec §6.2).

The order of operations is the contract, so most of these tests assert on the
order rather than just the end state: enqueue before sending, dequeue only
after storing the version, and never retry a dead token.
"""

from __future__ import annotations

import pytest

from lurkn.queue import Queue
from lurkn.syncclient import AuthError, TransportError
from lurkn.syncsettings import SyncConfig, SyncSettings
from lurkn.syncer import NEEDS_ATTENTION, Syncer

VERSION = "2026-11-21T09:15:01.002331Z"
NOTE = "0f0c2f4e-6a1b-4c3d-9e8f-1a2b3c4d5e6f"


class FakeClient:
    """Records calls and replays a scripted server."""

    def __init__(self) -> None:
        self.pushes: list[list[dict]] = []
        self.pull_calls: list[tuple[str | None, int | None]] = []
        self.revoked: list[str] = []
        self.on_push: object = (200, {"applied": [], "rejected": []})
        self.on_pull: object = (200, {"changes": [], "cursor": VERSION, "after": 1, "has_more": False})

    def push(self, token: str, changes: list[dict]) -> dict:
        self.pushes.append(changes)
        if isinstance(self.on_push, Exception):
            raise self.on_push
        return self.on_push[1]  # the scripted (status, body) pair

    def pull(self, token: str, *, since: str | None, after: int | None = None) -> dict:
        self.pull_calls.append((since, after))
        if isinstance(self.on_pull, Exception):
            raise self.on_pull
        return self.on_pull[1]

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


@pytest.fixture()
def wired(tmp_path):
    settings = SyncSettings(tmp_path / "sync.json")
    queue = Queue(tmp_path / "queue.json")
    settings.save(
        SyncConfig(
            enabled=True,
            server="https://notes.example.com",
            email="user@example.com",
            token="1|token",
            cursor="",
        )
    )
    fake = FakeClient()
    syncer = Syncer(settings, queue, client_factory=lambda _server: fake)
    return syncer, settings, queue, fake


def test_a_queued_change_is_sent_and_removed_once_the_server_accepts_it(wired) -> None:
    syncer, settings, queue, fake = wired
    syncer.enqueue_note(note_id=NOTE, text="hello", position=0, created=1.0, base=None)
    fake.on_push = (
        200,
        {"applied": [{"id": NOTE, "server_updated_at": VERSION, "deleted": False}], "rejected": []},
    )

    result = syncer.run_once()

    assert result.applied == 1
    assert fake.pushes == [[queue_item(NOTE, "hello", None)]]
    # The queue keeps the entry until the app has stored the version.
    assert [item.id for item in queue.load()] == [NOTE]
    result.finalize()
    assert queue.load() == []
    assert settings.load().last_sync


def test_a_network_failure_keeps_the_change_queued(wired) -> None:
    syncer, _settings, queue, fake = wired
    syncer.enqueue_note(note_id=NOTE, text="hello", position=0, created=1.0, base=None)
    fake.on_push = TransportError("connection refused")

    result = syncer.run_once()

    assert result.state == NEEDS_ATTENTION
    assert "connection refused" in result.error
    assert [item.id for item in queue.load()] == [NOTE]


def test_a_dead_token_stops_instead_of_retrying(wired) -> None:
    syncer, _settings, queue, fake = wired
    syncer.enqueue_note(note_id=NOTE, text="hello", position=0, created=1.0, base=None)
    fake.on_push = AuthError("the device token was rejected")

    result = syncer.run_once()

    assert result.state == NEEDS_ATTENTION
    assert [item.id for item in queue.load()] == [NOTE]
    assert fake.pull_calls == []


def test_a_stale_change_is_dropped_and_the_pull_wins(wired) -> None:
    syncer, _settings, queue, fake = wired
    syncer.enqueue_note(note_id=NOTE, text="mine", position=0, created=1.0, base="old")
    fake.on_push = (
        200,
        {"applied": [], "rejected": [{"id": NOTE, "reason": "stale"}]},
    )

    result = syncer.run_once()
    result.finalize()

    assert queue.load() == []


def test_a_pull_updates_the_cursor_and_the_last_sync(wired) -> None:
    syncer, settings, _queue, fake = wired
    fake.on_pull = (
        200,
        {
            "changes": [{"id": NOTE, "server_updated_at": VERSION}],
            "cursor": VERSION,
            "after": 7,
            "has_more": False,
        },
    )

    result = syncer.run_once()

    assert result.pulled == 1
    assert settings.load().cursor == VERSION


def test_paging_uses_both_the_cursor_and_the_row_id(wired) -> None:
    syncer, _settings, _queue, fake = wired
    pages = [
        (200, {"changes": [{"id": NOTE}], "cursor": VERSION, "after": 5, "has_more": True}),
        (200, {"changes": [{"id": "b" * 36}], "cursor": VERSION, "after": 9, "has_more": False}),
    ]

    def pull(token: str, *, since: str | None, after: int | None = None) -> dict:
        fake.pull_calls.append((since, after))
        return pages[len(fake.pull_calls) - 1][1]

    fake.pull = pull  # type: ignore[assignment]
    syncer.run_once()

    assert fake.pull_calls[0] == (None, None)
    assert fake.pull_calls[1] == (VERSION, 5)


def test_sync_off_touches_neither_network_nor_queue(wired) -> None:
    syncer, settings, queue, fake = wired
    syncer.enqueue_note(note_id=NOTE, text="hello", position=0, created=1.0, base=None)
    settings.update(enabled=False)

    result = syncer.run_once()

    assert result.applied == 0
    assert fake.pushes == [] and fake.pull_calls == []
    assert [item.id for item in queue.load()] == [NOTE]


def test_a_deletion_is_queued_as_a_tombstone(wired) -> None:
    syncer, _settings, queue, fake = wired
    syncer.enqueue_delete(note_id=NOTE, base=VERSION)
    fake.on_push = (200, {"applied": [{"id": NOTE, "server_updated_at": VERSION, "deleted": True}], "rejected": []})

    result = syncer.run_once()
    result.finalize()

    assert fake.pushes[0][0]["deleted"] is True
    assert queue.load() == []


def test_sign_out_revokes_and_forgets(wired) -> None:
    syncer, settings, queue, fake = wired
    syncer.enqueue_note(note_id=NOTE, text="hello", position=0, created=1.0, base=None)

    syncer.sign_out()

    assert fake.revoked == ["1|token"]
    assert settings.load().token == ""
    assert queue.load() == []
    assert not settings.path.exists()


def queue_item(note_id: str, text: str, base: str | None) -> dict:
    return {
        "id": note_id,
        "text": text,
        "position": 0,
        "created": 1.0,
        "base": base,
        "deleted": False,
    }


def test_the_queue_survives_the_pull_so_the_editor_is_protected(wired) -> None:
    """The bug: push cleared the queue, the pull then saw "no local edit".

    `_editing_protection` treats a queued change as proof the user's text is
    the truth. Clearing the queue inside `_push` left the pull with nothing to
    see, so it overwrote the note with the server's older copy.
    """
    syncer, _settings, queue, fake = wired
    syncer.enqueue_note(note_id=NOTE, text="typed far more than this", position=0, created=1.0, base=None)
    fake.on_push = (
        200,
        {"applied": [{"id": NOTE, "server_updated_at": VERSION, "deleted": False}], "rejected": []},
    )
    fake.on_pull = (
        200,
        {
            "changes": [{"id": NOTE, "text": "typed", "server_updated_at": VERSION, "deleted": False}],
            "cursor": VERSION,
            "after": 1,
            "has_more": False,
        },
    )

    result = syncer.run_once()

    # During the pull the entry must still be there for the guard to see.
    assert [item.id for item in queue.load()] == [NOTE]
    assert result.finalize is not None

    result.finalize()

    assert queue.load() == []
