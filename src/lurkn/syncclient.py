"""HTTP client for the sync API (sync spec §4, §6.2).

Deliberately built on ``http.client`` and ``ssl`` from the core24 base: no new
dependency, nothing to stage into the snap. ``urllib`` would silently pick up
proxy settings from the environment, which for a privacy-minded notes app is
the wrong default.

Nothing in this module opens a socket at import time, and the app imports it
lazily, only once sync is switched on — the "no network sockets" acceptance
check depends on that.

Errors are split by what the caller must do:

* :class:`AuthError` — the token is gone or wrong: stop syncing and ask the
  user to sign in again.
* :class:`RequestError` — the server rejected the payload: drop that change,
  do not retry it forever.
* :class:`TransportError` — the network or the server is unavailable: keep
  the change queued and retry with backoff.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urlsplit


class SyncError(Exception):
    """Base class for every failure this module raises."""


class AuthError(SyncError):
    """The device token was rejected (401/403)."""


class RequestError(SyncError):
    """The server refused this payload (4xx other than auth)."""


class TransportError(SyncError):
    """The request never completed: DNS, TLS, timeout, 5xx."""


@dataclass(frozen=True)
class Response:
    status: int
    body: dict | list | None


class SyncClient:
    """One HTTPS endpoint, one token, no shared state between calls."""

    def __init__(
        self,
        server: str,
        *,
        timeout: float = 15.0,
        context: ssl.SSLContext | None = None,
    ) -> None:
        parsed = urlsplit(server)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"not an http(s) URL: {server!r}")
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = parsed.port
        self._prefix = parsed.path.rstrip("/")
        self._timeout = timeout
        self._context = context

    # -- public calls --------------------------------------------------

    def login(self, email: str, password: str, device: str) -> str:
        """Trade the account password for a device token (spec §4.1)."""
        response = self._request(
            "POST",
            "/api/sync/tokens",
            {"email": email, "password": password, "device": device},
        )
        token = response.body.get("token") if isinstance(response.body, dict) else None
        if not isinstance(token, str) or not token:
            raise TransportError("the server did not return a token")
        return token

    def revoke(self, token: str) -> None:
        self._request("DELETE", "/api/sync/tokens", None, token=token)

    def push(self, token: str, changes: list[dict]) -> dict:
        """Apply changes; the response carries versions for what was applied."""
        response = self._request(
            "POST", "/api/sync/changes", {"changes": changes}, token=token
        )
        return response.body if isinstance(response.body, dict) else {}

    def pull(self, token: str, *, since: str | None, after: int | None = None) -> dict:
        query = []
        if since:
            query.append(f"since={_quote(since)}")
        if after is not None:
            query.append(f"after={after}")
        path = "/api/sync/changes"
        if query:
            path += "?" + "&".join(query)
        response = self._request("GET", path, None, token=token)
        return response.body if isinstance(response.body, dict) else {}

    # -- transport -----------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None,
        *,
        token: str | None = None,
    ) -> Response:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"

        connection = self._connect()
        try:
            connection.request(method, self._prefix + path, body=body, headers=headers)
            raw = connection.getresponse()
            status = raw.status
            data = raw.read()
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise TransportError(str(exc)) from exc
        finally:
            connection.close()

        parsed: dict | list | None = None
        if data:
            try:
                parsed = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None

        if status in (401, 403):
            raise AuthError(_message(parsed) or "the device token was rejected")
        if 400 <= status < 500:
            raise RequestError(_message(parsed) or f"HTTP {status}")
        if status >= 500:
            raise TransportError(_message(parsed) or f"HTTP {status}")
        return Response(status=status, body=parsed)

    def _connect(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            context = self._context or ssl.create_default_context()
            return http.client.HTTPSConnection(
                self._host, self._port, timeout=self._timeout, context=context
            )
        return http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )


def _message(body: object) -> str:
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str):
            return message
    return ""


def _quote(value: str) -> str:
    # Timestamps are ISO-8601; quote the colon so proxies keep it intact.
    return value.replace(":", "%3A").replace("+", "%2B")
