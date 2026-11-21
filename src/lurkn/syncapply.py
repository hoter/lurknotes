"""What a successful push changes locally (sync spec §6.2).

The push response is the only place the server hands back versions, and the
version is what the *next* push uses as its ``base``. Dropping it is silent and
expensive: the note keeps ``base = None``, the server answers ``stale`` on the
next edit, and the edit is lost. So applying the response is a rule, not a
detail, and it lives here where it can be tested without GTK.

Deletion is the mirror case: a tombstone the server accepted means the note
should not come back from the local deck either.
"""

from __future__ import annotations

from .notes import Note


def apply_applied(notes: list[Note], applied: list[dict]) -> bool:
    """Store the versions the server accepted; return whether anything moved."""
    by_id = {note.id: note for note in notes}
    changed = False

    for entry in applied:
        note_id = str(entry.get("id", ""))
        note = by_id.get(note_id)
        if note is None:
            # The deck moved on (deleted locally) between push and reply.
            continue
        version = entry.get("server_updated_at")
        if version and note.server_updated_at != version:
            note.server_updated_at = version
            changed = True
        if note.synced is False:
            note.synced = True
            changed = True

    return changed


def apply_rejected(notes: list[Note], rejected: list[dict]) -> list[str]:
    """Notes the server refused as stale; the pull that follows overwrites them.

    Returns their ids so the caller can decide whether to keep waiting for the
    pull. The notes stay ``synced`` True: the local edit lost, and pretending
    otherwise would keep re-sending it forever.
    """
    ids = [str(entry.get("id", "")) for entry in rejected if entry.get("id")]
    by_id = {note.id: note for note in notes}
    for note_id in ids:
        note = by_id.get(note_id)
        if note is not None:
            note.synced = True
    return ids
