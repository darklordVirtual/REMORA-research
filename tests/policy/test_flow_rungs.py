# SPDX-License-Identifier: BUSL-1.1
"""IFC-05b: flow rungs F1 to F6 in the hard floor (SDD v1.3 §3.7).

With flow control off (``flow_status`` None) every golden case decides as
RemoraDecisionEngine-v5 did; ``V5_GOLDEN`` was computed with the v5 engine
on the golden set of ``scripts/opa_conformance.py`` before the rungs existed.
With flow on, each rung has a case.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine, hard_guard_floor
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from opa_conformance import golden_observations  # noqa: E402

A, R = DecisionAction, DecisionReason

V5_GOLDEN: dict[str, tuple[str, tuple[str, ...]]] = {
    'hard_guard:adversarial': ('escalate', ('admission_firewall_blocked',)),
    'hard_guard:schema_invalid': ('escalate', ('malformed_call_blocked',)),
    'hard_guard:tool_forbidden': ('escalate', ('forbidden_tool_blocked',)),
    'hard_guard:coercion': ('escalate', ('coercion_blocked',)),
    'hard_guard:blackmail': ('escalate', ('blackmail_blocked',)),
    'hard_guard:counterfactual_failed': ('escalate', ('counterfactual_failed',)),
    'hard_guard:contradiction_cycles': ('escalate', ('evidence_contradicted',)),
    'hard_guard:contradiction_no_cycles': ('abstain', ('evidence_contradicted',)),
    'hard_guard:tainted_argument': ('verify', ('tainted_argument_verify',)),
    'hard_guard:tainted_argument_critical': ('escalate', ('tainted_argument_escalate',)),
    'clean_low_read_ordered': ('accept', ('ordered_high_trust',)),
    'dry_run_staging': ('verify', ('unknown_action_type_verify',)),
    'medium_ordered': ('verify', ('schema_unverified_verify',)),
    'high_no_evidence': ('verify', ('schema_unverified_verify', 'evidence_insufficient')),
    'critical_destructive_prod': ('escalate', ('schema_unverified_verify', 'critical_phase')),
    'disordered_low_trust': ('abstain', ('disordered_no_evidence',)),
    'preview_high_risk_staging': ('verify', ('evidence_insufficient',)),
    'simulate_critical_staging': ('verify', ('evidence_insufficient',)),
}


@pytest.fixture(scope="module")
def engine() -> RemoraDecisionEngine:
    return RemoraDecisionEngine()


def _golden() -> dict[str, PolicyObservation]:
    return dict(golden_observations())


def test_v5_golden_cases_are_unchanged_with_flow_off(engine):
    golden = _golden()
    for name, (action, reasons) in V5_GOLDEN.items():
        report = engine.decide(golden[name])
        assert golden[name].flow_status is None
        assert (report.action.value, tuple(r.value for r in report.reasons)) == (action, reasons), name


@pytest.mark.parametrize("status", ["evaluated", "not_declared"])
def test_a_clean_flow_leaves_every_v5_decision_alone(engine, status):
    golden = _golden()
    for name, (action, reasons) in V5_GOLDEN.items():
        report = engine.decide(dataclasses.replace(golden[name], flow_status=status))
        assert (report.action.value, tuple(r.value for r in report.reasons)) == (action, reasons), name


BASE = dict(question="read metrics", risk_tier="low", action_type="read",
            phase="ordered", trust_score=0.95)


@pytest.mark.parametrize(("fields", "action", "reason"), [
    ({"flow_status": "state_unavailable"}, A.ABSTAIN, R.FLOW_STATE_UNAVAILABLE),           # F1
    ({"flow_status": "context_unknown"}, A.ABSTAIN, R.FLOW_CONTEXT_UNKNOWN),               # F2
    ({"flow_status": "handle_invalid"}, A.ABSTAIN, R.FLOW_HANDLE_INVALID),                 # F2
    ({"flow_status": "policy_missing"}, A.ABSTAIN, R.TOOLSPEC_FLOW_POLICY_MISSING),        # F3
    ({"flow_status": "evaluated", "flow_confidentiality_violation": True},
     A.ESCALATE, R.FLOW_CONFIDENTIALITY_VIOLATION),                                         # F4
    ({"flow_status": "evaluated", "flow_integrity_violation": True},
     A.VERIFY, R.FLOW_INTEGRITY_VIOLATION_VERIFY),                                          # F5
    ({"flow_status": "evaluated", "flow_integrity_violation": True, "risk_tier": "critical"},
     A.ESCALATE, R.FLOW_INTEGRITY_VIOLATION_ESCALATE),                                      # F6
])
def test_each_rung_fires_on_an_otherwise_accepted_call(engine, fields, action, reason):
    assert engine.decide(PolicyObservation(**BASE)).action is A.ACCEPT
    obs = PolicyObservation(**{**BASE, **fields})
    assert hard_guard_floor(obs) == (action, reason)
    report = engine.decide(obs)
    assert report.action is action and reason in report.reasons


def test_an_unknown_status_fails_closed(engine):
    obs = PolicyObservation(**BASE, flow_status="granted_by_the_model")
    assert hard_guard_floor(obs) == (A.ABSTAIN, R.FLOW_STATE_UNAVAILABLE)


def test_violation_flags_without_a_verdict_are_not_read(engine):
    """Only an evaluated verdict carries violations; F1 to F3 decide otherwise."""
    obs = PolicyObservation(**BASE, flow_status="context_unknown",
                            flow_confidentiality_violation=True)
    assert hard_guard_floor(obs) == (A.ABSTAIN, R.FLOW_CONTEXT_UNKNOWN)
    off = PolicyObservation(**BASE, flow_confidentiality_violation=True,
                            flow_integrity_violation=True)
    assert hard_guard_floor(off) is None


def test_confidentiality_beats_integrity_in_the_meet(engine):
    obs = PolicyObservation(**BASE, flow_status="evaluated",
                            flow_confidentiality_violation=True, flow_integrity_violation=True)
    assert engine.decide(obs).action is A.ESCALATE


def test_a_flow_rung_does_not_hide_a_non_approvable_refusal(engine):
    obs = PolicyObservation(**BASE, flow_status="evaluated",
                            flow_confidentiality_violation=True, argument_scope_valid=False)
    assert hard_guard_floor(obs) == (A.ABSTAIN, R.CROSS_TENANT_ARGUMENT_BLOCKED)


def test_legacy_taint_still_adds_to_a_clean_flow(engine):
    """argument_tainted stays downgrade-only beside derived taint (§3.7)."""
    obs = PolicyObservation(**BASE, flow_status="evaluated", argument_tainted=True)
    assert engine.decide(obs).action is A.VERIFY


def test_the_epoch_and_digest_do_not_change_a_decision(engine):
    plain = PolicyObservation(**BASE, flow_status="evaluated")
    bound = dataclasses.replace(plain, flow_epoch=7, flow_digest="ab" * 32)
    assert engine.decide(plain).action is engine.decide(bound).action is A.ACCEPT


def test_the_engine_is_v6(engine):
    assert engine.decide(PolicyObservation(**BASE)).policy_version == "RemoraDecisionEngine-v6"


def test_an_approval_does_not_cover_a_confidentiality_violation():
    """F4 is grant-only (SDD v1.3 §3.6 c): re-deciding the same verdict voids
    even an approval that recorded the reason; F6 stays approvable."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from remora.governance.review_queue import Approval, _approval_survives

    now = datetime.now(UTC)

    def approval(reasons):
        return Approval(item_id="i", approved_action=A.ESCALATE, approver="r",
                        issued_at=now, expires_at=now + timedelta(minutes=5),
                        tool_call_hash="h", observation_hash="o",
                        approved_reasons=tuple(sorted(r.value for r in reasons)))

    f4 = SimpleNamespace(action=A.ESCALATE, reasons=(R.FLOW_CONFIDENTIALITY_VIOLATION,))
    assert not _approval_survives(f4, approval([R.FLOW_CONFIDENTIALITY_VIOLATION]))
    f6 = SimpleNamespace(action=A.ESCALATE, reasons=(R.FLOW_INTEGRITY_VIOLATION_ESCALATE,))
    assert _approval_survives(f6, approval([R.FLOW_INTEGRITY_VIOLATION_ESCALATE]))
