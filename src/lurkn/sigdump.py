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
        # The handler runs on the main loop's thread here (GLib installs its
        # own signal source), but a dump is filesystem work: schedule it on
        # the loop rather than doing it inside the handler.
        _schedule_write(app, destination)

    try:
        signal.signal(signal.SIGUSR1, on_signal)
    except (ValueError, OSError):
        # Not the main thread or the platform refuses: degrade to no dump.
        return None
    return destination


def _resolve(path: Path) -> Path:
    """Put a relative name under the snap data dir; keep absolute paths."""
    if path.is_absolute():
        return path
    data = Path(os.environ.get("SNAP_USER_DATA") or Path.home())
    return data / path


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
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
