"""Crash-safe file writes shared by the store, the sync settings and the queue.

Spec §5.2 (store) and spec sync §6.3 (``sync.json``, ``queue.json``) all ask
for the same sequence: write a sibling temp file, ``fsync`` it, then
``os.replace`` over the target and ``fsync`` the directory so the rename
survives a power cut.

The permission argument matters for secrets: ``open`` applies the mode only at
creation, so an existing file keeps whatever permissions it had. ``atomic_write``
therefore opens with ``O_NOFOLLOW`` (a symlink planted in the data directory
must not redirect the write) and calls ``fchmod`` every time.
"""

from __future__ import annotations

import os
from pathlib import Path


def temp_path_for(path: Path) -> Path:
    """The sibling used while writing ``path``."""
    return path.with_name(path.name + ".tmp")


def atomic_write(path: Path, text: str, *, mode: int | None = None) -> None:
    """Replace ``path`` with ``text`` without ever leaving it half-written.

    ``mode`` is applied on every write, not only on creation, so a file that
    was previously world-readable is tightened on the next save. Without
    ``mode`` the file keeps the process umask, as the notes store always did.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temp_path_for(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if mode is not None:
        # Refuse to follow a symlink squatting on the temp name.
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600 if mode else 0o666)
        if mode is not None:
            try:
                os.fchmod(descriptor, mode)
            except BaseException:
                os.close(descriptor)
                raise
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def fsync_directory(directory: Path) -> None:
    """Make a rename durable; fsync on a directory is not portable."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
