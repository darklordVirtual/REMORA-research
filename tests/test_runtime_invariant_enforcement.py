# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Policy invariants are enforced at runtime, not only asserted in tests.

Before this, ``check_all_invariants`` had no caller outside the test suite:
the same safety properties were implemented once as invariants and again
inside ``decide``, with nothing to notice the two drifting apart. The engine
now evaluates them at its single build choke point and fails closed.
"""
from __future__ import annotations

import pytest

import remora.policy.decision_engine as engine_mod
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.invariants import (
    CORE_INVARIANTS,
    InvariantResult,
    PolicyInvariant,
    check_all_invariants,
)
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason


class _AlwaysViolated(PolicyInvariant):
    """A stand-in for a real invariant that a future engine change breaks."""

    name = "always_violated_probe"

    def check(self, obs, report) -> InvariantResult:  # type: ignore[override]
        return InvariantResult(
            invariant_name=self.name,
            passed=False,
            violated=True,
            evidence="probe invariant, violated by construction",
        )


def _obs(**kw) -> PolicyObservation:
    return PolicyObservation(question="read the deployment status page", **kw)


def test_enforcement_is_on_by_default() -> None:
    assert RemoraDecisionEngine().verify_invariants is True


def test_ordinary_decisions_satisfy_the_core_invariants() -> None:
    """The enforcement path must not disturb normal operation."""
    engine = RemoraDecisionEngine()
    for obs in (
        _obs(),
        _obs(risk_tier="critical", action_type="delete"),
        _obs(risk_tier="low", action_type="read", target_environment="dev"),
    ):
        report = engine.decide(obs)
        violated = [r for r in check_all_invariants(obs, report) if r.violated]
        assert violated == [], violated


def test_a_violated_invariant_escalates_instead_of_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decision that breaks an invariant is withdrawn, not delivered."""
    probe = _AlwaysViolated()
    monkeypatch.setattr(
        engine_mod, "check_all_invariants",
        lambda obs, report: [probe.check(obs, report)],
    )
    report = RemoraDecisionEngine().decide(_obs())
    assert report.action is DecisionAction.ESCALATE
    assert DecisionReason.INVARIANT_VIOLATION_ESCALATE in report.reasons
    assert "always_violated_probe" in report.explanation
    assert report.human_review_required is True


def test_escalation_does_not_recurse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building the escalation must not re-enter enforcement forever."""
    calls: list[int] = []

    def _always_violated(obs, report):
        calls.append(1)
        return [
            InvariantResult(
                invariant_name="probe", passed=False, violated=True, evidence=""
            )
        ]

    monkeypatch.setattr(engine_mod, "check_all_invariants", _always_violated)
    report = RemoraDecisionEngine().decide(_obs())
    assert report.action is DecisionAction.ESCALATE
    # Exactly one evaluation: the original decision. The replacement is built
    # with enforcement suppressed.
    assert len(calls) == 1


def test_enforcement_can_be_disabled_for_measurement() -> None:
    engine = RemoraDecisionEngine(verify_invariants=False)
    original = engine_mod.check_all_invariants
    seen: list[int] = []
    engine_mod.check_all_invariants = lambda obs, report: (seen.append(1), [])[1]
    try:
        engine.decide(_obs())
    finally:
        engine_mod.check_all_invariants = original
    assert seen == []


def test_core_invariants_are_non_empty() -> None:
    """A silently empty invariant set would make enforcement a no-op."""
    assert len(CORE_INVARIANTS) >= 5
