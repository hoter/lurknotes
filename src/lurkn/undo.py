"""The one-slot, memory-only delete undo (spec §4.5, §5.4, §10).

Deleting a note writes the shortened deck immediately. Undo keeps exactly one
deleted note and one timer in memory; a second delete finalises the first and
restarts the countdown. Nothing here touches the store, so a restart can never
resurrect a note.

Timers are injected through :mod:`lurkn.timers`, like the deck and focus
machines, so the countdown is unit-tested on a fake clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .notes import Note
from .timers import Cancel, Handle, Schedule

UNDO_TIMEOUT_MS = 10_000  # spec §4.5, §7.1


@dataclass
class DeletedNote:
    """One deleted note plus everything undo needs to put it back.

    ``session_member`` is captured at delete time: an undone untouched note
    must still follow ticket 03's "discard when the session created it" rule.
    """

    note: Note
    index: int
    session_member: bool


class UndoController:
    """Exactly one pending delete, with a single timer.

    ``start`` finalises any previous payload (spec §10: a second delete fixes
    the first) and restarts the countdown. The payload is memory-only; nothing
    here is persisted and a restart therefore cannot undo anything.
    """

    def __init__(
        self,
        *,
        timeout_ms: int,
        schedule: Schedule,
        cancel: Cancel,
        on_expire: Callable[[], None] | None = None,
    ) -> None:
        self._timeout_ms = timeout_ms
        self._schedule = schedule
        self._cancel = cancel
        self._on_expire = on_expire
        self._handle: Handle | None = None
        self.pending: DeletedNote | None = None

    def start(self, deleted: DeletedNote) -> None:
        self.finalize()
        self.pending = deleted
        self._handle = self._schedule(self._timeout_ms, self._expire)

    def take(self) -> DeletedNote | None:
        """Hand the payload back once and cancel its timer."""
        if self.pending is None:
            return None
        self._cancel_timer()
        deleted, self.pending = self.pending, None
        return deleted

    def finalize(self) -> None:
        """Drop the payload; after this it can no longer be undone."""
        self._cancel_timer()
        self.pending = None

    def _cancel_timer(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        self._cancel(handle)

    def _expire(self) -> bool:
        self._handle = None
        self.pending = None
        if self._on_expire is not None:
            self._on_expire()
        return False
