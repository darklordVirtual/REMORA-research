"""SR-22 / SEC-11: RAG-oracle transport and HTTP failures must surface as
errors, never as valid quorum votes, and the bearer must reach /query.

On HEAD, ``CloudflareRAGOracle._call`` caught HTTPError/Exception and
returned a response with ``confidence 0.0`` and ``error`` unset, so
``engine.py`` counted a 401 from the worker toward consensus. The
constructor's ``secret`` was never sent.
"""

from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch

from remora.oracles.cloudflare_rag import CloudflareRAGOracle


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://oracle.example/query", code, "denied", {}, io.BytesIO(b"{}")
    )


def test_http_error_is_an_error_not_a_vote() -> None:
    oracle = CloudflareRAGOracle(worker_url="https://oracle.example", secret="tok")
    with patch("urllib.request.urlopen", side_effect=_http_error(401)):
        resp = oracle.ask("is this safe?")

    assert resp.error is not None, (
        "a 401 from the worker was returned as a valid (error-free) response "
        "and counted toward quorum"
    )


def test_transport_error_is_an_error_not_a_vote() -> None:
    oracle = CloudflareRAGOracle(worker_url="https://oracle.example", secret="tok")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        resp = oracle.ask("is this safe?")

    assert resp.error is not None


def test_bearer_is_sent_when_secret_configured() -> None:
    oracle = CloudflareRAGOracle(worker_url="https://oracle.example", secret="tok-123")
    captured: dict = {}

    class _Resp:
        def read(self):
            return b'{"answer": true, "claim": "ok", "confidence": 0.9}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _capture(req, **kwargs):
        captured["auth"] = req.headers.get("Authorization")
        return _Resp()

    with patch("urllib.request.urlopen", side_effect=_capture):
        resp = oracle.ask("is this safe?")

    assert resp.error is None
    assert captured["auth"] == "Bearer tok-123"


def test_no_bearer_header_when_no_secret() -> None:
    oracle = CloudflareRAGOracle(worker_url="https://oracle.example")
    captured: dict = {}

    class _Resp:
        def read(self):
            return b'{"answer": true, "claim": "ok", "confidence": 0.9}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _capture(req, **kwargs):
        captured["auth"] = req.headers.get("Authorization")
        return _Resp()

    with patch("urllib.request.urlopen", side_effect=_capture):
        oracle.ask("is this safe?")

    assert captured["auth"] is None
