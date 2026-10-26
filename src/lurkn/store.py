"""Reading and atomically writing the notes JSON file (spec §5).

The happy path is complete: missing file -> empty list, version/shape checks,
and the tmp + fsync + backup + replace sequence. Recovery from a corrupt file,
an unknown version, or an unwritable directory is ticket 08; the exceptions
raised here are the seam it will build on.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Sequence

from .notes import Note

VERSION = 1


class StoreError(Exception):
    """Base class for problems reading or writing the notes file."""


class CorruptData(StoreError):
    """The file is not the documented JSON shape."""


class UnsupportedVersion(StoreError):
    """The file was written by a newer LurkNotes; do not overwrite it."""


def default_path() -> Path:
    """`$XDG_DATA_HOME/lurknotes/notes.json` (spec §5.1)."""
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "lurknotes" / "notes.json"


class Store:
    """The notes file at *path*, or the XDG default when omitted."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        self.tmp_path = self.path.with_name(self.path.name + ".tmp")
        self.backup_path = self.path.with_name(self.path.stem + ".bak.json")

    def load(self) -> list[Note]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise StoreError(f"cannot read {self.path}: {exc}") from exc

        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise CorruptData(f"{self.path} is not valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise CorruptData(f"{self.path} must contain a JSON object")
        version = payload.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise CorruptData(f"{self.path} has no integer version")
        if version > VERSION:
            raise UnsupportedVersion(
                f"{self.path} has version {version}; this build supports {VERSION}"
            )
        if version != VERSION:
            raise CorruptData(f"{self.path} has unsupported version {version}")

        raw_notes = payload.get("notes")
        if not isinstance(raw_notes, list):
            raise CorruptData(f"{self.path} has no notes array")
        try:
            return [Note.from_dict(item) for item in raw_notes]
        except (TypeError, ValueError, KeyError) as exc:
            raise CorruptData(f"{self.path} contains an invalid note: {exc}") from exc

    def save(self, notes: Sequence[Note]) -> None:
        """Write notes via the crash-safe sequence in spec §5.2.

        The previous file, if any, is copied to notes.bak.json before the
        replace. A failure leaves the old notes.json in place and raises
        OSError/StoreError for the caller to surface.
        """
        payload = {
            "version": VERSION,
            "notes": [note.to_dict() for note in notes],
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())

            if self.path.exists():
                try:
                    shutil.copyfile(self.path, self.backup_path)
                except OSError:
                    # Best effort per spec: the new data is more important than
                    # last save's backup.
                    pass

            os.replace(self.tmp_path, self.path)
            self._fsync_directory()
        except BaseException:
            # A signal may not reach this, but ordinary failures should not
            # leave a half-written tmp file to confuse the next save.
            try:
                self.tmp_path.unlink()
            except OSError:
                pass
            raise

    def _fsync_directory(self) -> None:
        """Make the rename durable; fsync on a directory is not portable."""
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
