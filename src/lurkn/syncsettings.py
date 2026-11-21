"""Synchronisation settings: ``sync.json`` next to ``notes.json`` (spec sync §3.3).

The file holds everything the app needs to talk to the site: whether sync is
on, which server, the account email, the device token and the pull cursor. It
is optional on purpose: **no file means sync was never configured**, and the
network modules are not even imported. Deleting the file is the documented way
to forget an account.

Two rules are load-bearing:

* The token lives in a ``0600`` file. ``atomic.atomic_write`` re-applies the
  mode on every save, because a file created by an older version or by a
  manual copy could otherwise stay world-readable.
* A corrupt file is treated as "sync off" with an error surfaced to the user,
  never silently overwritten — the token inside is not recoverable from
  anywhere else.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic import atomic_write

VERSION = 1

# Off: no file, or a file with enabled=False and no token.
# Paused: a file with a token but enabled=False — resuming needs no password.
# On: enabled=True and a token.
# Needs attention: enabled=True but the last request was rejected; the caller
# flips this in memory, it is not persisted as a separate flag.
OFF = "off"
PAUSED = "paused"
ON = "on"


class SyncConfigError(Exception):
    """The settings file cannot be read or trusted."""


@dataclass(frozen=True)
class SyncConfig:
    """One immutable snapshot of ``sync.json``."""

    enabled: bool = False
    server: str = ""
    email: str = ""
    token: str = ""
    cursor: str = ""
    last_sync: str = ""

    def state(self) -> str:
        """Which of the three persisted states the settings describe."""
        if self.enabled and self.token:
            return ON
        if self.token:
            return PAUSED
        return OFF

    def to_dict(self) -> dict:
        return {
            "version": VERSION,
            "enabled": self.enabled,
            "server": self.server,
            "email": self.email,
            "token": self.token,
            "cursor": self.cursor,
            "last_sync": self.last_sync,
        }

    @classmethod
    def from_dict(cls, data: dict, path: Path) -> "SyncConfig":
        if not isinstance(data, dict):
            raise SyncConfigError(f"{path} must be a JSON object")
        version = data.get("version", VERSION)
        if version != VERSION:
            raise SyncConfigError(f"{path} has unsupported version {version!r}")
        values = {}
        for key in ("enabled", "server", "email", "token", "cursor", "last_sync"):
            value = data.get(key, cls.__dataclass_fields__[key].default)
            if key == "enabled" and not isinstance(value, bool):
                raise SyncConfigError(f"{path} has a non-boolean 'enabled'")
            if key != "enabled" and not isinstance(value, str):
                raise SyncConfigError(f"{path} has a non-string {key!r}")
            values[key] = value
        return cls(**values)


def default_path(data_dir: Path | str | None = None) -> Path:
    """`$XDG_DATA_HOME/lurknotes/sync.json`, beside ``notes.json``."""
    if data_dir is not None:
        return Path(data_dir) / "sync.json"
    configured = os.environ.get("XDG_DATA_HOME")
    base = Path(configured) if configured else Path.home() / ".local" / "share"
    return base / "lurknotes" / "sync.json"


class SyncSettings:
    """Reads and writes ``sync.json``; never touches the network."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        self.last_error: SyncConfigError | None = None
        self._config: SyncConfig | None = None
        self._loaded = False

    # -- reading -------------------------------------------------------

    def load(self) -> SyncConfig:
        """The current settings; an absent file is an all-defaults value."""
        if self._loaded:
            return self._config  # type: ignore[return-value]
        self._loaded = True
        self.last_error = None
        if not self.path.exists():
            self._config = SyncConfig()
            return self._config
        try:
            raw = self.path.read_text(encoding="utf-8")
            document = json.loads(raw)
            self._config = SyncConfig.from_dict(document, self.path)
        except (OSError, json.JSONDecodeError, SyncConfigError) as exc:
            # A broken file must not silently degrade into "never configured":
            # that would hide the account and look like data loss.
            self.last_error = (
                exc if isinstance(exc, SyncConfigError) else SyncConfigError(str(exc))
            )
            self._config = SyncConfig()
        return self._config

    def reload(self) -> SyncConfig:
        self._loaded = False
        return self.load()

    @property
    def exists(self) -> bool:
        return self.path.exists()

    # -- writing -------------------------------------------------------

    def save(self, config: SyncConfig) -> SyncConfig:
        atomic_write(
            self.path,
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
            mode=0o600,
        )
        self._config = config
        self._loaded = True
        self.last_error = None
        return config

    def update(self, **changes: object) -> SyncConfig:
        """Save a copy of the current settings with ``changes`` applied."""
        return self._write(replace(self.load(), **changes))  # type: ignore[arg-type]

    def forget(self) -> None:
        """Remove the file: the documented way back to "never configured"."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._config = SyncConfig()
        self._loaded = True
        self.last_error = None

    def _write(self, config: SyncConfig) -> SyncConfig:
        self.save(config)
        return config
