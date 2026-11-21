"""The sync controller's threading and retry behaviour, without GTK.

``syncui`` reaches for GLib only inside ``_idle_add``, so the retry backoff,
the periodic timer and the "one pass at a time" rule can be tested with a fake
scheduler — which is where the bugs actually live.
"""

from __future__ import annotations

import threading

import pytest

from lurkn.syncui import PULL_INTERVAL_MS, RETRY_DELAYS_MS, SyncController
from lurkn.syncer import IDLE, NEEDS_ATTENTION, SyncResult


class FakeScheduler:
    def __init__(self) -> None:
        self.timers: list[tuple[int, object]] = []
        self.cancelled: list[object] = []

    def __call__(self, delay: int, callback):
        handle = object()
        self.timers.append((delay, callback))
        return handle

    def cancel(self, handle) -> None:
        self.cancelled.append(handle)

    def fire(self, index: int) -> None:
        _delay, callback = self.timers[index]
        callback()


class FakeSyncer:
    def __init__(self, result: SyncResult | None = None) -> None:
        self.calls = 0
        self.result = result or SyncResult(state=IDLE)
        self.gate: threading.Event | None = None

    def run_once(self) -> SyncResult:
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(timeout=5)
        return self.result


@pytest.fixture(autouse=True)
def immediate_idle(monkeypatch):
    """Run the worker's result callback inline instead of via GLib."""
    monkeypatch.setattr("lurkn.syncui._idle_add", lambda callback: callback())


def make_controller(syncer: FakeSyncer, scheduler: FakeScheduler, results: list) -> SyncController:
    return SyncController(
        syncer,  # type: ignore[arg-type]
        on_result=results.append,
        schedule=scheduler,
        cancel=scheduler.cancel,
    )


def join(controller: SyncController) -> None:
    thread = getattr(controller, "_thread", None)
    if thread is not None:
        thread.join(timeout=5)


def test_start_runs_a_pass_and_schedules_the_periodic_pull() -> None:
    scheduler = FakeScheduler()
    syncer = FakeSyncer()
    controller = make_controller(syncer, scheduler, [])
    controller.sync_now()
    join(controller)

    controller.start()

    assert syncer.calls == 2
    assert scheduler.timers[0][0] == PULL_INTERVAL_MS


def test_the_pull_timer_reschedules_itself() -> None:
    scheduler = FakeScheduler()
    syncer = FakeSyncer()
    controller = make_controller(syncer, scheduler, [])
    controller.start()
    join(controller)

    scheduler.fire(0)
    join(controller)

    assert syncer.calls == 2
    assert len(scheduler.timers) == 2


def test_a_failure_schedules_a_retry_with_backoff() -> None:
    scheduler = FakeScheduler()
    syncer = FakeSyncer(SyncResult(state=NEEDS_ATTENTION, error="offline"))
    results: list[SyncResult] = []
    controller = make_controller(syncer, scheduler, results)

    controller.sync_now()
    join(controller)

    assert results[-1].state == NEEDS_ATTENTION
    assert scheduler.timers[0][0] == RETRY_DELAYS_MS[0]


def test_success_resets_the_backoff() -> None:
    scheduler = FakeScheduler()
    syncer = FakeSyncer(SyncResult(state=NEEDS_ATTENTION))
    controller = make_controller(syncer, scheduler, [])

    controller.sync_now()
    join(controller)
    controller.sync_now()
    join(controller)
    # Only the first retry is pending while one is already scheduled.
    assert len(scheduler.timers) == 1

    syncer.result = SyncResult(state=IDLE)
    scheduler.fire(0)  # the pending retry fires a success
    join(controller)

    assert controller._failures == 0


def test_a_second_kick_does_not_start_a_parallel_pass() -> None:
    scheduler = FakeScheduler()
    syncer = FakeSyncer()
    syncer.gate = threading.Event()
    controller = make_controller(syncer, scheduler, [])

    controller.sync_now()
    controller.sync_now()  # while the first is still running
    syncer.gate.set()
    join(controller)

    assert syncer.calls == 1


def test_stop_cancels_pending_timers_and_blocks_new_passes() -> None:
    scheduler = FakeScheduler()
    syncer = FakeSyncer()
    controller = make_controller(syncer, scheduler, [])
    controller.start()
    join(controller)

    controller.stop()
    controller.sync_now()

    assert len(scheduler.cancelled) == 1
    assert syncer.calls == 1
