"""Tests for remora.adapters.gateway (PR-9)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from remora.adapters.gateway import HttpGateway, LocalGateway
from remora.engine import Remora
from remora.genome import Genome
from remora.oracles.mock import MockOracle


def _make_engine() -> Remora:
    return Remora(
        oracles=[MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)],
        genome=Genome(max_iterations=1, max_subquestions=1),
    )


def test_local_gateway_returns_result() -> None:
    gw = LocalGateway(_make_engine())
    result = gw.assess_sync(question="Is water wet?")
    assert result.action in {"accept", "verify", "abstain", "escalate"}
    assert isinstance(result.human_review_required, bool)
    assert isinstance(result.is_safe_to_proceed, bool)


def test_http_gateway_scheme_validation() -> None:
    try:
        HttpGateway(base_url="ftp://localhost:8000")
        assert False, "Expected ValueError for non-http scheme"
    except ValueError:
        pass


def test_http_gateway_assess_sync_success() -> None:
    gw = HttpGateway(base_url="http://localhost:8000")

    body = {
        "policy_decision": {
            "action": "verify",
            "human_review_required": True,
            "evidence_required": True,
            "explanation": "test",
            "confidence": 0.9,
            "risk_estimate": 0.8,
            "source_of_decision": "python",
            "fallback_used": False,
        },
        "require_rag": True,
        "refuse_parametric_verdict": True,
        "state_hash": "abc123",
    }

    with patch("urllib.request.urlopen") as mock_open:
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp

        out = gw.assess_sync(question="q")

    assert out.action == "verify"
    assert out.human_review_required is True
    assert out.state_hash == "abc123"


def test_http_gateway_assess_sync_unreachable() -> None:
    import urllib.error

    gw = HttpGateway(base_url="http://localhost:8000")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        try:
            gw.assess_sync(question="q")
            assert False, "Expected RuntimeError when gateway unreachable"
        except RuntimeError:
            pass


def test_http_gateway_sends_bearer_token() -> None:
    gw = HttpGateway(base_url="http://localhost:8000", bearer_token="secret")
    body = {
        "policy_decision": {
            "action": "verify",
            "human_review_required": True,
            "evidence_required": True,
            "explanation": "test",
            "confidence": 0.9,
            "risk_estimate": 0.8,
            "source_of_decision": "python",
            "fallback_used": False,
        },
        "require_rag": True,
        "refuse_parametric_verdict": True,
        "state_hash": "abc123",
    }

    with patch("urllib.request.urlopen") as mock_open:
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp

        gw.assess_sync(question="q")

        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer secret"


def test_local_gateway_cache_hit_for_same_context() -> None:
    engine = MagicMock()
    state = object()
    engine.run.return_value = state
    engine.report.return_value = {
        "policy_decision": {
            "action": "verify",
            "human_review_required": True,
            "evidence_required": True,
            "explanation": "cached",
            "confidence": 0.8,
            "risk_estimate": 0.3,
            "source_of_decision": "python",
            "fallback_used": False,
        },
        "require_rag": False,
        "refuse_parametric_verdict": False,
        "state_hash": "state-1",
    }

    gw = LocalGateway(engine)
    r1 = gw.assess_sync(question="same q", risk_tier="low", tenant_id="tenant-a")
    r2 = gw.assess_sync(question="same q", risk_tier="low", tenant_id="tenant-a")

    assert r1 == r2
    assert engine.run.call_count == 1
    metrics = gw.cache_metrics()
    assert metrics["low"]["requests"] == 2
    assert metrics["low"]["hits"] == 1
    assert metrics["low"]["hit_rate"] == 0.5


def test_local_gateway_cache_is_tenant_scoped() -> None:
    engine = MagicMock()
    state = object()
    engine.run.return_value = state
    engine.report.return_value = {
        "policy_decision": {
            "action": "verify",
            "human_review_required": True,
            "evidence_required": True,
            "explanation": "tenant scoped",
            "confidence": 0.8,
            "risk_estimate": 0.3,
            "source_of_decision": "python",
            "fallback_used": False,
        },
        "require_rag": False,
        "refuse_parametric_verdict": False,
        "state_hash": "state-2",
    }

    gw = LocalGateway(engine)
    gw.assess_sync(question="same q", risk_tier="low", tenant_id="tenant-a")
    gw.assess_sync(question="same q", risk_tier="low", tenant_id="tenant-b")

    assert engine.run.call_count == 2
    metrics = gw.cache_metrics()
    assert metrics["low"]["requests"] == 2
    assert metrics["low"]["hits"] == 0


def test_http_gateway_sends_tenant_header() -> None:
    gw = HttpGateway(base_url="http://localhost:8000", bearer_token="secret")
    body = {
        "policy_decision": {
            "action": "verify",
            "human_review_required": True,
            "evidence_required": True,
            "explanation": "test",
            "confidence": 0.9,
            "risk_estimate": 0.8,
            "source_of_decision": "python",
            "fallback_used": False,
        },
        "require_rag": True,
        "refuse_parametric_verdict": True,
        "state_hash": "abc123",
    }

    with patch("urllib.request.urlopen") as mock_open:
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp

        gw.assess_sync(question="q", tenant_id="tenant-x")

        req = mock_open.call_args[0][0]
        assert req.get_header("X-remora-tenant") == "tenant-x"
