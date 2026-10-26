"""Retry policy for failed saves: bounded backoff, no polling while clean."""

from __future__ import annotations

from lurkn.retry import Retrier

DELAYS = (1000, 2000, 5000)


class FakeScheduler:
    """Records timers; nothing fires until the test says so."""

    def __init__(self) -> None:
        self.next_id = 1
        self.jobs: dict[int, tuple[int, object]] = {}
        self.cancelled: list[int] = []

    def schedule(self, delay: int, callback) -> int:
        handle = self.next_id
        self.next_id += 1
        self.jobs[handle] = (delay, callback)
        return handle

    def cancel(self, handle: int) -> None:
        self.cancelled.append(handle)
        self.jobs.pop(handle, None)

    def fire_next(self) -> None:
        handle, (_delay, callback) = min(
            self.jobs.items(), key=lambda item: (item[1][0], item[0])
        )
        del self.jobs[handle]
        callback()

    @property
    def delays(self) -> list[int]:
        return [delay for delay, _callback in self.jobs.values()]


def test_a_failed_save_schedules_one_bounded_retry():
    scheduler = FakeScheduler()
    attempts: list[int] = []
    retrier = Retrier(
        lambda: attempts.append(1),
        schedule=scheduler.schedule,
        cancel=scheduler.cancel,
        delays=DELAYS,
    )

    retrier.failed()
    retrier.failed()  # a second failing save must not stack timers

    assert scheduler.delays == [1000]
    assert attempts == []


def test_backoff_grows_and_stops_at_the_last_delay():
    scheduler = FakeScheduler()
    attempts: list[int] = []

    def attempt() -> None:
        attempts.append(1)
        retrier.failed()  # every retry fails in this test

    retrier = Retrier(
        attempt,
        schedule=scheduler.schedule,
        cancel=scheduler.cancel,
        delays=DELAYS,
    )

    retrier.failed()
    assert scheduler.delays == [1000]
    scheduler.fire_next()
    assert scheduler.delays == [2000]
    scheduler.fire_next()
    assert scheduler.delays == [5000]
    scheduler.fire_next()
    assert scheduler.delays == [5000]
    assert len(attempts) == 3


def test_success_cancels_the_timer_and_resets_the_backoff():
    scheduler = FakeScheduler()
    retrier = Retrier(
        lambda: None,
        schedule=scheduler.schedule,
        cancel=scheduler.cancel,
        delays=DELAYS,
    )

    retrier.failed()
    retrier.succeeded()

    assert scheduler.delays == []
    assert len(scheduler.cancelled) == 1

    retrier.failed()
    assert scheduler.delays == [1000]


def test_stop_cancels_without_scheduling_anything_else():
    scheduler = FakeScheduler()
    retrier = Retrier(
        lambda: None,
        schedule=scheduler.schedule,
        cancel=scheduler.cancel,
        delays=DELAYS,
    )

    retrier.failed()
    retrier.stop()
    retrier.stop()

    assert scheduler.delays == []
    assert len(scheduler.cancelled) == 1


def test_no_timer_exists_while_there_is_nothing_to_save():
    scheduler = FakeScheduler()
    Retrier(
        lambda: None,
        schedule=scheduler.schedule,
        cancel=scheduler.cancel,
        delays=DELAYS,
    )

    assert scheduler.jobs == {}
