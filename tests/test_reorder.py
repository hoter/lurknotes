"""Drag reorder: threshold, target mapping, cancel/no-op, persistence (§4.4, §7.2).

The geometry and the drag session are pure Python, so the whole decision can be
tested without a display. The app-level half drives the real ``reorder_note``
method with a fake panel and store; the gesture itself is covered by
``scripts/smoke_drag.py`` through a real X11 press/move/release.
"""

from __future__ import annotations

from pathlib import Path

from lurkn.app import STATE_FAN, LurkNotesApp
from lurkn.deck import DeckMachine
from lurkn.events import DeckChanged
from lurkn.notes import Note
from lurkn.reorder import (
    CANCEL,
    CLICK,
    REORDER,
    DRAG_THRESHOLD_PX,
    DragSession,
    is_drag,
    target_index,
)
from lurkn.store import Store


# -- pure: one gesture, click vs drag -----------------------------------


def test_a_short_move_is_a_click_and_five_pixels_is_a_drag() -> None:
    assert is_drag(0.0, 0.0) is False
    assert is_drag(4.9, 0.0) is False
    assert is_drag(0.0, -4.9) is False
    # Both axes are still inside 5 px: a small diagonal jitter is a click.
    assert is_drag(4.9, 4.9) is False
    assert is_drag(5.0, 0.0) is True
    assert is_drag(0.0, -5.0) is True
    assert DRAG_THRESHOLD_PX == 5.0


# -- pure: real row bounds, not a hardcoded height ----------------------


def test_target_index_follows_the_rendered_row_spans() -> None:
    # Deliberately unequal heights: a fixed row height would pick the wrong row.
    spans = [(0.0, 20.0), (20.0, 50.0), (50.0, 110.0)]

    assert target_index(-5.0, spans) == 0
    assert target_index(0.0, spans) == 0
    assert target_index(19.9, spans) == 0
    assert target_index(25.0, spans) == 1
    assert target_index(49.9, spans) == 1
    assert target_index(80.0, spans) == 2
    assert target_index(10_000.0, spans) == 2


def test_target_index_clamps_to_the_row_list() -> None:
    spans = [(100.0, 120.0), (120.0, 140.0)]

    assert target_index(0.0, spans) == 0
    assert target_index(999.0, spans) == 1
    assert target_index(0.0, []) is None


def test_a_pointer_in_a_gap_picks_the_nearer_row() -> None:
    spans = [(0.0, 20.0), (40.0, 60.0)]

    assert target_index(38.0, spans) == 1
    assert target_index(22.0, spans) == 0


# -- pure: drag session --------------------------------------------------


def make_session(
    note_id: str = "note-a", source_index: int = 0
) -> DragSession:
    return DragSession(note_id, source_index)


def test_the_session_stays_a_click_until_the_threshold_is_crossed() -> None:
    session = make_session()

    assert session.update(2.0, 1.0) is False
    assert session.active is False

    result = session.finish(
        released_inside=True,
        released_on_tab=True,
        pointer_y=10.0,
        spans=[(0.0, 20.0), (20.0, 40.0)],
    )

    assert result.kind == CLICK
    assert result.note_id == "note-a"
    assert result.target is None


def test_releasing_outside_the_deck_cancels_an_active_drag() -> None:
    session = make_session(source_index=0)
    assert session.update(0.0, 40.0) is True

    result = session.finish(
        released_inside=False,
        released_on_tab=False,
        pointer_y=400.0,
        spans=[(0.0, 20.0), (20.0, 40.0)],
    )

    assert result.kind == CANCEL
    assert result.target is None


def test_an_active_drag_maps_the_release_point_to_a_target() -> None:
    session = make_session("note-a", 0)
    session.update(0.0, 80.0)

    result = session.finish(
        released_inside=True,
        released_on_tab=False,
        pointer_y=80.0,
        spans=[(0.0, 20.0), (20.0, 50.0), (50.0, 110.0)],
    )

    assert result.kind == REORDER
    assert result.source == 0
    assert result.target == 2


def test_an_unchanged_target_is_reported_and_the_app_keeps_it_a_no_op() -> None:
    session = make_session("note-b", 1)
    session.update(0.0, 12.0)

    result = session.finish(
        released_inside=True,
        released_on_tab=False,
        pointer_y=25.0,
        spans=[(0.0, 20.0), (20.0, 50.0), (50.0, 110.0)],
    )

    assert result.kind == REORDER
    assert result.target == result.source


# -- app: reorder, save, read-only, no-op -------------------------------


class FakePanel:
    def __init__(self) -> None:
        self.refreshed: list[tuple[list[str], str | None]] = []
        self.save_failed: list[bool] = []

    def refresh_notes(self, notes, active_id) -> None:
        self.refreshed.append(([note.id for note in notes], active_id))

    def show_fan(self, notes) -> None:
        self.refreshed.append(([note.id for note in notes], None))

    def show_save_failed(self, failed: bool) -> None:
        self.save_failed.append(failed)

    def get_surface(self):
        return None


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
    overwrite_blocked: bool = False,
    store=None,
) -> tuple[LurkNotesApp, FakePanel, FakeStore]:
    app = LurkNotesApp.__new__(LurkNotesApp)
    app.notes = list(notes)
    app.session_ids = set()
    app.current_id = None
    app.deck = DeckMachine(lambda _delay, _callback: 0, lambda _handle: None)
    app.deck.state = STATE_FAN
    app.save_source = 0
    app.unsaved = False
    app.read_only = read_only
    app.overwrite_blocked = overwrite_blocked
    app.panel = FakePanel()
    app.store = store or FakeStore()
    app.x11 = None
    app._test_dump_path = None
    app._test_type = None
    app.deck_changed_event = DeckChanged()
    app._retrier = NullRetrier()
    return app, app.panel, app.store


def test_reordering_moves_the_note_to_the_target_and_saves_it_once() -> None:
    first, second, third = (
        make_note("first"),
        make_note("second"),
        make_note("third"),
    )
    app, panel, store = make_app([first, second, third])
    notified: list[bool] = []
    app.deck_changed_event.subscribe(lambda: notified.append(True))

    assert app.reorder_note("first", 2) is True

    assert [note.id for note in app.notes] == ["second", "third", "first"]
    assert store.saved == [["second", "third", "first"]]
    assert notified == [True]
    # The fan/rail rebuild is the app's job, after the gesture has ended.
    assert panel.refreshed[-1] == (["second", "third", "first"], None)


def test_reordering_to_the_same_index_is_a_no_op() -> None:
    app, panel, store = make_app(
        [make_note("first"), make_note("second"), make_note("third")]
    )

    assert app.reorder_note("second", 1) is False

    assert [note.id for note in app.notes] == ["first", "second", "third"]
    assert store.saved == []
    assert panel.refreshed == []


def test_an_unknown_note_is_ignored() -> None:
    app, _panel, store = make_app([make_note("first")])

    assert app.reorder_note("missing", 0) is False
    assert store.saved == []


def test_the_target_is_clamped_to_the_deck() -> None:
    app, _panel, _store = make_app(
        [make_note("first"), make_note("second"), make_note("third")]
    )

    assert app.reorder_note("first", 99) is True
    assert [note.id for note in app.notes] == ["second", "third", "first"]

    assert app.reorder_note("first", -5) is True
    assert [note.id for note in app.notes] == ["first", "second", "third"]


def test_a_read_only_deck_reorders_in_memory_without_writing() -> None:
    app, panel, store = make_app(
        [make_note("first"), make_note("second")], read_only=True
    )

    assert app.reorder_note("first", 1) is True

    assert [note.id for note in app.notes] == ["second", "first"]
    assert store.saved == []
    assert panel.save_failed == []
    assert app.unsaved is False


def test_an_unconfirmed_corrupt_deck_reorders_in_memory_without_writing() -> None:
    app, _panel, store = make_app(
        [make_note("first"), make_note("second")], overwrite_blocked=True
    )

    assert app.reorder_note("first", 1) is True

    assert [note.id for note in app.notes] == ["second", "first"]
    assert store.saved == []


def test_reorder_persists_through_the_real_store(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    notes = [make_note("first", "one"), make_note("second", "two")]
    Store(path).save(notes)
    store = Store(path)
    loaded = store.load().notes
    app, _panel, _store = make_app(loaded, store=store)

    assert app.reorder_note("first", 1) is True

    reloaded = Store(path).load()
    assert [note.id for note in reloaded.notes] == ["second", "first"]
    assert [note.text for note in reloaded.notes] == ["two", "one"]
