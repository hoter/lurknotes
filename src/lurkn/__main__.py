"""Entry point: force the X11 backend before GTK is imported.

``--help``, ``--install-autostart`` and invalid argv are handled here, before
a display is opened. Everything else is passed to ``Gtk.Application`` so a
second process hands its argv to the running primary (spec §9.3).
"""

from __future__ import annotations

import os
import sys

from . import autostart as autostart_file
from . import strings
from .cli import CliError, parse


def main(argv: list[str] | None = None) -> int:
    # Spec §9.1: must happen before GTK/GDK is imported anywhere.
    os.environ["GDK_BACKEND"] = "x11"

    args = list(sys.argv[1:] if argv is None else argv)
    try:
        command = parse(args)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if command.help:
        print(strings.USAGE)
        return 0

    if command.install_autostart:
        try:
            written = autostart_file.install(
                launcher=autostart_file.launcher_path(sys.argv[0])
            )
        except OSError as exc:
            print(
                strings.AUTOSTART_INSTALL_FAILED.format(message=str(exc)),
                file=sys.stderr,
            )
            return 1
        print(strings.AUTOSTART_INSTALLED.format(path=written))
        return 0

    from .x11 import X11

    try:
        x11 = X11()
    except RuntimeError as exc:
        print(strings.ERROR.format(message=str(exc)), file=sys.stderr)
        return 1

    from .app import LurkNotesApp

    app = LurkNotesApp(x11=x11)
    return app.run([sys.argv[0], *args])


if __name__ == "__main__":
    raise SystemExit(main())
