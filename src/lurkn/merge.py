"""Merging a server pull into the local deck (sync spec §5).

The server is the authority for versions, but the local deck owns its own
edits: a note the user changed while offline must not be silently replaced by
the pull. The merge therefore works one note at a time:

* no local note with that id → create it (a note made on another machine);
* note edited locally since its last push (``synced is False``) → keep the
  local copy; the queue already holds the edit and it will win or lose on the
  server, not here;
* otherwise → take the server's text and version.

Tombstones delete the local note when it is not dirty. Deleting a note the user
just typed into would lose text the server has never seen, so a dirty note
survives until its push lands.
"""

from __future__ import annotations

import time

from .notes import Note


def merge_pulled(
    local: list[Note],
    changes: list[dict],
    *,
    now: float | None = None,
) -> tuple[list[Note], bool]:
    """Apply wire changes to ``local``; return the deck and whether it moved.

    Order is preserved: an updated note keeps its array slot, a new note is
    appended, and the caller re-sorts by ``position`` if the deck syncs.
    """
    stamp = time.time() if now is None else now
    by_id = {note.id: note for note in local}
    result = list(local)
    changed = False

    for change in changes:
        note_id = str(change.get("id", ""))
        if not note_id:
            continue
        deleted = bool(change.get("deleted", False))
        existing = by_id.get(note_id)
        version = change.get("server_updated_at") or None

        if deleted:
            if existing is None:
                continue
            if not existing.synced:
                # The user edited it after the server last saw it; the queue
                # owns that edit and a push will decide.
                continue
            result = [note for note in result if note.id != note_id]
            del by_id[note_id]
            changed = True
            continue

        text = str(change.get("text") or "")
        position = change.get("position")
        created = change.get("created")

        if existing is None:
            note = Note(
                id=note_id,
                text=text,
                created=float(created) if created else stamp,
                updated=stamp,
                position=int(position) if isinstance(position, int) else None,
                server_updated_at=version,
                synced=True,
            )
            result.append(note)
            by_id[note_id] = note
            changed = True
            continue

        if not existing.synced:
            # Local edits are not overridden by a pull; the push settles it.
            continue

        if (existing.text, existing.server_updated_at) == (text, version):
            continue

        existing.text = text
        if isinstance(position, int):
            existing.position = position
        existing.server_updated_at = version
        existing.updated = stamp
        changed = True

    return result, changed


def sort_by_position(notes: list[Note]) -> list[Note]:
    """Deck order once sync is on: explicit ``position``, then array order.

    Notes without a position keep their relative place after the ones that
    have one, which is what a freshly migrated v1 file looks like before the
    first push.
    """
    indexed = list(enumerate(notes))
    indexed.sort(
        key=lambda pair: (
            pair[1].position is None,
            pair[1].position if pair[1].position is not None else 0,
            pair[0],
        )
    )
    return [note for _index, note in indexed]


def assign_positions(notes: list[Note]) -> None:
    """Write the array index back into every note after a reorder."""
    for index, note in enumerate(notes):
        note.position = index
