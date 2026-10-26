"""The deck state machine: strip -> fan -> peek/open (spec §3, §7.1, §7.4).

Pure Python, no GTK. Timers are injected (``schedule``/``cancel``), which keeps
the hover delays testable on a fake clock and lets the app use ``GLib``.

The machine owns three facts and nothing else:

* ``state`` — ``strip``, ``fan`` or ``open``;
* ``peek_id`` — the note whose read-only peek is showing, if any;
* ``panel_visible`` — whether the fan/panel window should be mapped.

The app maps those facts onto widgets; clicks still go through the app, which
tells the machine when a note opened or closed. This is the seam future
tickets (drag reorder, All Notes) build on.
"""

from __future__ import annotations

from typing import Callable, Protocol

STATE_STRIP = "strip"
STATE_FAN = "fan"
STATE_OPEN = "open"

# Spec §7.1.
FAN_DELAY_MS = 120
PEEK_DELAY_MS = 150
COLLAPSE_DELAY_MS = 400


class Handle(Protocol):
    """Opaque timer handle returned by ``schedule``."""


Schedule = Callable[[int, Callable[[], None]], Handle]
Cancel = Callable[[Handle], None]


class DeckMachine:
    """Hover, peek and collapse transitions. UI work happens in callbacks.

    Callbacks are optional; tests usually assert on ``state``/``peek_id``.
    ``on_panel_shown``/``on_panel_hidden`` fire on the strip <-> fan mapping
    edge only, so the app re-applies X11 hints exactly when a map happens.
    """

    def __init__(
        self,
        schedule: Schedule,
        cancel: Cancel,
        *,
        fan_delay_ms: int = FAN_DELAY_MS,
        peek_delay_ms: int = PEEK_DELAY_MS,
        collapse_delay_ms: int = COLLAPSE_DELAY_MS,
        on_panel_shown: Callable[[], None] | None = None,
        on_panel_hidden: Callable[[], None] | None = None,
        on_peek: Callable[[str], None] | None = None,
        on_unpeek: Callable[[], None] | None = None,
    ) -> None:
        self._schedule = schedule
        self._cancel = cancel
        self._fan_delay_ms = fan_delay_ms
        self._peek_delay_ms = peek_delay_ms
        self._collapse_delay_ms = collapse_delay_ms

        self._on_panel_shown = on_panel_shown
        self._on_panel_hidden = on_panel_hidden
        self._on_peek = on_peek
        self._on_unpeek = on_unpeek

        self.state = STATE_STRIP
        self.peek_id: str | None = None
        self._hovered_tab: str | None = None
        # A tab drag suppresses the hover-leave collapse for its whole life
        # (ticket 06, spec §7.2): the pointer legitimately leaves the deck
        # while the button is still held.
        self._dragging = False

        self._expand_timer: Handle | None = None
        self._peek_timer: Handle | None = None
        self._collapse_timer: Handle | None = None

    # -- queries -------------------------------------------------------

    @property
    def panel_visible(self) -> bool:
        return self.state != STATE_STRIP

    @property
    def dragging(self) -> bool:
        return self._dragging

    # -- pointer -------------------------------------------------------

    def hover_enter(self) -> None:
        """The pointer entered the deck (strip or panel)."""
        self._cancel_collapse()
        if self.state == STATE_STRIP and self._expand_timer is None:
            self._expand_timer = self._schedule(
                self._fan_delay_ms, self._expand
            )
        # Already ``fan``/``open``: entering only cancels a pending collapse.

    def hover_leave(self, *, allow_collapse: bool = True) -> None:
        """The pointer left the deck entirely.

        ``allow_collapse=False`` still hides a peek and cancels a pending
        expansion, but keeps the fan mapped. Ticket 05 uses it while the undo
        toast is live: unmapping the panel would hide the Undo button.
        """
        if self.state == STATE_STRIP:
            self._cancel_expand()
            return
        if self._dragging:
            # Releasing will decide where the tab lands; a pointer that
            # strays off the deck mid-drag must not take the fan with it.
            self._clear_peek()
            return
        if self.state != STATE_FAN:
            # Spec §3: an open note never collapses by itself.
            return
        self._clear_peek()
        if not allow_collapse:
            return
        if self._collapse_timer is None:
            self._collapse_timer = self._schedule(
                self._collapse_delay_ms, self._collapse_timer_fired
            )

    def hover_tab(self, note_id: str) -> None:
        """The pointer entered a tab in the fan."""
        if self.state != STATE_FAN or self._dragging:
            return
        self._cancel_collapse()
        if self._hovered_tab == note_id and (
            self.peek_id == note_id or self._peek_timer is not None
        ):
            return

        self._cancel_peek_timer()
        if self.peek_id is not None and self.peek_id != note_id:
            # Crossing tabs: drop the old peek at once, then wait 150 ms for
            # the new one. Showing both would look like a stale peek.
            self._clear_peek()
        self._hovered_tab = note_id
        if self.peek_id == note_id:
            return
        self._peek_timer = self._schedule(
            self._peek_delay_ms, lambda: self._show_peek(note_id)
        )

    def hover_tab_leave(self, note_id: str) -> None:
        """The pointer left a tab.

        A leave from the tab we just crossed away from must not cancel the
        pending peek of the tab we entered (GTK can order the events either
        way), hence the ``_hovered_tab`` check.
        """
        if self._hovered_tab != note_id:
            return
        self._hovered_tab = None
        self._cancel_peek_timer()
        self._clear_peek()

    # -- drag ----------------------------------------------------------

    def drag_begin(self) -> None:
        """A tab press crossed the 5 px threshold (spec §7.2).

        The in-fan peek is cleared at once (its hover is over), any pending
        collapse is cancelled and further collapses are suppressed until
        :meth:`drag_end`. The fan itself stays mapped for the whole gesture.
        """
        self._dragging = True
        self._cancel_collapse()
        self._hovered_tab = None
        self._clear_peek()

    def drag_end(self) -> None:
        """The drag ended or was cancelled; hover rules apply again."""
        self._dragging = False

    # -- deck transitions ---------------------------------------------

    def expand_now(self) -> bool:
        """strip -> fan immediately, without the hover delay (spec §9.3).

        ``lurknotes`` with no arguments expands the fan at once; waiting 120 ms
        for a pointer that is not there would make the cold start look dead.
        Never collapses: an open note stays open.
        """
        if self.state != STATE_STRIP:
            return False
        self._cancel_all()
        self.state = STATE_FAN
        if self._on_panel_shown is not None:
            self._on_panel_shown()
        return True

    def open(self, note_id: str) -> None:
        """A note was opened in the editor (spec §3)."""
        self._cancel_all()
        self._clear_peek()
        self._hovered_tab = None
        self.state = STATE_OPEN

    def close(self) -> bool:
        """The editor closed; the panel stays mapped as the fan."""
        if self.state != STATE_OPEN:
            return False
        self._cancel_all()
        self._clear_peek()
        self.state = STATE_FAN
        return True

    def collapse(self) -> bool:
        """Fan -> strip. ``×`` in the header, or Esc on a focused fan.

        Never touches an open note: there is no header ``×`` in ``open`` and
        the caller must not discard text that is still on screen.
        """
        if self.state != STATE_FAN:
            return False
        self._cancel_all()
        self._clear_peek()
        self._hovered_tab = None
        self.state = STATE_STRIP
        if self._on_panel_hidden is not None:
            self._on_panel_hidden()
        return True

    def escape(self, *, panel_focused: bool) -> bool:
        """Spec §7.3: Esc closes the note, then collapses a focused fan."""
        if self.state == STATE_OPEN:
            self.close()
            return True
        if self.state == STATE_FAN and panel_focused:
            self.collapse()
            return True
        return False

    def stop(self) -> None:
        """Drop every pending timer (app shutdown)."""
        self._cancel_all()

    # -- timer bodies --------------------------------------------------

    def _expand(self) -> None:
        self._expand_timer = None
        if self.state != STATE_STRIP:
            return
        self.state = STATE_FAN
        if self._on_panel_shown is not None:
            self._on_panel_shown()

    def _collapse_timer_fired(self) -> None:
        self._collapse_timer = None
        if self.state != STATE_FAN:
            return
        self.collapse()

    def _show_peek(self, note_id: str) -> None:
        self._peek_timer = None
        if self.state != STATE_FAN or self._hovered_tab != note_id:
            return
        self.peek_id = note_id
        if self._on_peek is not None:
            self._on_peek(note_id)

    # -- helpers -------------------------------------------------------

    def _clear_peek(self) -> None:
        self._cancel_peek_timer()
        if self.peek_id is None:
            return
        self.peek_id = None
        if self._on_unpeek is not None:
            self._on_unpeek()

    def _cancel_expand(self) -> None:
        if self._expand_timer is not None:
            self._cancel(self._expand_timer)
            self._expand_timer = None

    def _cancel_peek_timer(self) -> None:
        if self._peek_timer is not None:
            self._cancel(self._peek_timer)
            self._peek_timer = None

    def _cancel_collapse(self) -> None:
        if self._collapse_timer is not None:
            self._cancel(self._collapse_timer)
            self._collapse_timer = None

    def _cancel_all(self) -> None:
        self._cancel_expand()
        self._cancel_peek_timer()
        self._cancel_collapse()
