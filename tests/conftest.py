"""Shared non-GUI test helpers.

``make_note`` builds a note without touching the clock. ``make_app`` builds a
``LurkNotesApp`` with fake widgets/store/timers for the app-level tests; it
does not call ``Gtk.Application.__init__``, so no display is needed.
"""

from __future__ import annotations

from typing import Callable

from lurkn.app import STATE_FAN, LurkNotesApp
from lurkn.deck import DeckMachine
from lurkn.events import DeckChanged
from lurkn.notes import Note
from lurkn.testhooks import TestHooks
from lurkn.undo import UndoController


def make_note(
    note_id: str,
    text: str = "",
    *,
    created: float = 1.0,
    updated: float | None = None,
) -> Note:
    """A note with deterministic timestamps (an untouched note by default)."""
    return Note(
        id=note_id,
        text=text,
        created=created,
        updated=created if updated is None else updated,
    )


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
    """Both the note page and the fan surface the app-level tests touch."""

    def __init__(self) -> None:
        self.note = FakeNoteView()
        self.visible = False
        self.shown: list[tuple[str, object]] = []
        self.refreshed: list[tuple[list[str], str | None]] = []
        self.save_failed: list[bool] = []
        self.toast_visible = False
        self.toast_shows = 0

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
        self.refreshed.append(([note.id for note in notes], active_id))

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


def make_app(
    notes: list[Note],
    *,
    read_only: bool = False,
    overwrite_blocked: bool = False,
    session_ids: set[str] | None = None,
    store=None,
    scheduler: FakeScheduler | None = None,
) -> LurkNotesApp:
    """A real app object with fake collaborators, without GTK initialization.

    ``app.panel``, ``app.store``, ``app.scheduler`` expose the fakes for
    assertions. The deck starts in ``fan`` because these tests drive app
    methods directly rather than the hover machine.
    """
    app = LurkNotesApp.__new__(LurkNotesApp)
    app.notes = list(notes)
    app.session_ids = set(session_ids or ())
    app.current_id = None
    app.shutdown_done = False
    app.deck = DeckMachine(lambda _delay, _callback: 0, lambda _handle: None)
    app.deck.state = STATE_FAN
    app.save_source = 0
    app.unsaved = False
    app.read_only = read_only
    app.overwrite_blocked = overwrite_blocked
    app.panel = FakePanel()
    app.store = store or FakeStore()
    app.x11 = None
    app._workarea = None
    app._load_result = None
    app._load_error = None
    app.all_notes = None
    app._focus_guard = None
    app._all_notes_focus_guard = None
    app._onboarding_pending = False
    app._hooks = TestHooks(app)
    app.deck_changed_event = DeckChanged()
    app._retrier = NullRetrier()
    app.scheduler = scheduler or FakeScheduler()
    app._undo = UndoController(
        timeout_ms=10_000,
        schedule=app.scheduler,
        cancel=app.scheduler.cancel,
        on_expire=app._on_undo_expired,
    )
    return app
