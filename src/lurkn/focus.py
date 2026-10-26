"""The 150 ms focus decision after activation (spec §9.5, §7.1).

``present()`` is a request, not a guarantee: focus can be withheld by the
shell, a keyboard grab or the overview. The guard waits 150 ms, reads the
authoritative ``_NET_ACTIVE_WINDOW`` (through the injected ``is_focused``
callable — ``Gtk.Window.is_active()`` lies after an unmap, PLATFORM §4), and
asks the app to show the "Click to type" hint when focus did not arrive.

Timers are injected so the decision is unit-tested on a fake clock.
"""

from __future__ import annotations

from typing import Callable

from .timers import Cancel, Handle, Schedule

FOCUS_CHECK_MS = 150


class FocusGuard:
    def __init__(
        self,
        schedule: Schedule,
        cancel: Cancel,
        *,
        is_focused: Callable[[], bool],
        on_missing: Callable[[], None],
        delay_ms: int = FOCUS_CHECK_MS,
    ) -> None:
        self._schedule = schedule
        self._cancel = cancel
        self._is_focused = is_focused
        self._on_missing = on_missing
        self._delay_ms = delay_ms
        self._handle: Handle | None = None

    def watch(self) -> None:
        """Start (or restart) the check for one activation attempt."""
        self.clear()
        self._handle = self._schedule(self._delay_ms, self._fired)

    def focus_arrived(self) -> None:
        """Focus arrived normally; the hint is not needed any more."""
        self.clear()

    def clear(self) -> None:
        """Cancel the pending check without a decision."""
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        self._cancel(handle)

    def _fired(self) -> None:
        self._handle = None
        if not self._is_focused():
            self._on_missing()
