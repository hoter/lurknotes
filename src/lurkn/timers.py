"""Shared timer injection types.

The pure state machines (:mod:`lurkn.deck`, :mod:`lurkn.focus`,
:mod:`lurkn.undo`) never import GLib. They receive a ``schedule``/``cancel``
pair, so tests can run them on a fake clock while the app injects
``GLib.timeout_add``/``GLib.source_remove``.
"""

from __future__ import annotations

from typing import Callable, Protocol


class Handle(Protocol):
    """Opaque timer handle returned by ``schedule``."""


Schedule = Callable[[int, Callable[[], None]], Handle]
Cancel = Callable[[Handle], None]
