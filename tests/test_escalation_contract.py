"""Tests for the Human-on-the-Loop Escalation Contract."""
from __future__ import annotations

import json

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.escalation_contract import (
    EscalationPayload,
    build_escalation_payload,
)
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason


def _make_escalate_obs(**kwargs) -> PolicyObservation:
    defaults = dict(
        question="Is the offshore installation compliant with §9-6?",
        phase="disordered",
        trust_score=0.22,
        temperature=1.4,
        final_H=0.95,
        final_D=0.78,
    )
    defaults.update(kwargs)
    return PolicyObservation(**defaults)


def _escalate_report(obs: PolicyObservation | None = None) -> object:
    if obs is None:
        obs = PolicyObservation(
            question="test",
            counterfactual_passed=False,
        )
    engine = RemoraDecisionEngine()
    return engine.decide(obs)


class TestBuildEscalationPayload:
    def test_builds_from_escalate_report(self) -> None:
        obs = PolicyObservation(question="test", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        assert report.action == DecisionAction.ESCALATE
        payload = build_escalation_payload(report)
        assert isinstance(payload, EscalationPayload)

    def test_builds_from_abstain_report(self) -> None:
        obs = PolicyObservation(
            question="test",
            phase="disordered",
            trust_score=0.1,
        )
        report = RemoraDecisionEngine().decide(obs)
        assert report.action == DecisionAction.ABSTAIN
        payload = build_escalation_payload(report)
        assert isinstance(payload, EscalationPayload)

    def test_raises_on_accept_report(self) -> None:
        obs = PolicyObservation(
            question="test",
            phase="ordered",
            trust_score=0.9,
        )
        report = RemoraDecisionEngine(conformal_trust_threshold=0.7).decide(obs)
        if report.action == DecisionAction.ACCEPT:
            with pytest.raises(ValueError, match="ESCALATE/ABSTAIN"):
                build_escalation_payload(report)

    def test_schema_version_is_v1(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report)
        assert payload.schema_version == "escalation-v1"

    def test_prompt_preserved(self) -> None:
        obs = PolicyObservation(question="Is clause 9 enforceable?", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report)
        assert payload.prompt == "Is clause 9 enforceable?"

    def test_trigger_is_primary_reason(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report)
        assert payload.trigger == DecisionReason.COUNTERFACTUAL_FAILED.value

    def test_all_reasons_populated(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report)
        assert len(payload.all_reasons) >= 1
        assert DecisionReason.COUNTERFACTUAL_FAILED.value in payload.all_reasons

    def test_domain_hint_routing(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report, domain_hint="hse")
        assert payload.recommended_routing == "hse_manager"
        assert payload.domain_hint == "hse"

    def test_oracle_responses_included(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        oracle_data = [{"oracle": "llama-70b", "verdict": "false", "confidence": 0.3}]
        payload = build_escalation_payload(report, oracle_responses=oracle_data)
        assert len(payload.oracle_responses) == 1
        assert payload.oracle_responses[0]["oracle"] == "llama-70b"

    def test_uuid_is_unique(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        ids = {build_escalation_payload(report).id for _ in range(10)}
        assert len(ids) == 10

    def test_thermodynamics_populated(self) -> None:
        obs = PolicyObservation(
            question="q",
            counterfactual_passed=False,
            temperature=1.4,
            final_H=0.95,
            final_D=0.78,
            phase="disordered",
        )
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report)
        assert payload.thermodynamics.temperature == pytest.approx(1.4)
        assert payload.thermodynamics.entropy == pytest.approx(0.95)
        assert payload.thermodynamics.dissensus == pytest.approx(0.78)
        assert payload.thermodynamics.phase == "disordered"
        # F = lambda*D - T*H = 1.0*0.78 - 1.4*0.95
        expected_F = 1.0 * 0.78 - 1.4 * 0.95
        assert payload.thermodynamics.free_energy == pytest.approx(expected_F)

    def test_to_dict_is_json_serialisable(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report)
        d = payload.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert "schema_version" in serialised

    def test_action_field_is_string(self) -> None:
        obs = PolicyObservation(question="q", counterfactual_passed=False)
        report = RemoraDecisionEngine().decide(obs)
        payload = build_escalation_payload(report)
        assert payload.action in {"escalate", "abstain"}


class TestEscalationPayloadJsonSchema:
    def test_schema_is_valid_json(self) -> None:
        schema = EscalationPayload.json_schema()
        assert isinstance(schema, dict)
        assert schema["$schema"].startswith("https://json-schema.org")

    def test_schema_has_required_fields(self) -> None:
        schema = EscalationPayload.json_schema()
        required = schema["required"]
        assert "id" in required
        assert "schema_version" in required
        assert "timestamp" in required
        assert "prompt" in required
        assert "trigger" in required
        assert "action" in required

    def test_schema_version_is_escalation_v1(self) -> None:
        schema = EscalationPayload.json_schema()
        assert schema["properties"]["schema_version"]["const"] == "escalation-v1"

    def test_action_enum_values(self) -> None:
        schema = EscalationPayload.json_schema()
        assert "escalate" in schema["properties"]["action"]["enum"]
        assert "abstain" in schema["properties"]["action"]["enum"]

    def test_thermodynamics_subschema_present(self) -> None:
        schema = EscalationPayload.json_schema()
        thermo = schema["properties"]["thermodynamics"]
        assert "temperature" in thermo["properties"]
        assert "entropy" in thermo["properties"]
        assert "dissensus" in thermo["properties"]
        assert "free_energy" in thermo["properties"]
        assert "phase" in thermo["properties"]
