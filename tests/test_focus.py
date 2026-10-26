"""Focus decision after activation (spec §9.5, §7.1).

The guard only decides whether focus arrived within 150 ms and tells the app
to show the "Click to type" hint. Timers are injected, so no display or sleep.
"""

from __future__ import annotations

from lurkn.focus import FOCUS_CHECK_MS, FocusGuard


class FakeClock:
    def __init__(self) -> None:
        self.now = 0
        self._next = 1
        self._timers: dict[int, tuple[int, object]] = {}

    def schedule(self, delay_ms: int, callback) -> int:
        handle = self._next
        self._next += 1
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


def test_the_check_waits_the_spec_150_ms() -> None:
    clock = FakeClock()
    hints: list[bool] = []
    guard = FocusGuard(
        clock.schedule,
        clock.cancel,
        is_focused=lambda: True,
        on_missing=lambda: hints.append(True),
    )

    guard.watch()
    clock.advance(FOCUS_CHECK_MS - 1)
    assert hints == []

    clock.advance(1)
    assert hints == []


def test_missing_focus_shows_the_hint_once() -> None:
    clock = FakeClock()
    hints: list[bool] = []
    guard = FocusGuard(
        clock.schedule,
        clock.cancel,
        is_focused=lambda: False,
        on_missing=lambda: hints.append(True),
    )

    guard.watch()
    clock.advance(FOCUS_CHECK_MS)

    assert hints == [True]


def test_a_second_activation_replaces_the_pending_check() -> None:
    clock = FakeClock()
    focused = False
    hints: list[bool] = []
    guard = FocusGuard(
        clock.schedule,
        clock.cancel,
        is_focused=lambda: focused,
        on_missing=lambda: hints.append(True),
    )

    guard.watch()
    clock.advance(FOCUS_CHECK_MS // 2)
    focused = True
    guard.watch()
    clock.advance(FOCUS_CHECK_MS)

    assert hints == []


def test_focus_arriving_before_the_deadline_cancels_the_hint() -> None:
    clock = FakeClock()
    hints: list[bool] = []
    guard = FocusGuard(
        clock.schedule,
        clock.cancel,
        is_focused=lambda: False,
        on_missing=lambda: hints.append(True),
    )

    guard.watch()
    guard.focus_arrived()
    clock.advance(FOCUS_CHECK_MS * 2)

    assert hints == []


def test_clear_cancels_without_showing_anything() -> None:
    clock = FakeClock()
    hints: list[bool] = []
    guard = FocusGuard(
        clock.schedule,
        clock.cancel,
        is_focused=lambda: False,
        on_missing=lambda: hints.append(True),
    )

    guard.watch()
    guard.clear()
    clock.advance(FOCUS_CHECK_MS * 2)

    assert hints == []
