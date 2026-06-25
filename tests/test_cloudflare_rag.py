# Author: Stian Skogbrott
# License: Apache-2.0
"""
Tests for CloudflareRAGOracle.

Unit tests use a mock HTTP server so no API key or live Worker is required.
Integration tests (marked live) require REMORA_RAG_WORKER_URL to be set.
"""
from __future__ import annotations

import json
import unittest.mock as mock

import pytest

from remora.oracles.cloudflare_rag import CloudflareRAGOracle


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(data: dict, status: int = 200):
    """Build a fake urllib response."""
    body = json.dumps(data).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


# ── Unit tests (no network) ───────────────────────────────────────────────────

class TestCloudflareRAGOracleUnit:

    def _oracle(self, **kwargs) -> CloudflareRAGOracle:
        return CloudflareRAGOracle(
            worker_url="https://test-worker.example.com",
            **kwargs,
        )

    def test_name_includes_domain(self):
        assert self._oracle(domain="science").name == "cloudflare_rag/science:rerank"
        assert self._oracle(domain=None).name == "cloudflare_rag/all:rerank"

    def test_set_domain_updates_name(self):
        oracle = self._oracle(domain=None)
        assert oracle.domain is None
        oracle.set_domain("science")
        assert oracle.domain == "science"
        assert oracle.name == "cloudflare_rag/science:rerank"

    def test_call_returns_valid_verdict_true(self):
        payload = {
            "answer": True, "claim": "DNA is a double helix",
            "confidence": 0.95, "sources": ["NCBI"],
            "retrieved_chunks": 3, "cache_hit": False,
            "model": "@cf/meta/llama-3.1-8b-instruct",
        }
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(payload)):
            oracle = self._oracle()
            response = oracle.ask("Is DNA a double helix?")

        assert response.provider == oracle.name
        extracted = response.extracted
        assert extracted["answer"] is True
        assert extracted["confidence"] == pytest.approx(0.95)
        assert "double helix" in extracted["claim"].lower()

    def test_call_returns_valid_verdict_false(self):
        payload = {
            "answer": False, "claim": "Sydney is not the capital",
            "confidence": 1.0, "sources": ["World Atlas"],
            "retrieved_chunks": 1, "cache_hit": True,
            "model": "@cf/meta/llama-3.1-8b-instruct",
        }
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(payload)):
            oracle = self._oracle()
            response = oracle.ask("Is Sydney the capital of Australia?")

        assert response.extracted["answer"] is False
        assert response.extracted["confidence"] == pytest.approx(1.0)

    def test_call_handles_null_answer(self):
        payload = {
            "answer": None, "claim": "Insufficient evidence in corpus",
            "confidence": 0.0, "sources": [],
            "retrieved_chunks": 0, "cache_hit": False,
            "model": "@cf/meta/llama-3.1-8b-instruct",
        }
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(payload)):
            oracle = self._oracle()
            response = oracle.ask("Highly obscure domain question?")

        assert response.extracted["answer"] is None
        assert response.extracted["confidence"] == pytest.approx(0.0)

    def test_call_handles_http_error_gracefully(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.HTTPError(None, 503, "Service Unavailable", {}, None)):
            oracle = self._oracle()
            response = oracle.ask("Any question?")

        extracted = response.extracted
        assert extracted["answer"] is None
        assert extracted["confidence"] == pytest.approx(0.0)
        assert "503" in extracted["claim"]

    def test_call_handles_connection_error_gracefully(self):
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionError("timed out")):
            oracle = self._oracle()
            response = oracle.ask("Any question?")

        assert response.extracted["answer"] is None

    def test_top_k_clamped(self):
        oracle_low  = self._oracle(top_k=0)
        oracle_high = self._oracle(top_k=999)
        assert oracle_low._top_k == 1
        assert oracle_high._top_k == 10

    def test_oracle_implements_abc(self):
        from remora.core import Oracle
        oracle = self._oracle()
        assert isinstance(oracle, Oracle)

    def test_cost_is_zero(self):
        """Workers AI billed at account level; per-call cost is reported as zero."""
        payload = {
            "answer": True, "claim": "test", "confidence": 0.9,
            "sources": [], "retrieved_chunks": 1, "cache_hit": False,
            "model": "test",
        }
        with mock.patch("urllib.request.urlopen", return_value=_mock_response(payload)):
            oracle = self._oracle()
            response = oracle.ask("test?")
        assert response.cost_usd == pytest.approx(0.0)

    def test_ingest_requires_secret(self):
        oracle = self._oracle(secret=None)
        with pytest.raises(ValueError, match="secret"):
            oracle.ingest("content", "source", "science")


# ── Integration test (requires live Worker) ───────────────────────────────────

@pytest.mark.live
class TestCloudflareRAGOracleLive:
    """
    Requires environment variable REMORA_RAG_WORKER_URL or uses the default
    deployed Worker. Mark with pytest -m live to run.
    """

    @pytest.fixture
    def oracle(self):
        import os
        url = os.environ.get(
            "REMORA_RAG_WORKER_URL",
            "https://remora-rag-oracle.razorsharp.workers.dev",
        )
        return CloudflareRAGOracle(worker_url=url, domain=None, top_k=5)

    def test_status_endpoint(self, oracle):
        status = oracle.status()
        assert status["ok"] is True
        assert "total_chunks" in status
        assert status["embed_model"] == "@cf/baai/bge-base-en-v1.5"

    def test_dna_double_helix(self, oracle):
        response = oracle.ask("Is DNA a double helix?")
        assert response.extracted["answer"] is True
        assert response.extracted["confidence"] > 0.5

    def test_sydney_not_capital(self, oracle):
        oracle.set_domain("general")
        response = oracle.ask("Is the capital of Australia Sydney?")
        assert response.extracted["answer"] is False

    def test_vaccines_autism(self, oracle):
        oracle.set_domain("science")
        response = oracle.ask("Do vaccines cause autism?")
        assert response.extracted["answer"] is False
        assert response.extracted["confidence"] > 0.5

    def test_unknown_domain_returns_null(self, oracle):
        oracle.set_domain("nonexistent_domain_xyz")
        response = oracle.ask("Some question in an unknown domain?")
        # Should return null with zero confidence, not crash
        assert response.extracted.get("answer") is None or response.extracted.get("confidence", 0) < 0.3

    def test_raw_search(self, oracle):
        matches = oracle.search("CRISPR gene editing", k=3)
        assert isinstance(matches, list)
        # With seed corpus, should find the CRISPR document
        if matches:
            assert "score" in matches[0]
            assert "source" in matches[0]
