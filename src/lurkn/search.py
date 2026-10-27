"""Filtering the deck by text (the fan search box).

Pure Python so the rule is testable without GTK: the query is a
case-insensitive literal substring of the whole note text, so a match on any
line counts and the deck's manual order is preserved.
"""

from __future__ import annotations

import re
from typing import Sequence

from .notes import Note


def search_notes(notes: Sequence[Note], query: str) -> list[Note]:
    """Notes matching *query*, in deck order.

    An empty (or whitespace-only) query returns every note. The query is a
    case-insensitive substring of the whole text; ``re.escape`` keeps regular
    expression metacharacters literal.
    """
    needle = query.strip()
    if not needle:
        return list(notes)
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    return [note for note in notes if pattern.search(note.text)]
