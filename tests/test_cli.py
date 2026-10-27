"""CLI parsing and command dispatch (spec §9.3).

The parser is the single source of truth for argv, shared by ``__main__``
(help/unknown/install handled without a display) and ``do_command_line``
(commands delivered to the running primary). Tests are pure: no GTK.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lurkn import __version__
from lurkn.__main__ import main
from lurkn.cli import CliError, Command, parse


def test_no_arguments_means_expand_the_fan() -> None:
    assert parse([]) == Command()


def test_new_is_the_only_action() -> None:
    assert parse(["new"]).action == "new"
    with pytest.raises(CliError, match="unknown"):
        parse(["all"])


def test_autostart_is_accepted_without_a_command() -> None:
    assert parse(["--autostart"]) == Command(autostart=True)


def test_install_autostart_is_a_standalone_command() -> None:
    assert parse(["--install-autostart"]) == Command(install_autostart=True)


def test_help_wins_over_other_valid_arguments() -> None:
    assert parse(["--help"]).help is True
    assert parse(["-h"]).help is True
    assert parse(["new", "--help"]).help is True


def test_unknown_arguments_are_rejected() -> None:
    with pytest.raises(CliError, match="unknown"):
        parse(["open"])


def test_duplicate_actions_are_rejected() -> None:
    with pytest.raises(CliError):
        parse(["new", "new"])


def test_autostart_may_not_carry_a_command() -> None:
    # Autostart must never create a note: argv from the session must be quiet.
    with pytest.raises(CliError, match="--autostart"):
        parse(["--autostart", "new"])


def test_install_autostart_may_not_carry_other_operands() -> None:
    with pytest.raises(CliError):
        parse(["--install-autostart", "new"])
    with pytest.raises(CliError):
        parse(["--install-autostart", "--autostart"])


# -- entry point: no display needed for local commands ------------------


def test_help_prints_usage_and_exits_zero(capsys) -> None:
    assert main(["--help"]) == 0
    assert "usage: lurknotes" in capsys.readouterr().out


def test_version_is_a_standalone_flag() -> None:
    assert parse(["--version"]) == Command(version=True)
    assert parse(["-V"]) == Command(version=True)
    assert parse(["new", "--version"]).version is True


def test_help_wins_over_version() -> None:
    assert parse(["--version", "--help"]).help is True


def test_version_prints_without_a_display(capsys) -> None:
    assert main(["--version"]) == 0
    output = capsys.readouterr().out
    assert output == f"lurknotes {__version__}\n"


def test_unknown_and_autostart_with_command_exit_nonzero(capsys) -> None:
    assert main(["whatever"]) == 2
    assert "unknown" in capsys.readouterr().err
    assert main(["--autostart", "new"]) == 2
    assert "--autostart" in capsys.readouterr().err


def test_install_autostart_uses_the_xdg_config_home(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert main(["--install-autostart"]) == 0

    target = tmp_path / "config" / "autostart" / "dev.lurknotes.LurkNotes.desktop"
    assert target.is_file()
    assert "--autostart" in target.read_text(encoding="utf-8")
    assert str(target) in capsys.readouterr().out
