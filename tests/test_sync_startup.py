"""Sync must never stop the deck from starting.

This is the bug that shipped in x4: ``LurkNotesApp.__init__`` read the sync
settings and crashed with an AttributeError, so the whole application refused
to launch. The deck's first job is to show notes; sync is an optional layer and
must degrade to "off" for any reason at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lurkn.syncsettings import SyncConfig, SyncSettings


@pytest.fixture()
def data_home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path / "lurknotes"


def startup_state() -> tuple[SyncConfig, bool]:
    """What __init__ computes at startup: the config and row visibility."""
    settings = SyncSettings()
    return settings.load(), settings.exists


def test_no_settings_file_means_off_and_no_row(data_home) -> None:
    config, visible = startup_state()

    assert config.enabled is False
    assert config.token == ""
    assert visible is False


def test_a_corrupt_file_means_off_not_a_crash(data_home) -> None:
    data_home.mkdir(parents=True)
    (data_home / "sync.json").write_text("{broken", encoding="utf-8")

    config, visible = startup_state()

    assert config.enabled is False
    # The row is shown: the user configured sync once, so hiding it would make
    # the broken state invisible and unfixable from the UI.
    assert visible is True


def test_an_unreadable_file_means_off_not_a_crash(data_home, monkeypatch) -> None:
    path = data_home / "sync.json"
    data_home.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "enabled": True, "token": "t"}), encoding="utf-8")
    path.chmod(0o000)

    try:
        config, _visible = startup_state()
    finally:
        path.chmod(0o600)

    assert config.enabled is False


def test_the_row_is_shown_once_configured(data_home) -> None:
    data_home.mkdir(parents=True)
    SyncSettings(data_home / "sync.json").save(
        SyncConfig(enabled=True, token="t", server="http://n", email="u@e.com")
    )

    config, visible = startup_state()

    assert visible is True
    assert config.enabled is True


def test_startup_computes_the_row_visibility_from_the_file_not_the_config(
    data_home,
) -> None:
    """The x4 crash: the row flag read `exists` off SyncConfig.

    A dataclass would raise AttributeError, and because this runs inside
    `__init__` the whole application failed to start — a missing attribute took
    down the deck, not a dial within it.
    """
    data_home.mkdir(parents=True)
    SyncSettings(data_home / "sync.json").save(
        SyncConfig(enabled=True, token="t", server="http://n")
    )

    config = SyncSettings().load()

    assert not hasattr(config, "exists"), "the flag must come from SyncSettings"
    assert SyncSettings().exists is True
