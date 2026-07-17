# Author: Stian Skogbrott
# License: Apache-2.0
"""The industrial-maintenance demo must drive the real engine with canonical
outcomes.

Pins the demo's five-step autonomy boundary to actual RemoraDecisionEngine
behavior: reads ACCEPT, tainted work-order proposals VERIFY, contradicting
evidence ABSTAINs, and undelegated OT actuation hard-ESCALATEs — so the demo
can never drift into narrating outcomes the engine does not produce.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from remora.policy import RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason

ROOT = Path(__file__).resolve().parents[1]


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "demo_industrial_maintenance",
        ROOT / "scripts" / "demo_industrial_maintenance.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_industrial_maintenance"] = module
    spec.loader.exec_module(module)
    return module


demo = _load_demo()

EXPECTED = {
    "read_vibration_telemetry": (DecisionAction.ACCEPT, None),
    "read_equipment_history": (DecisionAction.ACCEPT, None),
    # High-risk production write → the explicit production-write policy
    # matrix requires human review (engine reason: evidence_insufficient).
    "propose_workorder_change": (
        DecisionAction.VERIFY, DecisionReason.EVIDENCE_INSUFFICIENT,
    ),
    "propose_with_contradicting_evidence": (
        DecisionAction.ABSTAIN, DecisionReason.EVIDENCE_CONTRADICTED,
    ),
    "direct_ot_actuation": (
        DecisionAction.ESCALATE, DecisionReason.FORBIDDEN_TOOL_BLOCKED,
    ),
}


def test_demo_uses_real_engine() -> None:
    src = (ROOT / "scripts" / "demo_industrial_maintenance.py").read_text(
        encoding="utf-8"
    )
    assert "RemoraDecisionEngine" in src
    assert "PolicyObservation" in src


def test_every_step_produces_the_narrated_outcome() -> None:
    engine = RemoraDecisionEngine()
    actions = {a.label: a for a in demo.build_actions()}
    assert set(actions) == set(EXPECTED)
    for label, (expected_action, expected_reason) in EXPECTED.items():
        report = engine.decide(actions[label].observation)
        assert report.action == expected_action, label
        if expected_reason is not None:
            assert expected_reason in report.reasons, label


def test_actuation_block_is_confidence_independent() -> None:
    """High trust and strong evidence must not unlock undelegated actuation."""
    engine = RemoraDecisionEngine()
    actuation = {a.label: a for a in demo.build_actions()}["direct_ot_actuation"]
    assert actuation.observation.trust_score >= 0.9
    report = engine.decide(actuation.observation)
    assert report.action == DecisionAction.ESCALATE
    assert report.human_review_required


def test_tool_forbidden_comes_from_a2a_verification_not_hardcoding() -> None:
    """P1 review finding: the demo must derive tool_forbidden from actual
    A2A envelope verification, not from a manually set flag."""
    src = (ROOT / "scripts" / "demo_industrial_maintenance.py").read_text(
        encoding="utf-8"
    )
    assert "tool_forbidden=True" not in src  # no hardcoded flag anywhere
    assert "A2AGovernanceEnvelope" in src
    forbidden, failures = demo.delegation_check("ot:set_pump_speed")
    assert forbidden
    assert any(f.startswith("scope_exceeds_delegation") for f in failures)
    allowed, no_failures = demo.delegation_check("workorder:propose_change")
    assert not allowed
    assert no_failures == ()


def test_delegation_chain_is_per_link_signed_and_verified() -> None:
    """The demo verifies against a key registry: forging a link breaks it."""
    envelope = demo.issue_envelope("telemetry:read")
    good = envelope.verify(
        signing_key=demo.ENVELOPE_KEY,
        expected_audience=demo.AUDIENCE,
        link_keys=demo.LINK_KEYS,
    )
    assert good.valid, good.failures
    # Without the registry key for the second hop, the chain is revoked.
    partial = envelope.verify(
        signing_key=demo.ENVELOPE_KEY,
        expected_audience=demo.AUDIENCE,
        link_keys={"coe-2026": demo.COE_KEY},
    )
    assert not partial.valid


def test_workorder_review_comes_from_policy_matrix_not_taint() -> None:
    """P2 review finding: review is an explicit policy decision — data from
    the operator's controlled maintenance sources is not modeled as tainted."""
    proposal = {a.label: a for a in demo.build_actions()}["propose_workorder_change"]
    assert proposal.observation.argument_tainted is False
    assert proposal.observation.action_type == "production_write"
    assert proposal.observation.risk_tier == "high"


def test_demo_main_runs_and_exits_zero(capsys) -> None:
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "ESCALATE" in out
    assert "forbidden_tool_blocked" in out
