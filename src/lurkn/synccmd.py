"""``lurknotes sync …``: enable sync from the terminal (sync spec §6).

The deck's settings UI is the everyday way in, but sync has to be verifiable
without it: a fresh install, a headless check, or a second "device" on the same
machine. These three subcommands are that path, and the UI will do the same
work through :class:`lurkn.syncer.Syncer`.

The password is read from stdin, never from argv: arguments are visible in
``ps`` and shell history, and the token it buys protects every note the user
has.
"""

from __future__ import annotations

import sys

from . import strings
from .queue import Queue
from .syncclient import AuthError, RequestError, SyncClient, TransportError
from .syncsettings import ON, PAUSED, SyncSettings
from .syncer import Syncer


def run(argv: list[str], *, stdin=None, stdout=None) -> int:
    """Dispatch ``sync <login|logout|status>``; returns a process exit code."""
    out = stdout or sys.stdout
    args = list(argv)

    if not args:
        print(strings.SYNC_USAGE, file=out)
        return 2

    command, rest = args[0], args[1:]

    if command == "login":
        return _login(rest, stdin or sys.stdin, out)
    if command == "logout":
        return _logout(out)
    if command == "status":
        return _status(out)

    print(strings.ERROR.format(message=f"unknown sync command {command!r}"), file=out)
    print(strings.SYNC_USAGE, file=out)
    return 2


def _login(argv: list[str], stdin, out) -> int:
    options = _parse_options(argv, ("--server", "--email"))
    if options is None:
        print(strings.SYNC_USAGE, file=out)
        return 2
    server = options.get("--server")
    email = options.get("--email")
    if not server or not email:
        print(strings.SYNC_USAGE, file=out)
        return 2

    password = stdin.readline().rstrip("\n") if hasattr(stdin, "readline") else ""
    if not password:
        print(strings.ERROR.format(message="no password on stdin"), file=out)
        return 2

    syncer = _syncer()
    try:
        config = syncer.sign_in(server=server, email=email, password=password)
    except AuthError:
        print(strings.ERROR.format(message="the server rejected the password"), file=out)
        return 1
    except (RequestError, TransportError, ValueError) as exc:
        print(strings.ERROR.format(message=f"cannot sign in: {exc}"), file=out)
        return 1

    print(strings.SYNC_SIGNED_IN.format(email=config.email, server=config.server), file=out)
    return 0


def _logout(out) -> int:
    _syncer().sign_out()
    print(strings.SYNC_SIGNED_OUT, file=out)
    return 0


def _status(out) -> int:
    config = SyncSettings().load()
    state = config.state()
    if state == ON:
        print(
            strings.SYNC_STATUS_ON.format(
                email=config.email,
                server=config.server,
                last=config.last_sync or "never",
            ),
            file=out,
        )
    elif state == PAUSED:
        print(strings.SYNC_STATUS_PAUSED.format(email=config.email), file=out)
    else:
        print(strings.SYNC_STATUS_OFF, file=out)
    return 0


def _syncer() -> Syncer:
    """Build the loop with the module's SyncClient.

    The factory is passed explicitly: a default argument is bound when the
    function is defined, so patching ``lurkn.syncer.SyncClient`` in a test
    would otherwise have no effect here.
    """
    return Syncer(SyncSettings(), Queue(), client_factory=SyncClient)


def _parse_options(argv: list[str], known: tuple[str, ...]) -> dict[str, str] | None:
    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        option = argv[index]
        if option == "--password-stdin":
            index += 1
            continue
        if option not in known:
            return None
        if index + 1 >= len(argv):
            return None
        values[option] = argv[index + 1]
        index += 2
    return values


__all__ = ["run"]
