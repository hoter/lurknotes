"""Deck state machine: hover, peek, collapse (spec §3, §7.1, §7.4).

Timers are injected, so the whole machine runs on a fake clock: no sleeps, no
display, and every delay can be asserted exactly.
"""

from __future__ import annotations

from lurkn.deck import (
    COLLAPSE_DELAY_MS,
    FAN_DELAY_MS,
    PEEK_DELAY_MS,
    STATE_FAN,
    STATE_OPEN,
    STATE_STRIP,
    DeckMachine,
)


class FakeClock:
    """Scheduler with a virtual millisecond clock."""

    def __init__(self) -> None:
        self.now = 0
        self._next_handle = 1
        self._timers: dict[int, tuple[int, object]] = {}

    def schedule(self, delay_ms: int, callback) -> int:
        handle = self._next_handle
        self._next_handle += 1
        self._timers[handle] = (self.now + delay_ms, callback)
        return handle

    def cancel(self, handle: int) -> None:
        self._timers.pop(handle, None)

    def advance(self, milliseconds: int) -> None:
        target = self.now + milliseconds
        while True:
            due = [
                (when, handle, callback)
                for handle, (when, callback) in self._timers.items()
                if when <= target
            ]
            if not due:
                break
            when, handle, callback = min(due)
            del self._timers[handle]
            self.now = when
            callback()
        self.now = target


def machine(clock: FakeClock, **kwargs):
    return DeckMachine(clock.schedule, clock.cancel, **kwargs)


def test_strip_expands_only_after_the_hover_delay() -> None:
    clock = FakeClock()
    deck = machine(clock)
    assert deck.state == STATE_STRIP

    deck.hover_enter()
    clock.advance(FAN_DELAY_MS - 1)
    assert deck.state == STATE_STRIP

    clock.advance(1)
    assert deck.state == STATE_FAN


def test_leaving_the_strip_before_the_delay_cancels_the_expand() -> None:
    clock = FakeClock()
    deck = machine(clock)

    deck.hover_enter()
    clock.advance(FAN_DELAY_MS // 2)
    deck.hover_leave()
    clock.advance(FAN_DELAY_MS * 4)

    assert deck.state == STATE_STRIP


def test_hovering_the_strip_again_uses_one_timer_not_two() -> None:
    clock = FakeClock()
    deck = machine(clock)

    deck.hover_enter()
    clock.advance(FAN_DELAY_MS - 10)
    deck.hover_enter()
    clock.advance(10)

    # A second enter must not postpone the fan by another full delay.
    assert deck.state == STATE_FAN


def test_fan_reports_the_panel_as_visible() -> None:
    clock = FakeClock()
    deck = machine(clock)
    assert deck.panel_visible is False

    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    assert deck.panel_visible is True


def test_leaving_the_fan_collapses_after_the_delay() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)

    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS - 1)
    assert deck.state == STATE_FAN

    clock.advance(1)
    assert deck.state == STATE_STRIP


def test_returning_to_the_deck_cancels_a_pending_collapse() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)

    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS // 2)
    deck.hover_enter()
    clock.advance(COLLAPSE_DELAY_MS)

    assert deck.state == STATE_FAN


def test_header_close_collapses_immediately_without_a_timer() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)

    assert deck.collapse() is True
    assert deck.state == STATE_STRIP
    assert deck.panel_visible is False


def test_header_close_never_discards_an_open_note() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.open("note-1")
    assert deck.state == STATE_OPEN

    assert deck.collapse() is False
    assert deck.state == STATE_OPEN


def test_hover_tab_shows_a_peek_after_the_delay() -> None:
    clock = FakeClock()
    clock.now = 100
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)

    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS - 1)
    assert deck.peek_id is None

    clock.advance(1)
    assert deck.peek_id == "note-a"


def test_hovering_the_same_tab_again_does_not_restart_the_peek() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS)

    deck.hover_tab("note-a")
    assert deck.peek_id == "note-a"


def test_moving_across_tabs_hides_the_old_peek_and_shows_only_the_new_one() -> None:
    clock = FakeClock()
    seen: list[str | None] = []
    deck = machine(clock, on_peek=seen.append, on_unpeek=lambda: seen.append(None))
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS)
    assert deck.peek_id == "note-a"

    deck.hover_tab("note-b")
    # The old peek goes away at once; the new one waits its 150 ms.
    assert deck.peek_id is None
    clock.advance(PEEK_DELAY_MS)
    assert deck.peek_id == "note-b"
    assert seen == ["note-a", None, "note-b"]


def test_a_leave_from_the_tab_we_just_left_does_not_cancel_the_new_peek() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS)

    # GTK can deliver enter(new) before leave(old) while crossing tabs.
    deck.hover_tab("note-b")
    deck.hover_tab_leave("note-a")
    clock.advance(PEEK_DELAY_MS)

    assert deck.peek_id == "note-b"


def test_leaving_the_tab_cancels_a_pending_peek() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)

    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS // 2)
    deck.hover_tab_leave("note-a")
    clock.advance(PEEK_DELAY_MS * 4)

    assert deck.peek_id is None


def test_leaving_the_fan_hides_the_peek_before_collapsing() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS)

    deck.hover_leave()
    assert deck.peek_id is None
    assert deck.state == STATE_FAN
    clock.advance(COLLAPSE_DELAY_MS)
    assert deck.state == STATE_STRIP


def test_collapsing_cancels_a_pending_peek() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS // 2)

    deck.collapse()
    clock.advance(PEEK_DELAY_MS * 4)

    assert deck.peek_id is None
    assert deck.state == STATE_STRIP


def test_a_pinned_leave_hides_the_peek_but_keeps_the_fan() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS)

    deck.hover_leave(allow_collapse=False)
    clock.advance(COLLAPSE_DELAY_MS * 4)

    assert deck.state == STATE_FAN
    assert deck.peek_id is None

    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS)
    assert deck.state == STATE_STRIP


def test_an_open_note_never_collapses_on_pointer_leave() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.open("note-a")

    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS * 4)

    assert deck.state == STATE_OPEN


def test_peeks_are_fan_only() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.open("note-a")

    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS * 4)

    assert deck.peek_id is None


def test_escape_closes_an_open_note_then_collapses_a_focused_fan() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.open("note-a")

    assert deck.escape(panel_focused=True) is True
    assert deck.state == STATE_FAN
    assert deck.escape(panel_focused=True) is True
    assert deck.state == STATE_STRIP
    assert deck.escape(panel_focused=True) is False


def test_escape_without_panel_focus_does_not_collapse() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)

    assert deck.escape(panel_focused=False) is False
    assert deck.state == STATE_FAN


def test_leaving_after_open_keeps_the_panel_mapped() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.open("note-a")
    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS * 2)

    assert deck.panel_visible is True
    assert deck.state == STATE_OPEN


def test_closing_an_open_note_returns_to_the_fan_without_collapsing() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.open("note-a")

    assert deck.close() is True
    assert deck.state == STATE_FAN
    assert deck.panel_visible is True

    clock.advance(COLLAPSE_DELAY_MS * 4)
    assert deck.state == STATE_FAN


def test_collapse_notifies_the_panel_callbacks_once() -> None:
    clock = FakeClock()
    events: list[str] = []
    deck = machine(
        clock,
        on_panel_shown=lambda: events.append("shown"),
        on_panel_hidden=lambda: events.append("hidden"),
    )

    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)

    assert events == ["shown", "hidden", "shown"]


def test_starting_a_drag_hides_the_peek_and_cancels_a_pending_collapse() -> None:
    clock = FakeClock()
    seen: list[str | None] = []
    deck = machine(clock, on_unpeek=lambda: seen.append(None))
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS)
    assert deck.peek_id == "note-a"

    deck.hover_leave()
    assert deck.state == STATE_FAN
    deck.drag_begin()

    assert deck.dragging is True
    assert deck.peek_id is None
    assert seen == [None]
    clock.advance(COLLAPSE_DELAY_MS * 4)
    assert deck.state == STATE_FAN


def test_leaving_the_deck_mid_drag_never_collapses_it() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.drag_begin()

    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS * 4)

    assert deck.state == STATE_FAN
    assert deck.panel_visible is True


def test_a_drag_blocks_new_peeks_until_it_ends() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.drag_begin()

    deck.hover_tab("note-a")
    clock.advance(PEEK_DELAY_MS * 4)
    assert deck.peek_id is None

    deck.drag_end()
    deck.hover_tab("note-b")
    clock.advance(PEEK_DELAY_MS)
    assert deck.peek_id == "note-b"


def test_after_drag_end_a_normal_hover_leave_collapses_again() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.drag_begin()

    deck.drag_end()
    deck.hover_leave()
    clock.advance(COLLAPSE_DELAY_MS)

    assert deck.state == STATE_STRIP


def test_shutdown_cancels_every_pending_timer() -> None:
    clock = FakeClock()
    deck = machine(clock)
    deck.hover_enter()
    clock.advance(FAN_DELAY_MS)
    deck.hover_tab("note-a")

    deck.stop()
    clock.advance(COLLAPSE_DELAY_MS * 4)

    assert deck.state == STATE_FAN
    assert deck.peek_id is None
