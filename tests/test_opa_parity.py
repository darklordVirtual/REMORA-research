# Author: Stian Skogbrott
# License: Apache-2.0
"""OPA policy-parity contract tests.

Two guarantees:

1. **Structural parity** — every ``PolicyObservation`` field the decision path
   (decision_engine, credal, trap_classifier) reads is exported to OPA via
   ``OPAContext``, or explicitly excluded with a justification in
   ``OPA_EXPORT_EXCLUSIONS``. A new engine guard on an unexported field fails
   this test, so the OPA contract cannot silently drift behind the engine.

2. **Decision monotonicity over OPA** — an OPA result can never downgrade
   below the engine's hard-guard floor. A Rego policy that predates a security
   signal (and therefore never evaluates it) is floored by the adapter to the
   engine's hard-block verdict.
"""
from __future__ import annotations

import inspect
import io
import json
import re
from dataclasses import fields as dataclass_fields
from unittest import mock

import remora.credal
import remora.policy.decision_engine as decision_engine
import remora.policy.trap_classifier as trap_classifier
from remora.policy.decision_engine import RemoraDecisionEngine, hard_guard_floor
from remora.policy.observation import PolicyObservation
from remora.policy.opa_adapter import (
    OPA_EXPORT_EXCLUSIONS,
    OPAAdapter,
    OPAContext,
    export_opa_context,
)
from remora.policy.report import DecisionAction, DecisionReason

# ---------------------------------------------------------------------------
# 1. Structural parity
# ---------------------------------------------------------------------------

_DECISION_PATH_MODULES = (decision_engine, remora.credal, trap_classifier)
_OBS_FIELD_RE = re.compile(r"\bobs\.([a-zA-Z_][a-zA-Z0-9_]*)")


def _fields_read_by_decision_path() -> set[str]:
    """Every ``obs.<field>`` access in the decision-path modules."""
    observation_fields = {f.name for f in dataclass_fields(PolicyObservation)}
    read: set[str] = set()
    for module in _DECISION_PATH_MODULES:
        source = inspect.getsource(module)
        for match in _OBS_FIELD_RE.finditer(source):
            name = match.group(1)
            # Keep only real observation fields (filters method calls and
            # attribute chains like obs.question.lower()).
            if name in observation_fields:
                read.add(name)
    return read


def test_every_engine_read_field_is_exported_or_excluded() -> None:
    """The OPA contract must cover every field the decision path reads."""
    read = _fields_read_by_decision_path()
    exported = {f.name for f in dataclass_fields(OPAContext)}
    missing = read - exported - OPA_EXPORT_EXCLUSIONS
    assert not missing, (
        "Decision path reads PolicyObservation fields that OPAContext does not "
        f"export: {sorted(missing)}. Add them to OPAContext (or, if genuinely "
        "audit-only, to OPA_EXPORT_EXCLUSIONS with a justification)."
    )


def test_exclusions_are_not_read_by_decision_path() -> None:
    """No excluded field may be used as an engine guard."""
    read = _fields_read_by_decision_path()
    misused = read & OPA_EXPORT_EXCLUSIONS
    assert not misused, (
        f"Fields in OPA_EXPORT_EXCLUSIONS are read by the decision path: "
        f"{sorted(misused)}. They must be exported to OPA instead."
    )


def test_exported_fields_exist_on_observation() -> None:
    """OPAContext must remain a subset of PolicyObservation (1-to-1 names)."""
    observation_fields = {f.name for f in dataclass_fields(PolicyObservation)}
    exported = {f.name for f in dataclass_fields(OPAContext)}
    phantom = exported - observation_fields
    assert not phantom, f"OPAContext fields missing on PolicyObservation: {sorted(phantom)}"


def test_hard_block_signals_are_exported() -> None:
    """The security signals behind every hard guard must reach OPA."""
    exported = {f.name for f in dataclass_fields(OPAContext)}
    required = {
        "adversarial_detected",
        "schema_valid",
        "tool_forbidden",
        "argument_tainted",
        "coercion_detected",
        "blackmail_pattern_detected",
        "counterfactual_passed",
        "evidence_contradictions",
        "contradiction_cycles",
        "target_environment",
        "oracle_failures",
        "valid_oracle_count",
    }
    assert required <= exported, f"Missing: {sorted(required - exported)}"


def test_export_round_trip_is_json_serialisable() -> None:
    obs = PolicyObservation.from_tool_call(
        name="update_work_order",
        arguments={"order_id": "WO-1123", "status": "closed"},
        risk_tier="high",
        domain="maintenance",
        action_type="write",
        trust_score=0.9,
        phase="ordered",
        adversarial_detected=True,
    )
    ctx = export_opa_context(obs)
    payload = json.dumps(ctx.to_opa_input())
    decoded = json.loads(payload)["input"]
    assert decoded["adversarial_detected"] is True
    assert decoded["target_environment"] == "prod"
    assert decoded["tool_call_hash"] == obs.tool_call_hash


# ---------------------------------------------------------------------------
# 2. Hard-guard floor over OPA results
# ---------------------------------------------------------------------------

_SEVERITY = {
    DecisionAction.ACCEPT: 0,
    DecisionAction.VERIFY: 1,
    DecisionAction.ABSTAIN: 2,
    DecisionAction.ESCALATE: 3,
}


def _adapter_with_opa_response(action: str) -> OPAAdapter:
    """OPAAdapter whose HTTP layer always returns the given OPA action."""
    adapter = OPAAdapter(opa_url="http://opa.test:8181")
    body = json.dumps({
        "result": {
            "action": action,
            "reasons": [],
            "risk_estimate": 0.1,
            "confidence": 0.9,
            "explanation": "permissive test policy",
            "policy_version": "test-policy-v1",
        }
    }).encode("utf-8")
    response = mock.MagicMock()
    response.read.return_value = body
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *a: False
    adapter._urlopen_patch = mock.patch(
        "urllib.request.urlopen", return_value=response
    )
    return adapter


_HARD_GUARD_CASES = [
    ({"adversarial_detected": True}, DecisionAction.ESCALATE,
     DecisionReason.ADMISSION_FIREWALL_BLOCKED),
    ({"schema_valid": False}, DecisionAction.ESCALATE,
     DecisionReason.MALFORMED_CALL_BLOCKED),
    ({"tool_forbidden": True}, DecisionAction.ESCALATE,
     DecisionReason.FORBIDDEN_TOOL_BLOCKED),
    ({"coercion_detected": True}, DecisionAction.ESCALATE,
     DecisionReason.COERCION_BLOCKED),
    ({"blackmail_pattern_detected": True}, DecisionAction.ESCALATE,
     DecisionReason.BLACKMAIL_BLOCKED),
    ({"counterfactual_passed": False}, DecisionAction.ESCALATE,
     DecisionReason.COUNTERFACTUAL_FAILED),
    ({"evidence_contradictions": 2, "contradiction_cycles": 1},
     DecisionAction.ESCALATE, DecisionReason.EVIDENCE_CONTRADICTED),
    ({"evidence_contradictions": 2}, DecisionAction.ABSTAIN,
     DecisionReason.EVIDENCE_CONTRADICTED),
    ({"argument_tainted": True}, DecisionAction.VERIFY,
     DecisionReason.TAINTED_ARGUMENT_VERIFY),
]


def test_opa_accept_cannot_override_any_hard_guard() -> None:
    """A permissive OPA policy must be floored on every hard-block signal."""
    for overrides, floor_action, floor_reason in _HARD_GUARD_CASES:
        obs = PolicyObservation(question="test action", risk_tier="low", **overrides)
        adapter = _adapter_with_opa_response("accept")
        with adapter._urlopen_patch:
            report, fallback_used = adapter.evaluate(obs)
        assert not fallback_used, overrides
        assert report.action == floor_action, overrides
        assert floor_reason in report.reasons, overrides
        assert report.source_of_decision == "opa_hard_guard_floor", overrides
        # VERIFY/ESCALATE require a human; ABSTAIN blocks autonomous
        # execution without demanding review (nothing is executed).
        expected_review = floor_action in {DecisionAction.VERIFY, DecisionAction.ESCALATE}
        assert report.human_review_required == expected_review, overrides
        assert "monotonicity" in report.explanation.lower(), overrides


def test_opa_result_stands_when_no_hard_guard_fires() -> None:
    """A clean observation keeps the OPA verdict untouched."""
    obs = PolicyObservation(
        question="read metrics dashboard",
        risk_tier="low",
        action_type="read",
        trust_score=0.95,
        phase="ordered",
    )
    adapter = _adapter_with_opa_response("accept")
    with adapter._urlopen_patch:
        report, fallback_used = adapter.evaluate(obs)
    assert not fallback_used
    assert report.action == DecisionAction.ACCEPT
    assert report.source_of_decision == "opa"


def test_opa_may_tighten_beyond_the_floor() -> None:
    """OPA saying ESCALATE on a tainted call (floor: VERIFY) is respected."""
    obs = PolicyObservation(
        question="apply config change", risk_tier="low", argument_tainted=True
    )
    adapter = _adapter_with_opa_response("escalate")
    with adapter._urlopen_patch:
        report, _ = adapter.evaluate(obs)
    assert report.action == DecisionAction.ESCALATE
    assert report.source_of_decision == "opa"


def test_floor_matches_engine_decide_on_hard_guards() -> None:
    """hard_guard_floor() and decide() must agree on every hard-guard case.

    Guards against the floor function drifting from the engine: for each
    hard-guard observation the engine's decision must carry the same action
    and include the same reason the floor reports.
    """
    engine = RemoraDecisionEngine()
    for overrides, floor_action, floor_reason in _HARD_GUARD_CASES:
        obs = PolicyObservation(question="test action", risk_tier="low", **overrides)
        floor = hard_guard_floor(obs)
        assert floor == (floor_action, floor_reason), overrides
        report = engine.decide(obs)
        assert report.action == floor_action, overrides
        assert floor_reason in report.reasons, overrides


def test_engine_never_returns_below_floor_severity() -> None:
    """Property: decide() severity >= hard_guard_floor severity, always."""
    engine = RemoraDecisionEngine()
    base_variants = [
        {},
        {"risk_tier": "critical", "action_type": "destructive_write"},
        {"trust_score": 0.99, "phase": "ordered", "risk_tier": "low",
         "action_type": "read"},
    ]
    for overrides, _, _ in _HARD_GUARD_CASES:
        for base in base_variants:
            obs = PolicyObservation(question="x", **{**base, **overrides})
            floor = hard_guard_floor(obs)
            assert floor is not None
            report = engine.decide(obs)
            assert _SEVERITY[report.action] >= _SEVERITY[floor[0]], (
                overrides, base,
            )


def test_floor_report_survives_json_audit_serialisation() -> None:
    """The floored report's explanation records the original OPA verdict."""
    obs = PolicyObservation(question="x", tool_forbidden=True)
    adapter = _adapter_with_opa_response("accept")
    with adapter._urlopen_patch:
        report, _ = adapter.evaluate(obs)
    assert "accept" in report.explanation
    assert "forbidden_tool_blocked" in report.explanation
    buffer = io.StringIO()
    json.dump({"action": report.action.value, "explanation": report.explanation}, buffer)
    assert buffer.getvalue()


def test_high_risk_conditional_gates_floor_opa_results() -> None:
    """P1 review finding: conditional risk gates (production-write matrix,
    missing rollback) must also be monotone floors on high/critical risk —
    an OPA policy may only relax decisions in the low/medium band."""
    engine = RemoraDecisionEngine()
    conditional_cases = [
        # Production-write matrix: high-risk production write → VERIFY
        PolicyObservation(
            question="apply work order", risk_tier="high",
            action_type="production_write", target_environment="prod",
            schema_valid=True, trust_score=0.95, phase="ordered",
            evidence_action="answer", evidence_confidence=0.9,
        ),
        # Missing rollback on high risk → ESCALATE
        PolicyObservation(
            question="apply migration", risk_tier="high",
            action_type="write", schema_valid=True,
            rollback_available=False, trust_score=0.95, phase="ordered",
        ),
        # Critical tier with no evidence → conservative routing
        PolicyObservation(
            question="rotate root key", risk_tier="critical",
            action_type="permission_change", schema_valid=True,
            trust_score=0.99, phase="ordered",
        ),
    ]
    for obs in conditional_cases:
        engine_action = engine.decide(obs).action
        assert engine_action != DecisionAction.ACCEPT  # precondition sanity
        adapter = _adapter_with_opa_response("accept")
        with adapter._urlopen_patch:
            report, fallback_used = adapter.evaluate(obs)
        assert not fallback_used
        assert _SEVERITY[report.action] >= _SEVERITY[engine_action], obs.question
        assert report.source_of_decision == "opa_engine_floor", obs.question


def test_low_risk_opa_result_not_floored_by_conditional_gates() -> None:
    """The full-engine floor applies only to fail-closed tiers: on low risk
    an OPA policy remains authoritative in the probabilistic band."""
    obs = PolicyObservation(
        question="update internal wiki page", risk_tier="low",
        action_type="write", schema_valid=True,
        trust_score=0.4, phase="disordered",  # engine alone would not accept
    )
    adapter = _adapter_with_opa_response("accept")
    with adapter._urlopen_patch:
        report, _ = adapter.evaluate(obs)
    assert report.action == DecisionAction.ACCEPT
    assert report.source_of_decision == "opa"


def test_high_risk_opa_tighten_still_respected() -> None:
    """OPA saying ESCALATE where the engine says VERIFY must stand."""
    obs = PolicyObservation(
        question="apply work order", risk_tier="high",
        action_type="production_write", target_environment="prod",
        schema_valid=True, trust_score=0.95, phase="ordered",
        evidence_action="answer", evidence_confidence=0.9,
    )
    adapter = _adapter_with_opa_response("escalate")
    with adapter._urlopen_patch:
        report, _ = adapter.evaluate(obs)
    assert report.action == DecisionAction.ESCALATE
    assert report.source_of_decision == "opa"
