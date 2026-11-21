"""A pull must never overwrite what the user is typing.

This is the data-loss bug that shipped: a push was acknowledged and the
immediate pull brought the note back with the text the server had *just*
accepted — which is older than what is in the editor — and `merge_pulled`
wrote it over. Collapsing the note then saved the shorter text.

The fix has two parts, and this module owns the first: the merge takes a set
of ids to leave alone, and the app passes the note it currently has open with
unsaved changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Protection:
    """A note the merge must not touch, and why.

    ``note_id`` is the desktop's UUID. ``reason`` is only for logs and tests.
    """

    note_id: str
    reason: str = "editing"


def protected_ids(protections: list[Protection]) -> set[str]:
    return {item.note_id for item in protections}
