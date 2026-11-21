"""Dump the live deck on demand: ``kill -USR1 <pid>``.

The deck keeps text in three places — the GTK buffer, the note object and the
file — and a bug that loses typing can hide in the gap between them. The
existing ``LURKNOTES_TEST_DUMP`` snapshot is written only on events (mapping,
opening a note), which is useless exactly when the question is "what does the
buffer hold *now*".

So an operator-triggered dump: the process listens for ``SIGUSR1`` and writes a
JSON file with the buffer text, the saved text and where they differ. It is
opt-in through an environment variable, and the handler is installed only when
set, so production behaviour is unchanged.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

# Default file, inside the snap's own data directory so `snap run` can write
# it and the user can still read it from `~/snap/lurknotes/current/...`.
DUMP_ENV = "LURKNOTES_SIGNAL_DUMP"


def install(app, path: Path | str | None = None) -> Path | None:
    """Start writing a dump on SIGUSR1; returns the file, or None when off.

    ``path`` defaults to ``$LURKNOTES_SIGNAL_DUMP``. Both must be writable
    from inside the confinement, which is why the default lives under
    ``$SNAP_USER_DATA`` rather than a host path the snap cannot see.
    """
    target = path or os.environ.get(DUMP_ENV)
    if not target:
        return None

    destination = _resolve(Path(target))

    def on_signal(_signum, _frame) -> None:
        # A Python signal handler runs on the main thread between bytecodes,
        # which for a GLib application is inside the loop — safe to do the
        # filesystem work here. Scheduling it through GLib instead would need
        # the loop to wake, and a process sitting idle in poll() may not.
        try:
            snapshot(app, destination)
        except Exception:  # pragma: no cover - never let diagnostics kill us
            pass

    try:
        signal.signal(signal.SIGUSR1, on_signal)
    except (ValueError, OSError):
        # Not the main thread or the platform refuses: degrade to no dump.
        return None
    return destination


def _resolve(path: Path) -> Path:
    """Put a relative name beside ``notes.json``; keep absolute paths.

    ``XDG_DATA_HOME`` first, then ``SNAP_USER_DATA``: the dump must land where
    the snap is allowed to write *and* where the user can read it, which is
    ``~/snap/lurknotes/current/.local/share/lurknotes``. Resolving to the
    plain home would write outside the confinement and fail silently.
    """
    if path.is_absolute():
        return path
    base = os.environ.get("XDG_DATA_HOME")
    if not base:
        snap_data = os.environ.get("SNAP_USER_DATA")
        base = str(Path(snap_data) / ".local" / "share") if snap_data else str(Path.home())
    return Path(base) / "lurknotes" / path


def _schedule_write(app, destination: Path) -> None:
    from gi.repository import GLib

    def write() -> bool:
        snapshot(app, destination)
        return False

    GLib.idle_add(write)


def snapshot(app, destination: Path) -> None:
    """Write the three copies of every note, plus the buffer for the open one.

    Kept separate from the signal plumbing so a test can call it directly and
    compare against what a user would see.
    """
    editor = None
    buffer_text = None
    current_id = getattr(app, "current_id", None)
    panel = getattr(app, "panel", None)
    if current_id is not None and panel is not None:
        text_method = getattr(getattr(panel, "note", None), "text", None)
        if callable(text_method):
            try:
                editor = text_method()
            except Exception:  # pragma: no cover - a dead widget
                editor = None
    if editor is not None:
        buffer_text = editor

    notes = []
    for note in getattr(app, "notes", []):
        notes.append(
            {
                "id": note.id,
                "length": len(note.text),
                "text": note.text,
                "position": getattr(note, "position", None),
                "server_updated_at": getattr(note, "server_updated_at", None),
                "is_current": note.id == current_id,
                "buffer_differs": (
                    editor is not None and note.id == current_id and editor != note.text
                ),
            }
        )

    document = {
        "state": getattr(app, "state", ""),
        "current_id": current_id,
        "buffer_length": None if buffer_text is None else len(buffer_text),
        "buffer_text": buffer_text,
        "notes": notes,
    }
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, destination)
    except OSError as exc:
        # Never silent: a dump that misses its path is why two rounds of
        # diagnosis showed nothing.
        print(f"lurknotes: cannot write deck dump {destination}: {exc}", file=sys.stderr)
