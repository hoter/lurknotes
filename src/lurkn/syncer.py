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
from dataclasses import dataclass, field
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
    # The raw wire data, so the app can update versions and merge the deck.
    # Not part of any persisted state.
    changes: list[dict] = field(default_factory=list)
    applied_changes: list[dict] = field(default_factory=list)
    rejected_changes: list[dict] = field(default_factory=list)
    # Called by the app once the accepted versions are stored, so the queue
    # outlives the pull that follows the push.
    finalize: Callable[[], None] | None = None


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
            applied, rejected = self._push(client, config)
            result.applied = len(applied)
            result.rejected = len(rejected)
            result.applied_changes = applied
            result.rejected_changes = rejected
            # The queue is cleared only once the caller has stored the
            # versions; until then the entries are the proof that this note has
            # an edit the server has not fully caught up with. Clearing them
            # before the pull is what let a pull overwrite the editor.
            clear = self.clear_confirmed
            result.finalize = lambda: clear(applied, rejected)
            pulled, cursor, after = self._pull(client, config)
            result.pulled = len(pulled)
            result.changes = pulled
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

    def _push(
        self, client: SyncClient, config: SyncConfig
    ) -> tuple[list[dict], list[dict]]:
        """Send the queue; the caller clears it once the reply is applied.

        Removing entries here looked harmless and broke the guard: the pull
        that follows the push then found an empty queue, believed the note was
        unedited, and overwrote the editor with the server's older copy. So
        this method reports what was accepted and leaves the queue alone —
        :class:`lurkn.syncer.Syncer` clears it after the versions are stored.
        """
        changes = self.queue.load()
        if not changes:
            return [], []

        response = client.push(config.token, [item.to_dict() for item in changes])
        applied = response.get("applied", []) or []
        rejected = response.get("rejected", []) or []

        return list(applied), list(rejected)

    def clear_confirmed(self, applied: list[dict], rejected: list[dict]) -> None:
        """Drop accepted and stale changes once their outcome is on disk."""
        applied_ids = {entry["id"] for entry in applied if "id" in entry}
        rejected_ids = {entry["id"] for entry in rejected if "id" in entry}
        # A rejected change is stale: the pull that follows returns the winning
        # version and overwrites the local copy anyway.
        for note_id in applied_ids | rejected_ids:
            self.queue.remove(note_id)

    def _pull(
        self, client: SyncClient, config: SyncConfig
    ) -> tuple[list[dict], str, int | None]:
        # Pages until the server says there is nothing left. `after` is needed
        # as well as `since`: a page boundary can share a timestamp.
        since = config.cursor or None
        after: int | None = None
        collected: list[dict] = []
        cursor = config.cursor

        while True:
            response = client.pull(config.token, since=since, after=after)
            changes = response.get("changes", []) or []
            collected.extend(changes)
            cursor = response.get("cursor") or cursor
            after = response.get("after")
            if not response.get("has_more"):
                break
            since = cursor or since

        return collected, cursor, after

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
