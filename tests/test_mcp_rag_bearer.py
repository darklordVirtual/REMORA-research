# SPDX-License-Identifier: BUSL-1.1
"""The MCP server authenticates to the RAG oracle, and only to it.

SR-02 made every rag-oracle route except GET /status require
``Authorization: Bearer <ORACLE_SECRET>``, but the MCP server's _get/_post
sent no credential, so remora_rag_search, remora_rag_query and
remora_legal_analysis failed with 401 against the hardened Worker. The bearer
is ``CLOUDFLARE_ORACLE_SECRET``, the name the Python RAG client already reads,
on the enterprise profile only, and it is attached solely to requests whose
origin is exactly the configured RAG worker.
"""
from __future__ import annotations

import io
import json
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "servers"))
import mcp_remora  # noqa: E402

_RAG = "https://rag.corp.example"
_SECRET = "oracle-secret-for-tests"


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setattr(mcp_remora, "RAG_WORKER", _RAG)
    monkeypatch.setattr(mcp_remora, "RAG_SECRET", _SECRET)
    requests: list = []

    def fake_urlopen(req, **_kwargs):
        requests.append(req)
        return io.BytesIO(json.dumps({"ok": True}).encode())

    with mock.patch.object(mcp_remora.urllib.request, "urlopen", fake_urlopen):
        yield requests


def _auth(req) -> str | None:
    return req.get_header("Authorization")


def test_get_to_rag_worker_carries_the_bearer(sent) -> None:
    mcp_remora._get(f"{_RAG}/search?q=x")
    assert _auth(sent[0]) == f"Bearer {_SECRET}"


def test_post_to_rag_worker_carries_the_bearer(sent) -> None:
    mcp_remora._post(f"{_RAG}/query", {"query": "x"})
    assert _auth(sent[0]) == f"Bearer {_SECRET}"


@pytest.mark.parametrize(
    "url",
    [
        "https://law.corp.example/search",
        "https://rag.corp.example.evil.test/query",
        "http://rag.corp.example/query",
        "https://rag.corp.example:8443/query",
    ],
    ids=["other-host", "lookalike-suffix", "downgraded-scheme", "other-port"],
)
def test_bearer_never_leaves_the_rag_origin(sent, url: str) -> None:
    mcp_remora._get(url)
    mcp_remora._post(url, {})
    assert all(_auth(req) is None for req in sent)


def test_no_bearer_when_secret_unset(sent, monkeypatch) -> None:
    monkeypatch.setattr(mcp_remora, "RAG_SECRET", "")
    mcp_remora._get(f"{_RAG}/search?q=x")
    assert _auth(sent[0]) is None


def test_rag_tools_send_the_bearer_end_to_end(sent) -> None:
    mcp_remora.handle_remora_rag_query({"query": "Does GDPR Article 17 grant erasure?"})
    mcp_remora.handle_remora_rag_search({"query": "erasure"})
    rag_calls = [req for req in sent if req.full_url.startswith(_RAG)]
    assert len(rag_calls) == 2
    assert all(_auth(req) == f"Bearer {_SECRET}" for req in rag_calls)


def test_enterprise_profile_reads_the_oracle_secret() -> None:
    _, urls = mcp_remora.resolve_profile({
        "REMORA_MCP_PROFILE": "enterprise",
        "REMORA_WORKER_URL": "https://remora.corp.example",
        "RAG_WORKER_URL": _RAG,
        "LAW_SEARCH_WORKER_URL": "https://law.corp.example",
        "CLOUDFLARE_ORACLE_SECRET": _SECRET,
    })
    assert urls["rag_secret"] == _SECRET


@pytest.mark.parametrize("profile", ["local", "demo"])
def test_local_and_demo_profiles_never_read_the_secret(profile: str, capsys) -> None:
    _, urls = mcp_remora.resolve_profile({
        "REMORA_MCP_PROFILE": profile,
        "CLOUDFLARE_ORACLE_SECRET": _SECRET,
    })
    capsys.readouterr()
    assert urls["rag_secret"] == ""
