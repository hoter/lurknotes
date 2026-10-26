"""Bounded retry policy for failed saves.

The app owns the actual save and the UI indicator; this module only decides
when the next attempt happens. A retry timer exists only while a save is
dirty: no timer is created on the happy path, and a successful save or
shutdown cancels the pending one.
"""

from __future__ import annotations

from typing import Callable, Sequence

# 1 s, 2 s, 5 s, 15 s, then every 30 s. Long enough not to spin on a full or
# read-only disk, short enough that restoring permissions heals the deck soon.
RETRY_DELAYS_MS: tuple[int, ...] = (1000, 2000, 5000, 15000, 30000)


class Retrier:
    """Schedule one retry at a time, backing off to a bounded delay."""

    def __init__(
        self,
        attempt: Callable[[], None],
        *,
        schedule: Callable[[int, Callable[[], None]], object],
        cancel: Callable[[object], None],
        delays: Sequence[int] = RETRY_DELAYS_MS,
    ) -> None:
        if not delays:
            raise ValueError("at least one retry delay is required")
        self._attempt = attempt
        self._schedule = schedule
        self._cancel = cancel
        self._delays = tuple(delays)
        self._handle: object | None = None
        self._failures = 0

    def failed(self) -> None:
        """A save failed: ensure exactly one retry timer is pending."""
        if self._handle is not None:
            return
        delay = self._delays[min(self._failures, len(self._delays) - 1)]
        self._failures += 1
        self._handle = self._schedule(delay, self._fire)

    def succeeded(self) -> None:
        """The deck is clean again: cancel the timer and reset the backoff."""
        self.stop()
        self._failures = 0

    def stop(self) -> None:
        """Cancel a pending retry; safe to call more than once."""
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        self._cancel(handle)

    def _fire(self) -> None:
        # The scheduler has already removed its source; the attempt is
        # expected to call failed() or succeeded() when it finishes.
        self._handle = None
        self._attempt()
