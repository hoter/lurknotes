"""The autostart .desktop file (spec §9.4).

GNOME session reads ``$XDG_CONFIG_HOME/autostart/<application-id>.desktop``.
The Exec line must be absolute (a login session has no source checkout on
``PATH``) and carries ``--autostart`` so the app maps the strip only and never
requests focus.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APPLICATION_ID = "dev.lurknotes.LurkNotes"
NAME = "LurkNotes"
COMMENT = "Notes deck at the edge of the screen"


def config_home(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root)
    configured = os.environ.get("XDG_CONFIG_HOME")
    return Path(configured) if configured else Path.home() / ".config"


def desktop_path(
    root: Path | str | None = None,
    *,
    app_id: str = APPLICATION_ID,
) -> Path:
    return config_home(root) / "autostart" / f"{app_id}.desktop"


def launcher_path(argv0: str | None = None) -> Path:
    """The absolute launcher to put in Exec.

    Prefer the script that invoked us (``.../lurknotes --install-autostart``),
    then ``lurknotes`` on PATH, then the checkout next to this package.
    """
    candidate = Path(argv0 if argv0 is not None else sys.argv[0])
    if candidate.name == "lurknotes" and candidate.is_file():
        return candidate.resolve()
    found = shutil.which("lurknotes")
    if found:
        return Path(found).resolve()
    return Path(__file__).resolve().parents[2] / "lurknotes"


def _exec_operand(path: str) -> str:
    return f'"{path}"' if any(character.isspace() for character in path) else path


def desktop_contents(
    launcher: str | Path,
    *,
    app_id: str = APPLICATION_ID,
) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={NAME}",
        f"Comment={COMMENT}",
        f"Exec={_exec_operand(str(launcher))} --autostart",
        "Terminal=false",
        "NoDisplay=true",
        "StartupNotify=false",
        "X-GNOME-Autostart-enabled=true",
        "OnlyShowIn=GNOME;",
        "",
    ]
    return "\n".join(lines)


def install(
    *,
    config_home: Path | str | None = None,
    launcher: str | Path | None = None,
    app_id: str = APPLICATION_ID,
) -> Path:
    """Write the .desktop atomically and return its path.

    The file is written to a sibling temp name, fsynced, chmodded 0644 and
    renamed over the target, so a crash never leaves a half desktop entry.
    """
    target = desktop_path(config_home, app_id=app_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    contents = desktop_contents(
        Path(launcher) if launcher is not None else launcher_path(),
        app_id=app_id,
    )
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    _fsync_directory(target.parent)
    return target


def _fsync_directory(directory: Path) -> None:
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
