"""Tests for the OPA/Rego adapter and OPAContext serialisation."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.opa_adapter import OPAAdapter, export_opa_context
from remora.policy.report import DecisionAction, DecisionReason


# ---------------------------------------------------------------------------
# OPAContext / export_opa_context
# ---------------------------------------------------------------------------

class TestOPAContext:
    def test_export_maps_all_fields(self) -> None:
        obs = PolicyObservation(
            question="Is the contract enforceable?",
            phase="ordered",
            trust_score=0.87,
            temperature=0.14,
            distribution_shift_detected=False,
            counterfactual_passed=True,
            evidence_action="answer",
            evidence_confidence=0.91,
            evidence_contradictions=0,
            contradiction_cycles=0,
            require_rag=False,
            refuse_parametric_verdict=False,
            claim_graph_betti_1=0,
            conformal_score=None,
        )
        ctx = export_opa_context(obs)
        assert ctx.trust_score == pytest.approx(0.87)
        assert ctx.phase == "ordered"
        assert ctx.distribution_shift_detected is False
        assert ctx.counterfactual_passed is True

    def test_to_opa_input_wraps_in_input_key(self) -> None:
        obs = PolicyObservation(question="test")
        ctx = export_opa_context(obs)
        doc = ctx.to_opa_input()
        assert "input" in doc
        assert isinstance(doc["input"], dict)

    def test_opa_input_is_json_serialisable(self) -> None:
        obs = PolicyObservation(
            question="q",
            trust_score=0.7,
            phase="critical",
        )
        ctx = export_opa_context(obs)
        # Should not raise
        serialised = json.dumps(ctx.to_opa_input())
        assert "trust_score" in serialised

    def test_none_fields_preserved(self) -> None:
        obs = PolicyObservation(question="test")
        ctx = export_opa_context(obs)
        assert ctx.trust_score is None
        assert ctx.phase is None
        assert ctx.temperature is None


# ---------------------------------------------------------------------------
# OPAAdapter — Python fallback (OPA server not running)
# ---------------------------------------------------------------------------

class TestOPAAdapterFallback:
    def test_falls_back_when_opa_unreachable(self) -> None:
        engine = RemoraDecisionEngine(conformal_trust_threshold=0.72)
        adapter = OPAAdapter(
            opa_url="http://localhost:9999",  # nothing listening
            timeout_seconds=0.05,
            fallback_engine=engine,
        )
        obs = PolicyObservation(
            question="Is the NDA valid?",
            phase="ordered",
            trust_score=0.80,
        )
        report, fallback_used = adapter.evaluate(obs)
        assert fallback_used is True
        assert report.action in {DecisionAction.ACCEPT, DecisionAction.ABSTAIN, DecisionAction.VERIFY}

    def test_fallback_engine_none_constructs_default(self) -> None:
        adapter = OPAAdapter(
            opa_url="http://localhost:9999",
            timeout_seconds=0.05,
            fallback_engine=None,
        )
        obs = PolicyObservation(question="test")
        report, fallback_used = adapter.evaluate(obs)
        assert fallback_used is True
        assert report is not None

    def test_fallback_preserves_hard_blocks(self) -> None:
        engine = RemoraDecisionEngine()
        adapter = OPAAdapter(
            opa_url="http://localhost:9999",
            timeout_seconds=0.05,
            fallback_engine=engine,
        )
        obs = PolicyObservation(
            question="test",
            distribution_shift_detected=True,
        )
        report, _ = adapter.evaluate(obs)
        assert report.action == DecisionAction.VERIFY
        assert DecisionReason.DISTRIBUTION_SHIFT in report.reasons

    def test_opa_outage_fail_closed_for_high_risk(self) -> None:
        adapter = OPAAdapter(
            opa_url="http://localhost:9999",
            timeout_seconds=0.05,
            fallback_engine=RemoraDecisionEngine(),
        )
        obs = PolicyObservation(
            question="Should we apply this production change?",
            risk_tier="high",
        )
        report, fallback_used = adapter.evaluate(obs)
        assert fallback_used is True
        assert report.source_of_decision == "opa_fail_closed"
        assert report.action == DecisionAction.VERIFY
        assert report.human_review_required is True
        assert report.fallback_used is True

    def test_opa_outage_fail_closed_for_critical_risk(self) -> None:
        adapter = OPAAdapter(
            opa_url="http://localhost:9999",
            timeout_seconds=0.05,
            fallback_engine=RemoraDecisionEngine(),
        )
        obs = PolicyObservation(
            question="Should we wipe this production database?",
            risk_tier="critical",
        )
        report, fallback_used = adapter.evaluate(obs)
        assert fallback_used is True
        assert report.source_of_decision == "opa_fail_closed"
        assert report.action == DecisionAction.ESCALATE
        assert report.human_review_required is True
        assert report.fallback_used is True


# ---------------------------------------------------------------------------
# OPAAdapter — mocked OPA response
# ---------------------------------------------------------------------------

class TestOPAAdapterMockedResponse:
    def _mock_urlopen(self, result_dict: dict):
        """Context manager that mocks urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": result_dict}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return patch("urllib.request.urlopen", return_value=mock_resp)

    def test_opa_accept_result_mapped(self) -> None:
        adapter = OPAAdapter()
        obs = PolicyObservation(question="test", trust_score=0.9, phase="ordered")

        opa_result = {
            "action": "accept",
            "reasons": ["ordered_high_trust"],
            "confidence": 0.9,
            "risk_estimate": 0.1,
            "explanation": "Accepted.",
            "policy_version": "opa-remora-v1",
        }
        with self._mock_urlopen(opa_result):
            report, fallback_used = adapter.evaluate(obs)

        assert fallback_used is False
        assert report.action == DecisionAction.ACCEPT
        assert DecisionReason.ORDERED_HIGH_TRUST in report.reasons
        assert report.confidence == pytest.approx(0.9)
        assert report.source_of_decision == "opa"

    def test_opa_escalate_result_mapped(self) -> None:
        adapter = OPAAdapter()
        obs = PolicyObservation(question="test", counterfactual_passed=False)

        opa_result = {
            "action": "escalate",
            "reasons": ["counterfactual_failed"],
            "confidence": 0.0,
            "risk_estimate": 1.0,
        }
        with self._mock_urlopen(opa_result):
            report, fallback_used = adapter.evaluate(obs)

        assert fallback_used is False
        assert report.action == DecisionAction.ESCALATE
        assert report.human_review_required is True

    def test_unknown_action_defaults_to_abstain(self) -> None:
        adapter = OPAAdapter()
        obs = PolicyObservation(question="test")

        opa_result = {"action": "totally_unknown_action"}
        with self._mock_urlopen(opa_result):
            report, _ = adapter.evaluate(obs)

        assert report.action == DecisionAction.ABSTAIN

    def test_unknown_reason_skipped(self) -> None:
        adapter = OPAAdapter()
        obs = PolicyObservation(question="test")

        opa_result = {
            "action": "verify",
            "reasons": ["totally_unknown_reason", "critical_phase"],
        }
        with self._mock_urlopen(opa_result):
            report, _ = adapter.evaluate(obs)

        assert DecisionReason.CRITICAL_PHASE in report.reasons

    def test_endpoint_property(self) -> None:
        adapter = OPAAdapter(opa_url="http://opa.internal:8181")
        assert adapter.endpoint == "http://opa.internal:8181/v1/data/remora/policy/decision"

    def test_custom_policy_path(self) -> None:
        adapter = OPAAdapter(policy_path="/v1/data/custom/path")
        assert "/v1/data/custom/path" in adapter.endpoint


# ---------------------------------------------------------------------------
# Integration: decision_engine.py export_opa_context round-trip
# ---------------------------------------------------------------------------

class TestOPAContextRoundTrip:
    def test_all_observation_fields_survive_serialisation(self) -> None:
        obs = PolicyObservation(
            question="test",
            phase="critical",
            trust_score=0.55,
            temperature=0.60,
            distribution_shift_detected=True,
            counterfactual_passed=None,
            evidence_action=None,
            evidence_confidence=None,
            evidence_contradictions=None,
            contradiction_cycles=None,
            require_rag=True,
            refuse_parametric_verdict=False,
            claim_graph_betti_1=1,
            conformal_score=0.48,
        )
        ctx = export_opa_context(obs)
        doc = ctx.to_opa_input()
        inp = doc["input"]

        assert inp["phase"] == "critical"
        assert inp["trust_score"] == pytest.approx(0.55)
        assert inp["distribution_shift_detected"] is True
        assert inp["require_rag"] is True
        assert inp["claim_graph_betti_1"] == 1
        assert inp["conformal_score"] == pytest.approx(0.48)
