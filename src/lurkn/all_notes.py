"""All Notes: search across the whole note text, snippets and dates.

Pure Python so the search rules are testable without GTK. The window in
``windows/all_notes.py`` renders :class:`SearchHit` rows; :class:`AllNotesModel`
is the piece that turns "the deck changed" into fresh rows without polling.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Sequence
from xml.sax.saxutils import escape

from .notes import Note

# A search result must show the line containing the match. Long lines are
# windowed around the match so the highlight cannot be ellipsized away.
SNIPPET_LIMIT = 100
DATE_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class SearchHit:
    """One All Notes row: the note, a one-line snippet, and where it matched."""

    note: Note
    snippet: str = ""
    highlight: tuple[int, int] | None = None


def format_updated(timestamp: float) -> str:
    """The note's updated date in local time, unambiguous and locale-free."""
    return time.strftime(DATE_FORMAT, time.localtime(timestamp))


def search_notes(notes: Sequence[Note], query: str) -> list[SearchHit]:
    """Notes matching *query*, in manual deck order (spec §4.3, §6.4).

    The query is a case-insensitive substring of the whole text, so a match on
    any line counts. An empty (or whitespace-only) query shows every note and
    uses the first body line as the snippet. Duplicate titles stay separate
    rows because the note id, not the title, is the identity.
    """
    needle = query.strip()
    hits: list[SearchHit] = []
    for note in notes:
        if not needle:
            hits.append(SearchHit(note=note, snippet=_body_snippet(note)))
            continue
        match = _find(note.text, needle)
        if match is None:
            continue
        snippet, highlight = _matched_snippet(
            note.text, match.start(), match.end()
        )
        hits.append(SearchHit(note=note, snippet=snippet, highlight=highlight))
    return hits


def highlight_markup(text: str, highlight: tuple[int, int] | None) -> str:
    """Pango markup for a snippet, bolding the match and escaping the rest."""
    if highlight is None:
        return escape(text)
    start, end = highlight
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    return (
        escape(text[:start])
        + "<b>"
        + escape(text[start:end])
        + "</b>"
        + escape(text[end:])
    )


def _find(text: str, query: str) -> re.Match[str] | None:
    # re.escape makes the user's input a literal substring; IGNORECASE keeps
    # the offsets into the original text, unlike lower()/casefold().
    return re.search(re.escape(query), text, re.IGNORECASE)


def _body_snippet(note: Note) -> str:
    preview = note.preview()
    return preview[0].strip() if preview else ""


def _matched_snippet(text: str, start: int, end: int) -> tuple[str, tuple[int, int]]:
    line_start = text.rfind("\n", 0, start) + 1
    newline = text.find("\n", end)
    line_end = len(text) if newline == -1 else newline
    line = text[line_start:line_end]

    leading = len(line) - len(line.lstrip())
    stripped = line.strip()
    match_start = max(0, start - line_start - leading)
    match_end = min(len(stripped), end - line_start - leading)

    if len(stripped) <= SNIPPET_LIMIT:
        return stripped, (match_start, match_end)

    match_length = match_end - match_start
    if match_length >= SNIPPET_LIMIT:
        window_start = match_start
    else:
        window_start = max(0, match_start - (SNIPPET_LIMIT - match_length) // 2)
    window_end = min(len(stripped), window_start + SNIPPET_LIMIT)
    if window_end - window_start < SNIPPET_LIMIT:
        window_start = max(0, window_end - SNIPPET_LIMIT)

    prefix = "…" if window_start > 0 else ""
    suffix = "…" if window_end < len(stripped) else ""
    visible_match_end = min(match_end, window_end)
    snippet = prefix + stripped[window_start:window_end] + suffix
    highlight = (
        len(prefix) + match_start - window_start,
        len(prefix) + visible_match_end - window_start,
    )
    return snippet, highlight


class AllNotesModel:
    """Rows for All Notes, refreshed by re-reading the deck on demand.

    The provider is called on every refresh, so text being typed in the panel
    is visible without reopening the window. The window subscribes ``refresh``
    to the app's :class:`~lurkn.events.DeckChanged` notifier.
    """

    def __init__(self, notes_provider: Callable[[], Sequence[Note]]) -> None:
        self._notes_provider = notes_provider
        self.query = ""
        self.hits: list[SearchHit] = []

    def set_query(self, query: str) -> list[SearchHit]:
        self.query = query
        return self.refresh()

    def refresh(self) -> list[SearchHit]:
        self.hits = search_notes(self._notes_provider(), self.query)
        return self.hits
