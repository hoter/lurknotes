"""Command-line parsing (spec §9.3).

One parser serves both entry points: :mod:`lurkn.__main__` handles ``--help``,
``--install-autostart`` and bad arguments before opening a display, and
``LurkNotesApp.do_command_line`` re-parses every delivery because a remote
process' argv arrives as-is (PLATFORM §5).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import strings

ACTIONS = ("new", "all")


class CliError(ValueError):
    """An argv the CLI cannot honour; the message is user-facing."""


@dataclass(frozen=True)
class Command:
    """What one invocation wants the app to do.

    ``action`` is ``""`` (expand the fan), ``"new"`` or ``"all"``.
    ``autostart`` is the quiet session launch: strip only, no focus.
    ``install_autostart`` writes the .desktop file and exits.
    """

    action: str = ""
    autostart: bool = False
    install_autostart: bool = False
    help: bool = False


def parse(argv: list[str]) -> Command:
    """Parse operands without the program name.

    ``--autostart`` accepts no command on purpose: session startup must not
    create notes. ``--help`` wins over everything so the help text is always
    reachable. Unknown operands are an error, never silently ignored.
    """
    action = ""
    autostart = False
    install = False
    wants_help = False

    for argument in argv:
        if argument in ("--help", "-h"):
            wants_help = True
        elif argument == "--autostart":
            if autostart:
                raise CliError(strings.CLI_DUPLICATE.format(argument=argument))
            autostart = True
        elif argument == "--install-autostart":
            if install:
                raise CliError(strings.CLI_DUPLICATE.format(argument=argument))
            install = True
        elif argument in ACTIONS:
            if action:
                raise CliError(
                    strings.CLI_ONE_COMMAND.format(
                        first=action, second=argument
                    )
                )
            action = argument
        elif argument.startswith("-"):
            raise CliError(
                strings.CLI_UNKNOWN_OPTION.format(argument=argument)
            )
        else:
            raise CliError(
                strings.CLI_UNKNOWN_COMMAND.format(argument=argument)
            )

    if wants_help:
        return Command(help=True)

    if install and (action or autostart):
        raise CliError(strings.CLI_INSTALL_ALONE)
    if install:
        return Command(install_autostart=True)

    if autostart and action:
        raise CliError(strings.CLI_AUTOSTART_ALONE)

    return Command(action=action, autostart=autostart)
