"""Storage status banner wiring for the panel (spec §5.3, §10).

The store reports *what* happened; this module decides which banner (and which
action) the panel shows. It reads the app's current ``LoadResult`` and save
retry state at call time, so no copy of that state can go stale.
"""

from __future__ import annotations

import sys

from . import strings
from .store import LOAD_CORRUPT, LOAD_RECOVERED, LOAD_UNSUPPORTED


def show_storage_status(app) -> None:
    if app.panel is None:
        return
    result = app._load_result
    if result is None:
        if app._load_error is not None:
            app.panel.show_status(
                strings.STORAGE_READ_FAILED.format(detail=app._load_error)
            )
        return

    if result.status == LOAD_RECOVERED:
        if result.save_error is not None:
            app.panel.show_status(strings.STORAGE_RECOVERY_NOT_SAVED)
            app._retrier.failed()
            return
        corrupt = (
            result.corrupt_path.name
            if result.corrupt_path is not None
            else "notes.corrupt-<timestamp>.json"
        )
        app.panel.show_status(
            strings.STORAGE_RECOVERED.format(
                count=len(result.notes), corrupt=corrupt
            ),
            kind="warning",
            dismissible=True,
        )
    elif result.status == LOAD_CORRUPT:
        app.panel.show_status(
            strings.STORAGE_CORRUPT,
            action_label=strings.STATUS_CONTINUE,
            on_action=lambda: confirm_overwrite(app),
        )
    elif result.status == LOAD_UNSUPPORTED:
        app.panel.show_status(
            strings.STORAGE_UNSUPPORTED,
            kind="warning",
            dismissible=True,
        )


def confirm_overwrite(app) -> None:
    """User pressed Continue on the corrupt-file banner."""
    if not app.store.confirm_overwrite():
        return
    app.overwrite_blocked = False
    print(
        strings.ERROR.format(
            message="user confirmed replacing the corrupt notes file"
        ),
        file=sys.stderr,
    )
    app._hooks.schedule_dump()
