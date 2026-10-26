"""Delete with a 10 s in-memory undo (spec §4.5, §5.4, §7.3).

The pending undo is exactly one slot: starting a second delete drops the first
payload, cancelling its timer, and restarts the countdown. Undo restores the
note object untouched, so its id, timestamps and session membership survive.
The app tests drive the real methods with a fake panel/store: the toast widget
itself is covered by the live X11 smoke.
"""

from __future__ import annotations

from typing import Callable

from lurkn.app import (
    STATE_FAN,
    STATE_OPEN,
    DeletedNote,
    LurkNotesApp,
    UndoController,
)
from lurkn.deck import DeckMachine
from lurkn.events import DeckChanged
from lurkn.notes import Note, discard_if_untouched


class FakeScheduler:
    """GLib.timeout_add/source_remove lookalike that honours cancellation."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, Callable[[], bool]]] = []
        self.cancelled: list[int] = []
        self._live: set[int] = set()

    def __call__(self, delay: int, callback: Callable[[], bool]) -> int:
        handle = len(self.calls) + 1
        self.calls.append((delay, callback))
        self._live.add(handle)
        return handle

    def cancel(self, handle: int) -> None:
        self.cancelled.append(handle)
        self._live.discard(handle)

    def fire(self, handle: int) -> None:
        if handle in self._live:
            self._live.discard(handle)
            self.calls[handle - 1][1]()


class FakeNoteView:
    def __init__(self) -> None:
        self._text = ""

    def text(self) -> str:
        return self._text


class FakePanel:
    def __init__(self) -> None:
        self.note = FakeNoteView()
        self.toast_visible = False
        self.toast_shows = 0
        self.shown: list[tuple[str, object]] = []
        self.save_failed: list[bool] = []

    def show_toast(self) -> None:
        self.toast_shows += 1
        self.toast_visible = True

    def hide_toast(self) -> None:
        self.toast_visible = False

    def set_visible(self, visible: bool) -> None:
        self.visible = visible

    def show_note(self, note: Note, notes) -> None:
        self.shown.append(("note", note.id))

    def show_fan(self, notes) -> None:
        self.shown.append(("fan", len(notes)))

    def refresh_notes(self, notes, active_id) -> None:
        pass

    def show_save_failed(self, failed: bool) -> None:
        self.save_failed.append(failed)

    def get_surface(self):
        return None

    def present(self) -> None:
        pass

    def focus_editor(self) -> None:
        pass


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[list[str]] = []

    def save(self, notes) -> None:
        self.saved.append([note.id for note in notes])


class NullRetrier:
    def succeeded(self) -> None:
        pass

    def failed(self) -> None:
        pass

    def stop(self) -> None:
        pass


def make_note(note_id: str, text: str = "") -> Note:
    return Note(id=note_id, text=text, created=1.0, updated=1.0)


def make_app(
    notes: list[Note],
    *,
    read_only: bool = False,
    session_ids: set[str] | None = None,
) -> tuple[LurkNotesApp, FakePanel, FakeStore, FakeScheduler]:
    app = LurkNotesApp.__new__(LurkNotesApp)
    app.notes = list(notes)
    app.session_ids = set(session_ids or ())
    app.current_id = None
    # Ticket 04 moved deck state into the pure machine; these tests drive the
    # app methods directly, so a machine without timers is enough.
    app.deck = DeckMachine(lambda _delay, _callback: 0, lambda _handle: None)
    app.deck.state = STATE_FAN
    app.save_source = 0
    app.unsaved = False
    app.read_only = read_only
    app.overwrite_blocked = False
    app.panel = FakePanel()
    app.store = FakeStore()
    app.x11 = None
    app._test_dump_path = None
    app._test_type = None
    app.deck_changed_event = DeckChanged()
    app._retrier = NullRetrier()
    scheduler = FakeScheduler()
    app._undo = UndoController(
        timeout_ms=10_000,
        schedule=scheduler,
        cancel=scheduler.cancel,
        on_expire=app._on_undo_expired,
    )
    return app, app.panel, app.store, scheduler


# -- the one pending undo slot -------------------------------------------


def test_starting_an_undo_schedules_a_ten_second_timer():
    scheduler = FakeScheduler()
    expired: list[bool] = []
    undo = UndoController(
        timeout_ms=10_000,
        schedule=scheduler,
        cancel=scheduler.cancel,
        on_expire=lambda: expired.append(True),
    )
    note = make_note("a")

    undo.start(DeletedNote(note=note, index=0, session_member=True))

    assert undo.pending is not None
    assert undo.pending.note is note
    assert scheduler.calls[0][0] == 10_000

    scheduler.fire(1)
    assert undo.pending is None
    assert expired == [True]


def test_a_second_delete_drops_the_first_payload_and_restarts_the_timer():
    scheduler = FakeScheduler()
    undo = UndoController(
        timeout_ms=10_000, schedule=scheduler, cancel=scheduler.cancel
    )
    first = DeletedNote(note=make_note("first"), index=0, session_member=False)
    second = DeletedNote(note=make_note("second"), index=1, session_member=False)

    undo.start(first)
    undo.start(second)

    assert undo.pending is second
    assert scheduler.cancelled == [1]
    assert [delay for delay, _ in scheduler.calls] == [10_000, 10_000]

    # The cancelled callback must not clear the new pending undo.
    scheduler.fire(1)
    assert undo.pending is second


def test_taking_the_pending_undo_cancels_its_timer():
    scheduler = FakeScheduler()
    undo = UndoController(
        timeout_ms=10_000, schedule=scheduler, cancel=scheduler.cancel
    )
    deleted = DeletedNote(note=make_note("a"), index=0, session_member=False)
    undo.start(deleted)

    assert undo.take() is deleted
    assert undo.pending is None
    assert scheduler.cancelled == [1]
    assert undo.take() is None


def test_finalising_cancels_without_handing_the_payload_back():
    scheduler = FakeScheduler()
    undo = UndoController(
        timeout_ms=10_000, schedule=scheduler, cancel=scheduler.cancel
    )
    undo.start(DeletedNote(note=make_note("a"), index=0, session_member=False))

    undo.finalize()

    assert undo.pending is None
    assert scheduler.cancelled == [1]


# -- app: delete ---------------------------------------------------------


def test_delete_writes_immediately_and_opens_the_next_note():
    first, second, third = (
        make_note("first", "one"),
        make_note("second", "two"),
        make_note("third", "three"),
    )
    app, panel, store, scheduler = make_app([first, second, third])
    app.open_note(second.id)

    assert app.delete_current() is True

    assert [note.id for note in app.notes] == ["first", "third"]
    assert store.saved[-1] == ["first", "third"]
    assert app.current_id == "third"
    assert app.state == STATE_OPEN
    assert panel.toast_visible is True
    assert app._undo.pending is not None
    assert app._undo.pending.note is second
    assert app._undo.pending.index == 1
    assert scheduler.calls[0][0] == 10_000


def test_delete_flushes_unsaved_typing_into_the_undo_payload():
    first, second = make_note("first", "one"), make_note("second", "two")
    app, panel, _store, _scheduler = make_app([first, second])
    app.open_note(first.id)
    panel.note._text = "one edited"

    app.delete_current()

    assert app._undo.pending is not None
    assert app._undo.pending.note.text == "one edited"


def test_deleting_the_last_note_shows_the_empty_fan_and_undo_restores_it():
    only = make_note("only", "last")
    app, panel, store, scheduler = make_app([only])
    app.open_note(only.id)

    assert app.delete_current() is True
    assert app.notes == []
    assert app.current_id is None
    assert app.state == STATE_FAN
    assert panel.shown[-1] == ("fan", 0)
    assert store.saved[-1] == []

    # Deleting again with an empty deck is a no-op, not a crash.
    assert app.delete_current() is False
    assert app._undo.pending is not None
    assert app._undo.pending.note.id == "only"
    assert len(scheduler.calls) == 1

    assert app.undo_delete() is True
    assert [note.id for note in app.notes] == ["only"]
    assert app.current_id == "only"
    assert app.state == STATE_OPEN
    assert store.saved[-1] == ["only"]
    assert panel.toast_visible is False


def test_delete_without_an_open_note_does_nothing():
    app, panel, store, scheduler = make_app([make_note("a")])

    assert app.delete_current() is False

    assert store.saved == []
    assert panel.toast_visible is False
    assert scheduler.calls == []


# -- app: undo -----------------------------------------------------------


def test_undo_restores_the_note_at_its_original_index_and_reopens_it():
    first, second, third = (
        make_note("first"),
        make_note("second"),
        make_note("third"),
    )
    app, panel, store, _scheduler = make_app([first, second, third])
    app.open_note(second.id)
    app.delete_current()
    assert [note.id for note in app.notes] == ["first", "third"]

    assert app.undo_delete() is True

    assert [note.id for note in app.notes] == ["first", "second", "third"]
    assert app.notes[1] is second
    assert app.current_id == "second"
    assert app.state == STATE_OPEN
    assert store.saved[-1] == ["first", "second", "third"]
    assert panel.toast_visible is False
    assert app._undo.pending is None


def test_undo_keeps_the_note_untouched_and_in_the_session():
    session_note = Note.create()
    other = make_note("other")
    app, _panel, _store, _scheduler = make_app(
        [session_note, other], session_ids={session_note.id}
    )
    app.open_note(session_note.id)
    app.delete_current()

    assert app.undo_delete() is True

    assert session_note.id in app.session_ids
    restored = app.notes[0]
    assert restored.id == session_note.id
    assert restored.created == session_note.created
    assert restored.updated == session_note.updated
    # Ticket 03: an undone untouched note still disappears when left.
    assert discard_if_untouched(app.notes, restored.id, app.session_ids) is restored


def test_expiry_finalises_the_delete_and_drops_the_payload():
    first, second = make_note("first"), make_note("second")
    app, panel, store, scheduler = make_app([first, second])
    app.open_note(first.id)
    app.delete_current()
    saved_before = list(store.saved)

    scheduler.fire(1)

    assert app._undo.pending is None
    assert panel.toast_visible is False
    assert app.undo_delete() is False
    assert store.saved == saved_before
    assert [note.id for note in app.notes] == ["second"]


def test_second_delete_finalises_the_first_and_only_restores_the_second():
    first, second, third = make_note("first"), make_note("second"), make_note("third")
    app, panel, _store, scheduler = make_app([first, second, third])
    app.open_note(second.id)

    app.delete_current()
    first_handle = 1
    assert app._undo.pending is not None
    assert app._undo.pending.note.id == "second"

    app.delete_current()  # second is gone; the open note is now third
    assert app.current_id == "first"
    assert app._undo.pending is not None
    assert app._undo.pending.note.id == "third"
    assert scheduler.cancelled == [first_handle]
    assert panel.toast_shows == 2

    scheduler.fire(first_handle)  # cancelled: must not clear the new payload
    assert app._undo.pending is not None
    assert app._undo.pending.note.id == "third"

    assert app.undo_delete() is True
    assert [note.id for note in app.notes] == ["first", "third"]
    assert app.current_id == "third"


def test_read_only_delete_and_undo_stay_in_memory_and_never_write():
    first, second = make_note("first"), make_note("second")
    app, panel, store, _scheduler = make_app([first, second], read_only=True)
    app.open_note(first.id)

    assert app.delete_current() is True
    assert [note.id for note in app.notes] == ["second"]
    assert store.saved == []
    assert panel.save_failed == []
    assert app.unsaved is False
    assert panel.toast_visible is True

    assert app.undo_delete() is True
    assert [note.id for note in app.notes] == ["first", "second"]
    assert app.current_id == "first"
    assert store.saved == []
    assert panel.save_failed == []
    assert app.unsaved is False
