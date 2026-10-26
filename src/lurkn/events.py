"""A tiny fan-out for "the deck changed" (ticket 07).

The panel mutates notes in several places: typing/autosave, create, switch,
close, delete/undo and reorder. Read-only views such as All Notes must not poll
the deck, so the app owns one :class:`DeckChanged` and notifies it from every
mutation path. Tickets 05 and 06 call the same hook.
"""

from __future__ import annotations

from typing import Callable

DeckListener = Callable[[], None]


class DeckChanged:
    """Subscribe callbacks and call them synchronously when the deck changes."""

    def __init__(self) -> None:
        self._listeners: list[DeckListener] = []

    def subscribe(self, listener: DeckListener) -> DeckListener:
        """Register *listener* once; returns it so call sites can keep a ref."""
        if listener not in self._listeners:
            self._listeners.append(listener)
        return listener

    def unsubscribe(self, listener: DeckListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def notify(self) -> None:
        # Copy: a listener may unsubscribe itself while being called.
        for listener in list(self._listeners):
            listener()

    def clear(self) -> None:
        self._listeners.clear()
