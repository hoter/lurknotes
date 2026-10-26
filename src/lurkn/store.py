"""Reading and atomically writing the notes JSON file (spec §5).

The write sequence is the crash-safe one from spec §5.2: tmp + fsync, copy the
current file to ``notes.bak.json`` (best effort), then ``os.replace``. Recovery
follows spec §5.3:

* corrupt main + valid backup -> quarantine the corrupt file as
  ``notes.corrupt-<ts>.json``, use the backup, and persist it immediately so a
  restart keeps the recovered deck;
* corrupt main + unusable backup -> empty deck and an overwrite gate: nothing
  touches the original file until the user explicitly confirms;
* a future ``version`` -> read-only mode; ``save`` refuses to write at all.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .notes import Note

VERSION = 1

LOAD_OK = "ok"
LOAD_RECOVERED = "recovered"
LOAD_CORRUPT = "corrupt"
LOAD_UNSUPPORTED = "unsupported"


class StoreError(Exception):
    """Base class for problems reading or writing the notes file."""


class CorruptData(StoreError):
    """The file is not the documented JSON shape."""


class UnsupportedVersion(StoreError):
    """The file was written by a newer LurkNotes; do not overwrite it."""


class OverwriteBlocked(StoreError):
    """A corrupt file is preserved until the user explicitly confirms."""


class ReadOnlyError(StoreError):
    """The store loaded a file it must never overwrite."""


@dataclass(frozen=True)
class LoadResult:
    """What ``load`` found and what the caller must tell the user.

    ``status`` is one of the module-level ``LOAD_*`` constants. ``save_error``
    is set when recovered notes could not be persisted (the deck is still in
    memory and a later ``save`` can retry).
    """

    notes: list[Note]
    status: str = LOAD_OK
    detail: str = ""
    corrupt_path: Path | None = None
    read_only: bool = False
    overwrite_blocked: bool = False
    save_error: Exception | None = None


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
        self.last_save_error: Exception | None = None
        self.last_quarantine_path: Path | None = None
        self._read_only = False
        self._overwrite_blocked = False
        self._preserve_before_save = False

    # -- reading -------------------------------------------------------

    def load(self) -> LoadResult:
        """Read the deck, recovering from corruption as spec §5.3 requires.

        A corrupt main file is never modified in place. With a valid backup it
        is moved aside and the backup deck is written back. Without a usable
        backup the file is left exactly as found and ``save`` is gated until
        :meth:`confirm_overwrite` is called.
        """
        self._read_only = False
        self._overwrite_blocked = False
        self._preserve_before_save = False
        self.last_save_error = None
        self.last_quarantine_path = None

        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._load_when_main_is_missing()
        except OSError as exc:
            raise StoreError(f"cannot read {self.path}: {exc}") from exc

        try:
            document = self._parse_document(raw, self.path)
            version = self._document_version(document, self.path)
        except CorruptData as exc:
            return self._recover_from_corruption(exc)

        if version > VERSION:
            self._read_only = True
            try:
                notes = self._document_notes(document, self.path)
            except CorruptData:
                # A future format may not even contain our notes array; the
                # file is still read-only, the deck is just empty.
                notes = []
            return LoadResult(
                notes,
                LOAD_UNSUPPORTED,
                detail=(
                    f"{self.path} has version {version}; this build supports "
                    f"{VERSION} and will not write it"
                ),
                read_only=True,
            )

        if version != VERSION:
            return self._recover_from_corruption(
                CorruptData(f"{self.path} has unsupported version {version}")
            )

        try:
            notes = self._document_notes(document, self.path)
        except CorruptData as exc:
            return self._recover_from_corruption(exc)
        return LoadResult(notes)

    def _load_when_main_is_missing(self) -> LoadResult:
        # First run, or a crash between quarantining a corrupt file and
        # writing the recovered deck. A valid backup is always worth keeping.
        backup = self._load_backup()
        if backup is None:
            return LoadResult([])
        try:
            self.save(backup)
        except (OSError, StoreError) as exc:
            self.last_save_error = exc
            return LoadResult(
                backup,
                LOAD_RECOVERED,
                detail=f"{self.path} was missing; restored from {self.backup_path}",
                save_error=exc,
            )
        return LoadResult(
            backup,
            LOAD_RECOVERED,
            detail=f"{self.path} was missing; restored from {self.backup_path}",
        )

    def _recover_from_corruption(self, corruption: CorruptData) -> LoadResult:
        backup = self._load_backup()
        if backup is None:
            # Spec §5.3: no overwrite until an explicit user action. Keep the
            # original file byte-for-byte and gate every save.
            self._overwrite_blocked = True
            self._preserve_before_save = True
            return LoadResult(
                [],
                LOAD_CORRUPT,
                detail=str(corruption),
                overwrite_blocked=True,
            )

        self._preserve_before_save = True
        try:
            self.save(backup)
        except (OSError, StoreError) as exc:
            self.last_save_error = exc
            return LoadResult(
                backup,
                LOAD_RECOVERED,
                detail=str(corruption),
                save_error=exc,
            )
        return LoadResult(
            backup,
            LOAD_RECOVERED,
            detail=str(corruption),
            corrupt_path=self.last_quarantine_path,
        )

    def _load_backup(self) -> list[Note] | None:
        """The backup deck, or None when it is absent or unusable."""
        try:
            raw = self.backup_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        try:
            document = self._parse_document(raw, self.backup_path)
            version = self._document_version(document, self.backup_path)
            if version != VERSION:
                return None
            return self._document_notes(document, self.backup_path)
        except CorruptData:
            return None

    @staticmethod
    def _parse_document(raw: str, path: Path) -> dict:
        try:
            document = json.loads(raw)
        except ValueError as exc:
            raise CorruptData(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise CorruptData(f"{path} must contain a JSON object")
        return document

    @staticmethod
    def _document_version(document: dict, path: Path) -> int:
        version = document.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise CorruptData(f"{path} has no integer version")
        return version

    @staticmethod
    def _document_notes(document: dict, path: Path) -> list[Note]:
        raw_notes = document.get("notes")
        if not isinstance(raw_notes, list):
            raise CorruptData(f"{path} has no notes array")
        try:
            return [Note.from_dict(item) for item in raw_notes]
        except (TypeError, ValueError, KeyError) as exc:
            raise CorruptData(f"{path} contains an invalid note: {exc}") from exc

    # -- writing -------------------------------------------------------

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def overwrite_blocked(self) -> bool:
        return self._overwrite_blocked

    def confirm_overwrite(self) -> bool:
        """Explicit user action: allow a later save to replace a corrupt file.

        The corrupt file is still not touched here. The next save first moves
        it to ``notes.corrupt-<ts>.json`` and only then writes the new deck, so
        a crash in between still preserves the unreadable original.
        """
        if self._read_only or not self._overwrite_blocked:
            return False
        self._overwrite_blocked = False
        return True

    def save(self, notes: Sequence[Note]) -> None:
        """Write notes via the crash-safe sequence in spec §5.2.

        A failure leaves the old ``notes.json`` and ``notes.bak.json`` intact
        and raises OSError/StoreError for the caller to surface.
        """
        if self._read_only:
            raise ReadOnlyError(
                f"{self.path} was written by a newer LurkNotes; refusing to save"
            )
        if self._overwrite_blocked:
            raise OverwriteBlocked(
                f"{self.path} is corrupt; confirm before overwriting it"
            )

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

            if self._preserve_before_save:
                self._quarantine_main()

            if self.path.exists():
                try:
                    shutil.copyfile(self.path, self.backup_path)
                except OSError:
                    # Best effort per spec: the new data is more important than
                    # last save's backup.
                    pass

            os.replace(self.tmp_path, self.path)
            self._fsync_directory()
            self.last_save_error = None
        except BaseException:
            # Ordinary failures must not leave a half-written tmp file to
            # confuse the next save. The old main and backup stay untouched.
            try:
                self.tmp_path.unlink()
            except OSError:
                pass
            raise

    def _quarantine_main(self) -> None:
        """Move the corrupt main aside, preserving its exact bytes."""
        if not self.path.exists():
            self._preserve_before_save = False
            return
        destination = self._corrupt_path()
        os.replace(self.path, destination)
        self.last_quarantine_path = destination
        self._preserve_before_save = False

    def _corrupt_path(self) -> Path:
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        candidate = self.path.with_name(
            f"{self.path.stem}.corrupt-{stamp}.json"
        )
        counter = 1
        while candidate.exists():
            candidate = self.path.with_name(
                f"{self.path.stem}.corrupt-{stamp}-{counter}.json"
            )
            counter += 1
        return candidate

    def _fsync_directory(self) -> None:
        """Make the rename durable; fsync on a directory is not portable."""
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
