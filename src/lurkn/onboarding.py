"""First-launch onboarding marker (spec §4.6).

The hint about binding ``Ctrl+Alt+N`` / ``Ctrl+Alt+A`` is shown once. The fact
that it was shown lives in ``$XDG_DATA_HOME/lurknotes/onboarded``. Writing the
marker is best effort: a read-only data directory must not stop the app.
"""

from __future__ import annotations

import os
from pathlib import Path

MARKER_NAME = "onboarded"


def data_home(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root)
    configured = os.environ.get("XDG_DATA_HOME")
    base = Path(configured) if configured else Path.home() / ".local" / "share"
    return base


def marker_path(root: Path | str | None = None) -> Path:
    return data_home(root) / "lurknotes" / MARKER_NAME


def needs_onboarding(root: Path | str | None = None) -> bool:
    return not marker_path(root).exists()


def mark_onboarded(root: Path | str | None = None) -> bool:
    """Create the marker; return False when the data directory is unwritable."""
    target = marker_path(root)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("onboarded\n", encoding="utf-8")
    except OSError:
        return False
    return True
