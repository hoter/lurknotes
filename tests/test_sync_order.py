"""Order inside `_on_sync_result`: finalize before saving, never after.

The bug this pins: `_save_notes` adopts the editor text and re-queues what
still differs, then `finalize()` cleared the queue by the ids from the push
reply — deleting the entry that had just been created. With an empty queue the
guard protected nothing, and the next pull wrote the server's older text over
the note while the user was typing.
"""

from __future__ import annotations

from lurkn.notes import Note
from lurkn.queue import PendingChange, Queue
from lurkn.syncer import SyncResult


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


def make_app(tmp_path, *, note_text: str, buffer_text: str):
    from lurkn.app import LurkNotesApp
    from lurkn.store import Store

    note = Note(id="a", text=note_text, created=1.0, updated=1.0)
    note.server_updated_at = "v1"
    store = Store(tmp_path / "notes.json")
    store.save([note])

    queue = Queue(tmp_path / "queue.json")
    queue.enqueue(PendingChange(id="a", text=note_text, position=0, created=1.0, base="v1"))

    app = LurkNotesApp.__new__(LurkNotesApp)
    app.notes = [note]
    app.store = store
    app.current_id = "a"
    app.panel = FakePanel(buffer_text)
    app.session_ids = set()
    app.unsaved = False
    app.read_only = False
    app.overwrite_blocked = False
    app.save_source = 0
    app._retrier = type("R", (), {"failed": lambda s: None, "succeeded": lambda s: None})()
    app._hooks = type("H", (), {"schedule_dump": lambda s, delay=0: None})()
    app.deck_changed = lambda: None
    app._sync_config = type(
        "C", (), {"enabled": True, "token": "t", "state": lambda self: "on"}
    )()
    app._sync_row_visible = True
    from lurkn.syncer import Syncer
    from lurkn.syncsettings import SyncConfig, SyncSettings

    settings = SyncSettings(tmp_path / "sync.json")
    settings.save(SyncConfig(enabled=True, token="t", server="http://n"))
    syncer = Syncer(settings, queue, client_factory=lambda _s: None)
    app._sync_controller = type(
        "S", (), {"syncer": syncer, "sync_now": lambda self: None}
    )()
    app._show_sync_state = lambda *_a: None
    return app, queue


def test_the_fresh_queue_entry_survives_a_sync_result(tmp_path) -> None:
    typed = "Lorem ipsum!\n\nSit amet sdfsdf\nsdfsdfsdf"
    app, queue = make_app(tmp_path, note_text="Lorem", buffer_text=typed)

    result = SyncResult(state="idle")
    result.applied_changes = [{"id": "a", "server_updated_at": "v2"}]
    result.finalize = lambda: queue.remove("a")

    app._on_sync_result(result)

    # The pull was empty, nothing to merge; but the editor had newer text, so
    # saving must have re-queued it — and finalize must not have removed it.
    assert [item.id for item in queue.load()] == ["a"]
    assert queue.load()[0].text == typed
