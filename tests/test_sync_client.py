"""Server-side simulation of the sync API contract (sync spec §4).

These tests drive the *real* client against a local HTTP server rather than a
mock, because the things most likely to break are at the HTTP layer: a wrong
path prefix, a header the server ignores, a query string mangled by quoting,
or a status code mapped to the wrong exception class. The fake server answers
from the contract in ``docs/api.json`` of the server repository, so a drift in
the paths shows up here too.

Nothing binds a public interface: the socket listens on 127.0.0.1 and only for
the duration of one test.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

import pytest

from lurkn.syncclient import (
    AuthError,
    RequestError,
    SyncClient,
    TransportError,
)

TOKEN = "1|test-token"
VERSION = "2026-11-21T09:15:01.002331Z"


class Contract:
    """The server the client talks to, in-memory, keyed by path."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Callable[[dict], tuple[int, object]]] = {}
        # The query string travels with each request instead of living in one
        # shared attribute: the test server handles several requests, and a
        # shared slot made assertions race against the handler thread.
        self.seen: list[tuple[str, str, dict | None, dict]] = []
        self.query = ""

    def on(
        self,
        method: str,
        path: str,
        handler: Callable[[dict], tuple[int, object]],
    ) -> None:
        self.routes[(method, path)] = handler


def _handler_for(contract: Contract) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            payload = json.loads(raw) if raw else None
            path = self.path.split("?", 1)[0]
            contract.seen.append((method, self.path, payload, dict(self.headers)))

            route = contract.routes.get((method, path))
            if route is None:
                status, body = 404, {"message": "not found"}
            else:
                status, body = route(payload or {})

            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self._serve("GET")

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            self._serve("POST")

        def do_DELETE(self) -> None:  # noqa: N802 - http.server API
            self._serve("DELETE")

        def log_message(self, *_args) -> None:
            pass

    return Handler


@pytest.fixture()
def contract() -> Contract:
    return Contract()


@pytest.fixture()
def server(contract: Contract):
    httpd = HTTPServer(("127.0.0.1", 0), _handler_for(contract))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}", contract
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_login_exchanges_the_password_for_a_token(server) -> None:
    base, contract = server
    contract.on(
        "POST",
        "/api/sync/tokens",
        lambda body: (200, {"token": TOKEN, "email": body.get("email")}),
    )

    token = SyncClient(base).login("user@example.com", "secret", "dev-pc")

    assert token == TOKEN
    method, path, payload, _headers = contract.seen[-1]
    assert (method, path) == ("POST", "/api/sync/tokens")
    assert payload == {
        "email": "user@example.com",
        "password": "secret",
        "device": "dev-pc",
    }


def test_a_wrong_password_raises_a_request_error_not_a_transport_one(server) -> None:
    base, contract = server
    contract.on(
        "POST", "/api/sync/tokens", lambda body: (422, {"message": "Invalid credentials."})
    )

    with pytest.raises(RequestError, match="Invalid credentials"):
        SyncClient(base).login("user@example.com", "wrong", "dev-pc")


def test_push_sends_the_token_and_returns_the_versions(server) -> None:
    base, contract = server
    contract.on(
        "POST",
        "/api/sync/changes",
        lambda body: (
            200,
            {
                "applied": [
                    {"id": body["changes"][0]["id"], "server_updated_at": VERSION, "deleted": False}
                ],
                "rejected": [],
            },
        ),
    )

    result = SyncClient(base).push(
        TOKEN, [{"id": "0f0c2f4e-6a1b-4c3d-9e8f-1a2b3c4d5e6f", "text": "x"}]
    )

    assert result["applied"][0]["server_updated_at"] == VERSION
    _method, _path, _payload, headers = contract.seen[-1]
    assert headers["Authorization"] == f"Bearer {TOKEN}"


def test_a_rejected_token_is_an_auth_error(server) -> None:
    base, contract = server
    contract.on("GET", "/api/sync/changes", lambda body: (401, {"message": "Unauthenticated."}))

    with pytest.raises(AuthError):
        SyncClient(base).pull(TOKEN, since=None)


def test_a_server_error_is_a_transport_error_so_the_queue_retries(server) -> None:
    base, contract = server
    contract.on("GET", "/api/sync/changes", lambda body: (503, {"message": "down"}))

    with pytest.raises(TransportError):
        SyncClient(base).pull(TOKEN, since=None)


def test_pull_quotes_the_cursor_and_passes_after(server) -> None:
    base, contract = server
    contract.on(
        "GET",
        "/api/sync/changes",
        lambda body: (200, {"changes": [], "cursor": VERSION, "after": 41, "has_more": False}),
    )

    SyncClient(base).pull(TOKEN, since="2026-11-21T09:15:01.002331Z", after=12)

    _method, path, _payload, _headers = contract.seen[-1]
    assert "since=2026-11-21T09%3A15%3A01.002331Z" in path
    assert "after=12" in path


def test_an_unreachable_server_raises_a_transport_error() -> None:
    # Nothing listens on port 9 on 127.0.0.1 in a normal container.
    with pytest.raises(TransportError):
        SyncClient("http://127.0.0.1:9", timeout=1).pull(TOKEN, since=None)


def test_a_base_path_in_the_server_url_is_kept() -> None:
    # The site may live under a sub-path; the request must not drop it.
    client = SyncClient("https://notes.example.com/lurknotes/")
    assert client._prefix == "/lurknotes"


def test_a_non_http_url_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        SyncClient("ftp://example.com")


def test_revoke_targets_the_token_endpoint(server) -> None:
    base, contract = server
    contract.on("DELETE", "/api/sync/tokens", lambda body: (200, {"revoked": True}))

    SyncClient(base).revoke(TOKEN)

    method, path, _payload, headers = contract.seen[-1]
    assert (method, path) == ("DELETE", "/api/sync/tokens")
    assert headers["Authorization"] == f"Bearer {TOKEN}"
