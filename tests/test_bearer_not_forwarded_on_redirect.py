# SPDX-License-Identifier: BUSL-1.1
"""RMR-SEC-0008: a bearer is never forwarded across a redirect.

urllib's redirect handler copies a request's ordinary headers to the
redirected request, so a 302 from the oracle URL (a compromised route, a
misconfigured proxy, a captive portal) handed ORACLE_SECRET or
AGENT_CONTROL_SECRET to whatever host the Location named. The clients now
attach Authorization as an unredirected header: it reaches the configured
endpoint and nothing it redirects to.
"""
from __future__ import annotations

import http.server
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "servers"))
import mcp_remora  # noqa: E402

from remora.oracles.cloudflare_rag import CloudflareRAGOracle  # noqa: E402

_SECRET = "bearer-that-must-stay-home"


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, str | None]]
    location: str | None = None

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        if type(self).location:
            self.send_response(302)
            self.send_header("Location", type(self).location + self.path)
            self.end_headers()
            return
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _handle

    def log_message(self, *_args) -> None:  # keep test output clean
        pass


def _serve(location: str | None):
    handler = type("H", (_Recorder,), {"seen": [], "location": location})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, handler, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def hop():
    other, other_h, other_url = _serve(None)
    home, home_h, home_url = _serve(other_url)
    yield home_url, home_h, other_h
    home.shutdown()
    other.shutdown()


def test_mcp_rag_bearer_reaches_the_oracle_but_not_the_redirect_target(hop, monkeypatch) -> None:
    home_url, home_h, other_h = hop
    monkeypatch.setattr(mcp_remora, "RAG_WORKER", home_url)
    monkeypatch.setattr(mcp_remora, "RAG_SECRET", _SECRET)
    mcp_remora._get(f"{home_url}/search?q=x")
    mcp_remora._post(f"{home_url}/query", {"query": "x"})
    assert [auth for _, auth in home_h.seen] == [f"Bearer {_SECRET}"] * 2
    assert other_h.seen, "the redirect must have been followed for this test to mean anything"
    assert all(auth is None for _, auth in other_h.seen)


def test_mcp_agent_control_bearer_is_not_forwarded(hop, monkeypatch) -> None:
    home_url, home_h, other_h = hop
    monkeypatch.setattr(mcp_remora, "AGENT_CONTROL", home_url)
    monkeypatch.setattr(mcp_remora, "AGENT_SECRET", _SECRET)
    mcp_remora._agent_post("/sessions", {"user_label": "t"})
    assert home_h.seen and home_h.seen[0][1] == f"Bearer {_SECRET}"
    assert other_h.seen and all(auth is None for _, auth in other_h.seen)


def test_python_rag_client_bearer_is_not_forwarded(hop) -> None:
    home_url, home_h, other_h = hop
    oracle = CloudflareRAGOracle(worker_url=home_url, secret=_SECRET)
    oracle._get("/status")
    assert home_h.seen[0][1] == f"Bearer {_SECRET}"
    assert other_h.seen and all(auth is None for _, auth in other_h.seen)
