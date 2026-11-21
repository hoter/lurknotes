"""The sync loop: queue in, HTTP out, versions back (sync spec §6).

This module is the only place that knows the order of operations, and the order
is the contract:

1. **Enqueue first.** A local save is written to ``queue.json`` before any
   network call. If the app dies right after, the next launch still knows the
   change exists.
2. **Send, then dequeue by version.** A change leaves the queue only when the
   server accepted it *and* the client stored the returned version, so a crash
   between the two repeats a push instead of losing it. The server's ``base``
   check makes the repeat harmless.
3. **Pull after a successful push** and on start, so another machine's edits
   land without waiting for the periodic pull.

The loop is driven by the app (a background thread plus GLib timers); this
class stays synchronous and free of GLib, which is what makes it testable
against the fake server.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .queue import PendingChange, Queue
from .syncclient import AuthError, RequestError, SyncClient, TransportError
from .syncsettings import SyncConfig, SyncSettings

# What the UI shows; the app maps these onto the status dot and the row.
IDLE = "idle"
SYNCING = "syncing"
NEEDS_ATTENTION = "needs_attention"


@dataclass
class SyncResult:
    """The outcome of one sync pass, for the UI and for tests."""

    state: str
    applied: int = 0
    rejected: int = 0
    pulled: int = 0
    error: str = ""


class Syncer:
    """Push the queue, pull the vault, keep ``sync.json`` current."""

    def __init__(
        self,
        settings: SyncSettings,
        queue: Queue,
        *,
        client_factory: Callable[[str], SyncClient] = SyncClient,
        device: str = "lurknotes",
    ) -> None:
        self.settings = settings
        self.queue = queue
        self._client_factory = client_factory
        self._device = device

    # -- one pass ------------------------------------------------------

    def run_once(self, config: SyncConfig | None = None) -> SyncResult:
        """A full push-then-pull pass; safe to call when sync is off."""
        config = config or self.settings.load()
        if not config.enabled or not config.token or not config.server:
            return SyncResult(state=IDLE)

        client = self._client_factory(config.server)
        result = SyncResult(state=IDLE)

        try:
            result.applied, result.rejected = self._push(client, config)
            pulled, cursor, after = self._pull(client, config)
            result.pulled = pulled
            if pulled or after is not None:
                self.settings.update(cursor=cursor)
        except AuthError as exc:
            # Stop, do not retry: the token is dead until the user signs in.
            result.state = NEEDS_ATTENTION
            result.error = str(exc)
            return result
        except TransportError as exc:
            # Keep everything queued; the app schedules the backoff.
            result.state = NEEDS_ATTENTION
            result.error = str(exc)
            return result

        self.settings.update(last_sync=now_stamp())
        return result

    # -- steps ---------------------------------------------------------

    def _push(self, client: SyncClient, config: SyncConfig) -> tuple[int, int]:
        changes = self.queue.load()
        if not changes:
            return 0, 0

        response = client.push(config.token, [item.to_dict() for item in changes])
        applied = response.get("applied", []) or []
        rejected = response.get("rejected", []) or []

        applied_ids = {entry["id"] for entry in applied if "id" in entry}
        for entry in applied:
            if "id" in entry:
                self.queue.remove(entry["id"])

        # A rejected change is stale: drop it, because the pull that follows
        # returns the winning version and overwrites the local copy anyway.
        rejected_ids = {entry["id"] for entry in rejected if "id" in entry}
        for note_id in rejected_ids - applied_ids:
            self.queue.remove(note_id)

        return len(applied), len(rejected)

    def _pull(
        self, client: SyncClient, config: SyncConfig
    ) -> tuple[int, str, int | None]:
        # Pages until the server says there is nothing left. `after` is needed
        # as well as `since`: a page boundary can share a timestamp.
        since = config.cursor or None
        after: int | None = None
        total = 0
        cursor = config.cursor

        while True:
            response = client.pull(config.token, since=since, after=after)
            changes = response.get("changes", []) or []
            total += len(changes)
            cursor = response.get("cursor") or cursor
            after = response.get("after")
            if not response.get("has_more"):
                break
            since = cursor or since

        return total, cursor, after

    # -- helpers for the app -------------------------------------------

    def enqueue_note(
        self, *, note_id: str, text: str, position: int, created: float, base: str | None
    ) -> None:
        self.queue.enqueue(
            PendingChange(
                id=note_id,
                text=text,
                position=position,
                created=created,
                base=base,
            )
        )

    def enqueue_delete(self, *, note_id: str, base: str | None) -> None:
        self.queue.enqueue(
            PendingChange(
                id=note_id, text="", position=0, created=0.0, base=base, deleted=True
            )
        )

    def sign_out(self) -> None:
        """Forget the account: revoke remotely (best effort) and drop the file."""
        config = self.settings.load()
        if config.token and config.server:
            try:
                self._client_factory(config.server).revoke(config.token)
            except (AuthError, RequestError, TransportError):
                pass
        self.settings.forget()
        self.queue.clear()

    def sign_in(self, *, server: str, email: str, password: str) -> SyncConfig:
        token = self._client_factory(server).login(email, password, self._device)
        return self.settings.save(
            SyncConfig(
                enabled=True,
                server=server,
                email=email,
                token=token,
                cursor="",
                last_sync="",
            )
        )


def now_stamp() -> str:
    """The UI timestamp; UTC so it sorts and reads the same everywhere."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
