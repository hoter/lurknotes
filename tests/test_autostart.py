"""The autostart .desktop file (spec §9.4).

Written atomically into ``$XDG_CONFIG_HOME/autostart`` with the exact keys the
spec and GNOME session need. Tests always pass a temporary config root.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from lurkn.autostart import (
    APPLICATION_ID,
    desktop_contents,
    desktop_path,
    install,
    launcher_path,
)


def test_the_path_is_the_application_id_under_xdg_config_autostart(
    tmp_path: Path,
) -> None:
    assert desktop_path(tmp_path) == (
        tmp_path / "autostart" / "dev.lurknotes.LurkNotes.desktop"
    )
    assert APPLICATION_ID == "dev.lurknotes.LurkNotes"


def test_install_creates_the_directory_and_file(tmp_path: Path) -> None:
    launcher = tmp_path / "bin" / "lurknotes"

    written = install(
        config_home=tmp_path / "config", launcher=launcher
    )

    assert written == desktop_path(tmp_path / "config")
    assert written.is_file()
    assert (tmp_path / "config" / "autostart").is_dir()


def test_the_file_has_the_required_keys_and_exec_line(tmp_path: Path) -> None:
    launcher = (tmp_path / "lurknotes").resolve()

    written = install(config_home=tmp_path / "config", launcher=launcher)
    lines = written.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "[Desktop Entry]"
    assert "Type=Application" in lines
    assert "Name=LurkNotes" in lines
    assert f"Exec={launcher} --autostart" in lines
    assert "Terminal=false" in lines
    assert "NoDisplay=true" in lines
    assert "X-GNOME-Autostart-enabled=true" in lines
    assert "OnlyShowIn=GNOME;" in lines


def test_install_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    config = tmp_path / "config"
    target = install(config_home=config, launcher="/opt/lurknotes")
    install(config_home=config, launcher="/opt/lurknotes")

    leftovers = sorted(
        path.name for path in target.parent.iterdir() if path.name != target.name
    )
    assert leftovers == []


def test_the_file_is_world_readable_and_not_executable(tmp_path: Path) -> None:
    written = install(
        config_home=tmp_path / "config", launcher="/opt/lurknotes"
    )

    mode = stat.S_IMODE(written.stat().st_mode)
    assert mode == 0o644


def test_the_placeholder_app_id_can_be_overridden_for_tests(tmp_path: Path) -> None:
    written = install(
        config_home=tmp_path / "config",
        launcher="/opt/lurknotes",
        app_id="dev.lurknotes.LurkNotes.test",
    )

    assert written.name == "dev.lurknotes.LurkNotes.test.desktop"


def test_the_snap_override_comes_from_the_environment(tmp_path: Path) -> None:
    # The snap sets LURKNOTES_APP_ID so its D-Bus name, desktop id and
    # autostart entry cannot collide with the deb/pipx build (research 03).
    script = (
        "from pathlib import Path\n"
        "from lurkn import autostart\n"
        "print(autostart.APPLICATION_ID)\n"
        "print(autostart.desktop_path(Path('cfg')).name)\n"
    )
    environment = {
        "LURKNOTES_APP_ID": "io.github.hoter.LurkNotes",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.splitlines() == [
        "io.github.hoter.LurkNotes",
        "io.github.hoter.LurkNotes.desktop",
    ]


def test_the_default_app_id_is_used_without_the_override(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path\n"
        "from lurkn import autostart\n"
        "print(autostart.APPLICATION_ID)\n"
        "print(autostart.desktop_path(Path('cfg')).name)\n"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "LURKNOTES_APP_ID"
    }
    environment["PYTHONPATH"] = str(
        Path(__file__).resolve().parents[1] / "src"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.splitlines() == [
        "dev.lurknotes.LurkNotes",
        "dev.lurknotes.LurkNotes.desktop",
    ]


def test_launcher_path_prefers_an_existing_argv0_script(tmp_path: Path) -> None:
    script = tmp_path / "lurknotes"
    script.write_text("#!/bin/sh\n", encoding="utf-8")

    assert launcher_path(str(script)) == script.resolve()


def test_desktop_contents_quotes_a_launcher_path_with_spaces() -> None:
    contents = desktop_contents("/home/dev/My Apps/lurknotes")

    assert 'Exec="/home/dev/My Apps/lurknotes" --autostart' in contents.splitlines()
