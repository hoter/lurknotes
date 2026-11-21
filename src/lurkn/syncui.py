"""Sync status inside the app: wire the pure Syncer to GTK and to saves.

The pure pieces (``Syncer``, ``Queue``, ``SyncSettings``) know nothing about
threads or GTK. This controller is the seam:

* a **background thread** makes the blocking HTTP call, because the deck must
  never freeze on a slow network (a 15 s socket timeout on the main loop would
  be 15 s of an unresponsive strip);
* results come back to the main loop through ``GLib.idle_add``;
* a periodic pull is a plain GLib timer;
* when sync is off, none of this is constructed and no network module is
  imported — the "no sockets" acceptance check keeps holding.

The controller only ever *reads* the deck to fill a change; writing pulled
changes back into ``notes.json`` is the app's job, because it owns the note
list and the save debounce.
"""

from __future__ import annotations

import threading
from typing import Callable

from .syncer import IDLE, NEEDS_ATTENTION, SyncResult, Syncer, now_stamp

PULL_INTERVAL_MS = 5 * 60 * 1000
# Backoff for a failed pass: 5 s, 15 s, then every 60 s.
RETRY_DELAYS_MS = (5000, 15000, 60000)


class SyncController:
    """Run the Syncer off the main loop and report state changes."""

    def __init__(
        self,
        syncer: Syncer,
        *,
        on_result: Callable[[SyncResult], None],
        schedule: Callable[[int, Callable[[], None]], object],
        cancel: Callable[[object], None],
    ) -> None:
        self._syncer = syncer
        self._on_result = on_result
        self._schedule = schedule
        self._cancel = cancel
        self._thread: threading.Thread | None = None
        self._pull_handle: object | None = None
        self._retry_handle: object | None = None
        self._failures = 0
        self._last_result = SyncResult(state=IDLE)
        self._stopped = False

    @property
    def syncer(self) -> Syncer:
        """The loop itself; the app queues changes through it."""
        return self._syncer

    @property
    def last_result(self) -> SyncResult:
        return self._last_result

    def start(self) -> None:
        if self._stopped:
            return
        self.sync_now()
        self._pull_handle = self._schedule(PULL_INTERVAL_MS, self._on_pull_timer)

    def stop(self) -> None:
        self._stopped = True
        for handle in (self._pull_handle, self._retry_handle):
            if handle is not None:
                self._cancel(handle)
        self._pull_handle = None
        self._retry_handle = None

    def sync_now(self) -> None:
        """Kick a pass unless one is already running."""
        if self._stopped or (self._thread is not None and self._thread.is_alive()):
            return

        def work() -> None:
            result = self._syncer.run_once()
            self._deliver(result)

        self._thread = threading.Thread(target=work, name="lurknotes-sync", daemon=True)
        self._thread.start()

    def _deliver(self, result: SyncResult) -> None:
        # Runs on the worker thread; hand the result to the main loop.
        def apply() -> bool:
            self._last_result = result
            self._on_result(result)
            if result.state == NEEDS_ATTENTION:
                self._schedule_retry()
            else:
                self._failures = 0
            return False

        _idle_add(apply)

    def _schedule_retry(self) -> None:
        if self._retry_handle is not None:
            return
        delay = RETRY_DELAYS_MS[min(self._failures, len(RETRY_DELAYS_MS) - 1)]
        self._failures += 1
        self._retry_handle = self._schedule(delay, self._on_retry_timer)

    def _on_retry_timer(self) -> None:
        self._retry_handle = None
        self.sync_now()

    def _on_pull_timer(self) -> None:
        self._pull_handle = self._schedule(PULL_INTERVAL_MS, self._on_pull_timer)
        self.sync_now()


def _idle_add(callback: Callable[[], bool]) -> None:
    # Imported here so importing this module never pulls GLib into a test that
    # only wants the controller's threading behaviour.
    from gi.repository import GLib

    GLib.idle_add(callback)


__all__ = ["NEEDS_ATTENTION", "PULL_INTERVAL_MS", "SyncController", "now_stamp"]
