"""The offline queue: changes that have not reached the server yet (spec §6.3).

One rule keeps this honest: **enqueue before sending, dequeue only after a
``2xx``**. A crash between the two therefore repeats a send, which the server
handles through the ``base`` version check, instead of losing the change.

The queue is a small JSON file beside ``notes.json``. It is written through
the same atomic replacement the notes store uses, and mutated under a lock:
atomic replace makes a single write safe, it does not stop two threads from
reading the same list and writing back two different versions.

A queued change carries the note's text and its ``base`` version. Sending the
last state of the note per id is enough: an earlier queued edit of the same
note is superseded by the later one.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic import atomic_write
from .syncsettings import default_path

VERSION = 1


class QueueError(Exception):
    """The queue file cannot be read or trusted."""


@dataclass(frozen=True)
class PendingChange:
    """One note's pending state, exactly as ``POST /api/sync/changes`` wants it."""

    id: str
    text: str
    position: int
    created: float
    base: str | None = None
    deleted: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "position": self.position,
            "created": self.created,
            "base": self.base,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PendingChange":
        if not isinstance(data, dict):
            raise QueueError("each pending change must be an object")
        try:
            return cls(
                id=str(data["id"]),
                text=str(data.get("text", "")),
                position=int(data.get("position", 0)),
                created=float(data.get("created", 0.0)),
                base=data.get("base") or None,
                deleted=bool(data.get("deleted", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise QueueError(f"invalid pending change: {exc}") from exc


def default_queue_path(data_dir: Path | str | None = None) -> Path:
    notes = default_path(data_dir)
    return notes.with_name("queue.json")


class Queue:
    """A durable, thread-safe list of pending changes keyed by note id."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_queue_path()
        self._lock = threading.Lock()
        self.last_error: QueueError | None = None

    # -- reading -------------------------------------------------------

    def load(self) -> list[PendingChange]:
        with self._lock:
            return self._read()

    def __len__(self) -> int:
        return len(self.load())

    def __bool__(self) -> bool:
        return bool(self.load())

    def _read(self) -> list[PendingChange]:
        self.last_error = None
        if not self.path.exists():
            return []
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise QueueError(f"{self.path} must be a JSON object")
            version = document.get("version", VERSION)
            if version != VERSION:
                raise QueueError(f"{self.path} has unsupported version {version!r}")
            raw = document.get("changes", [])
            if not isinstance(raw, list):
                raise QueueError(f"{self.path} has no changes array")
            return [PendingChange.from_dict(item) for item in raw]
        except (OSError, json.JSONDecodeError, QueueError) as exc:
            self.last_error = (
                exc if isinstance(exc, QueueError) else QueueError(str(exc))
            )
            # A broken queue must not stop the deck: the notes file is the
            # source of truth, and the next save re-enqueues whatever differs.
            return []

    def _write(self, changes: list[PendingChange]) -> None:
        if not changes:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return
        document = {"version": VERSION, "changes": [item.to_dict() for item in changes]}
        atomic_write(
            self.path,
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            mode=0o600,
        )

    # -- writing -------------------------------------------------------

    def enqueue(self, change: PendingChange) -> None:
        """Queue a note's latest state, replacing any earlier one for that id."""
        with self._lock:
            previous = {item.id: item for item in self._read()}
            earlier = previous.get(change.id)
            if earlier is not None and earlier.base is not None:
                # The server compares against the last version it sent us, not
                # against a local edit that never left the machine.
                change = replace(change, base=earlier.base)
            changes = [item for item in previous.values() if item.id != change.id]
            changes.append(change)
            self._write(changes)

    def remove(self, note_id: str) -> None:
        """Drop a change once the server confirmed it."""
        with self._lock:
            changes = [item for item in self._read() if item.id != note_id]
            self._write(changes)

    def clear(self) -> None:
        with self._lock:
            self._write([])
