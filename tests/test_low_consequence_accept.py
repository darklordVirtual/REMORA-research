# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the low-consequence ACCEPT path (2026-07-31).

Measured on the routing benchmark: ACCEPT recall was 0% in every arm except one
that declared every action low-risk, which then accepted 88.5% of known-wrong
calls. The cause is that every existing ACCEPT path requires an oracle-derived
consensus signal (trust, temperature, conformal or evidence). Without one, a
clean read-only call falls through to ``default_safe_abstain``. Action
semantics could only ever *block*; they could never permit.

This path lets bounded, reversible action semantics reach ACCEPT without an
oracle run. What it asserts is **consequence, not correctness**: the engine
cannot tell a correct read from an incorrect one from observable data, so the
claim is that executing this call is cheap to get wrong — not that it is right.

It is opt-in (``low_consequence_accept=True``) and off by default. A new ACCEPT
path that defaults on is how the 2026-07-30 regression happened; see
tests/test_escalate_semantics_guard.py.
"""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason

OFF = RemoraDecisionEngine()
ON = RemoraDecisionEngine(low_consequence_accept=True)


def _obs(**kwargs) -> PolicyObservation:
    defaults: dict = dict(question="Get reservation details for EHGLP3")
    defaults.update(kwargs)
    return PolicyObservation(**defaults)


# ---------------------------------------------------------------------------
# Default is unchanged
# ---------------------------------------------------------------------------

def test_path_is_off_by_default() -> None:
    """A clean read-only call still abstains on a default engine."""
    report = OFF.decide(_obs(action_type="read"))
    assert report.action == DecisionAction.ABSTAIN
    assert DecisionReason.LOW_CONSEQUENCE_ACCEPT not in report.reasons


def test_enabled_engine_accepts_a_clean_read() -> None:
    report = ON.decide(_obs(action_type="read"))
    assert report.action == DecisionAction.ACCEPT
    assert DecisionReason.LOW_CONSEQUENCE_ACCEPT in report.reasons


# ---------------------------------------------------------------------------
# Only read-only semantics qualify
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action_type",
    ["write", "destructive_write", "execution", "delete", "send", "unlock_access"],
)
def test_mutating_action_types_never_qualify(action_type: str) -> None:
    """The path asserts bounded consequence; a mutation is not bounded."""
    report = ON.decide(_obs(action_type=action_type))
    assert report.action != DecisionAction.ACCEPT
    assert DecisionReason.LOW_CONSEQUENCE_ACCEPT not in report.reasons


def test_unknown_action_type_does_not_qualify() -> None:
    """action_type=None is unknown, not read-only. Silence must not permit."""
    report = ON.decide(_obs(action_type=None))
    assert report.action != DecisionAction.ACCEPT


# ---------------------------------------------------------------------------
# Every negative safety signal disqualifies
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"argument_tainted": True}, id="tainted_argument"),
        pytest.param({"tool_forbidden": True}, id="forbidden_tool"),
        pytest.param({"schema_valid": False}, id="invalid_schema"),
        pytest.param({"adversarial_detected": True}, id="adversarial"),
        pytest.param({"coercion_detected": True}, id="coercion"),
        pytest.param({"blackmail_pattern_detected": True}, id="blackmail"),
        pytest.param({"counterfactual_passed": False}, id="counterfactual_failed"),
        pytest.param({"evidence_contradictions": 1}, id="evidence_contradicted"),
        pytest.param({"target_environment": "prod"}, id="production"),
        pytest.param({"distribution_shift_detected": True}, id="distribution_shift"),
    ],
)
def test_negative_safety_signal_blocks_the_path(kwargs: dict) -> None:
    report = ON.decide(_obs(action_type="read", **kwargs))
    assert report.action != DecisionAction.ACCEPT, (
        f"{kwargs} reached ACCEPT through the low-consequence path"
    )
    assert DecisionReason.LOW_CONSEQUENCE_ACCEPT not in report.reasons


def test_untainted_read_in_staging_still_qualifies() -> None:
    """The environment check must exclude production, not every named environment."""
    report = ON.decide(_obs(action_type="read", target_environment="staging"))
    assert report.action == DecisionAction.ACCEPT


# ---------------------------------------------------------------------------
# The path must not be able to preempt a block
# ---------------------------------------------------------------------------

def test_path_runs_after_every_blocking_gate() -> None:
    """Enabling the flag must not change any decision that was not an abstain.

    The path is placed immediately before the default abstain precisely so it
    can only ever convert a fall-through, never override a gate. This sweeps a
    grid of observations and asserts that property directly.
    """
    changed_from_non_abstain = []
    for action_type in ["read", "write", "execution", "delete", None]:
        for risk in ["low", "medium", "high", "critical", None]:
            for phase in ["ordered", "critical", "disordered", None]:
                for tainted in [True, False]:
                    obs = _obs(
                        action_type=action_type,
                        risk_tier=risk,
                        phase=phase,
                        argument_tainted=tainted,
                    )
                    before = OFF.decide(obs).action
                    after = ON.decide(obs).action
                    if before != after and before != DecisionAction.ABSTAIN:
                        changed_from_non_abstain.append((obs, before, after))
    assert changed_from_non_abstain == [], (
        f"{len(changed_from_non_abstain)} decision(s) changed from a non-abstain "
        f"outcome; the path is preempting a gate. First: {changed_from_non_abstain[:1]}"
    )


def test_escalate_semantics_are_unaffected_by_the_flag() -> None:
    """The flag must not touch any of the paths pinned by the escalate guards."""
    cases = [
        dict(action_type="disable_security", domain="security",
             target_environment="staging", risk_tier="low"),
        dict(action_type="unlock_access", target_environment="prod", risk_tier="low"),
        dict(action_type="bulk_delete", target_environment="staging", risk_tier="low"),
        dict(phase="critical", risk_tier="critical", trust_score=0.99),
        dict(rollback_available=False, risk_tier="high", phase="ordered",
             trust_score=0.9),
    ]
    for kwargs in cases:
        obs = _obs(**kwargs)
        assert OFF.decide(obs).action == ON.decide(obs).action == DecisionAction.ESCALATE


def test_accepted_report_records_bounded_consequence_not_correctness() -> None:
    """The explanation must not claim the call is correct — only cheap to get wrong."""
    report = ON.decide(_obs(action_type="read"))
    assert report.human_review_required is False
    assert "consequence" in report.coverage_policy.lower()
