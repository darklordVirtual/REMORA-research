"""SR-02/SR-04 review follow-up: the worker now requires the bearer on every
route except /status, so the client's debug helpers (/rerank, /translate)
must send it too, or they fail closed against every deployment."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from remora.oracles.cloudflare_rag import CloudflareRAGOracle


def _capture(store: dict, body: dict):
    def _urlopen(req, *args, **kwargs):
        store["auth"] = req.get_header("Authorization")
        store["url"] = req.full_url
        resp = io.BytesIO(json.dumps(body).encode())
        resp.__enter__ = lambda s=resp: s  # type: ignore[attr-defined]
        resp.__exit__ = lambda *a: False  # type: ignore[attr-defined]
        return resp

    return _urlopen


@pytest.mark.parametrize(
    "call, body",
    [
        (lambda o: o.rerank("q", ["a", "b"]), {"results": []}),
        (lambda o: o.translate("hei"), {"translated_text": "hi"}),
    ],
    ids=["rerank", "translate"],
)
def test_debug_helpers_send_bearer(call, body) -> None:
    oracle = CloudflareRAGOracle(worker_url="https://oracle.test", secret="s3cret")
    seen: dict = {}
    with patch("urllib.request.urlopen", side_effect=_capture(seen, body)):
        call(oracle)
    assert seen["auth"] == "Bearer s3cret"


def test_debug_helpers_send_no_bearer_without_secret() -> None:
    oracle = CloudflareRAGOracle(worker_url="https://oracle.test", secret=None)
    seen: dict = {}
    with patch("urllib.request.urlopen", side_effect=_capture(seen, {"results": []})):
        oracle.rerank("q", ["a"])
    assert seen["auth"] is None
