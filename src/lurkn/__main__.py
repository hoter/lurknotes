"""Entry point: force the X11 backend before GTK is imported."""

from __future__ import annotations

import os
import sys

from . import strings


def main(argv: list[str] | None = None) -> int:
    # Spec §9.1: must happen before GTK/GDK is imported anywhere.
    os.environ["GDK_BACKEND"] = "x11"

    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args else ""
    if action not in ("", "new", "all"):
        print(
            strings.UNKNOWN_COMMAND.format(command=action),
            file=sys.stderr,
        )
        return 2

    from .app import LurkNotesApp

    try:
        app = LurkNotesApp(action=action)
        return app.run([sys.argv[0]])
    except RuntimeError as exc:
        print(strings.ERROR.format(message=str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
