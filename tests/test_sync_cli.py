"""``lurknotes sync …`` from the terminal (sync spec §6).

The command must work where the deck cannot: a headless box, a fresh install,
or a second "device" on the same machine. The password never appears in argv.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from lurkn import synccmd
from lurkn.queue import Queue
from lurkn.syncsettings import ON, PAUSED, SyncConfig, SyncSettings
from lurkn.syncer import Syncer


@pytest.fixture()
def data_home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path / "lurknotes"


class FakeClient:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.revoked: list[str] = []

    def login(self, email: str, password: str, device: str) -> str:
        if self.fail is not None:
            raise self.fail
        return f"token-for-{email}"

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


def run(argv: list[str], password: str = "") -> tuple[int, str]:
    out = io.StringIO()
    code = synccmd.run(argv, stdin=io.StringIO(password + "\n"), stdout=out)
    return code, out.getvalue()


def install_fake(monkeypatch, client: FakeClient) -> None:
    monkeypatch.setattr("lurkn.synccmd.SyncClient", lambda _server: client)


def test_login_writes_an_enabled_private_settings_file(data_home, monkeypatch) -> None:
    install_fake(monkeypatch, FakeClient())

    code, output = run(
        ["login", "--server", "https://notes.example.com", "--email", "user@example.com"],
        password="secret",
    )

    assert code == 0
    assert "user@example.com" in output
    settings = SyncSettings(data_home / "sync.json").load()
    assert settings.state() == ON
    assert settings.token == "token-for-user@example.com"
    assert (data_home / "sync.json").stat().st_mode & 0o777 == 0o600


def test_login_asks_for_a_password_on_stdin(data_home, monkeypatch) -> None:
    install_fake(monkeypatch, FakeClient())

    code, output = run(
        ["login", "--server", "https://notes.example.com", "--email", "u@e.com"]
    )

    assert code == 2
    assert "no password on stdin" in output
    assert not (data_home / "sync.json").exists()


def test_login_reports_a_wrong_password_without_writing_settings(
    data_home, monkeypatch
) -> None:
    from lurkn.syncclient import AuthError

    install_fake(monkeypatch, FakeClient(fail=AuthError("rejected")))

    code, output = run(
        ["login", "--server", "https://n.example.com", "--email", "u@e.com"],
        password="wrong",
    )

    assert code == 1
    assert "rejected the password" in output
    assert not (data_home / "sync.json").exists()


def test_login_rejects_an_unknown_option_instead_of_guessing(data_home) -> None:
    code, output = run(["login", "--server", "https://n.example.com", "--oops", "x"])

    assert code == 2
    assert "usage" in output


def test_status_reports_off_paused_and_on(data_home) -> None:
    code, output = run(["status"])
    assert code == 0 and "sync is off" in output

    SyncSettings(data_home / "sync.json").save(SyncConfig(token="t", enabled=False))
    _code, output = run(["status"])
    assert "paused" in output

    SyncSettings(data_home / "sync.json").save(
        SyncConfig(enabled=True, token="t", email="u@e.com", server="https://n", last_sync="2026-11-21T09:00:00Z")
    )
    _code, output = run(["status"])
    assert "sync on for u@e.com" in output
    assert "2026-11-21T09:00:00Z" in output


def test_logout_forgets_the_token_and_the_queue(data_home, monkeypatch) -> None:
    client = FakeClient()
    install_fake(monkeypatch, client)
    path = data_home / "sync.json"
    SyncSettings(path).save(
        SyncConfig(enabled=True, token="t", server="https://n", email="u@e.com")
    )
    Queue(data_home / "queue.json").enqueue(
        __import__("lurkn.queue", fromlist=["PendingChange"]).PendingChange(
            id="a", text="x", position=0, created=1.0
        )
    )

    code, output = run(["logout"])

    assert code == 0
    assert "sync disabled" in output
    assert client.revoked == ["t"]
    assert not path.exists()
    assert not (data_home / "queue.json").exists()


def test_an_unknown_subcommand_prints_the_usage(data_home) -> None:
    code, output = run(["publish"])

    assert code == 2
    assert "unknown sync command" in output
    assert "usage" in output
