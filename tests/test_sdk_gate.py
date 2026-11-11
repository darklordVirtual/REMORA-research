# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The in-process policy decision facade (remora.sdk.gate).

A host that embeds REMORA without a server — a simulator, a shadow comparison —
needs a stable, deterministic way to get the gate's verdict. ``evaluate_policy``
is the policy decision point as a pure function of the observation: the engine
reads no clock and no random source, so the same observation always yields the
same decision. It is NOT an authorization grant; a real write still goes
through the governed execution path, where the single-use token, cumulative
limits, custody split and audit chain apply.
"""
from __future__ import annotations

from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction
from remora.sdk import (
    GateDecision,
    GateVerdict,
    evaluate_policy,
    verdict_for_action,
)
from remora.policy.decision_engine import RemoraDecisionEngine


def _obs(question: str, **kw) -> PolicyObservation:
    return PolicyObservation.minimal(question, **kw)


def test_verdict_for_action_maps_every_decision_action() -> None:
    assert verdict_for_action(DecisionAction.ACCEPT) is GateVerdict.ALLOW
    assert verdict_for_action(DecisionAction.VERIFY) is GateVerdict.VERIFY
    assert verdict_for_action(DecisionAction.ESCALATE) is GateVerdict.VERIFY
    assert verdict_for_action(DecisionAction.ABSTAIN) is GateVerdict.ABSTAIN


def test_evaluate_policy_agrees_with_the_engine() -> None:
    obs = _obs("Raise chilled water setpoint by 0.5 C", risk_tier="medium", domain="ot")
    report = RemoraDecisionEngine().decide(obs)
    decision = evaluate_policy(obs)
    assert decision.action is report.action
    assert decision.verdict is verdict_for_action(report.action)
    assert decision.reasons == tuple(r.value for r in report.reasons)
    assert decision.escalated is (report.action is DecisionAction.ESCALATE)


def test_evaluate_policy_is_deterministic_across_instances() -> None:
    obs = _obs("Take a chiller out of service for maintenance",
               risk_tier="critical", domain="ot")
    # No clock, no randomness: two independent engines give the same decision.
    a = evaluate_policy(obs, engine=RemoraDecisionEngine())
    b = evaluate_policy(obs, engine=RemoraDecisionEngine())
    assert a == b


def test_a_critical_unproven_action_is_never_allowed() -> None:
    # A conservative minimal observation (no grounding) for a critical action
    # must not ALLOW: it is held for a human or abstained, never auto-approved.
    decision = evaluate_policy(_obs("Open an MV feeder breaker",
                                    risk_tier="critical", domain="ot"))
    assert decision.verdict is not GateVerdict.ALLOW


def test_deny_is_a_host_side_verdict_for_a_governed_refusal() -> None:
    # The pure PDP never fabricates DENY; a host maps a governed refusal
    # (a typed error / 4xx from the execution path) onto this verdict.
    denied = GateDecision.deny(["limit_exceeded"], explanation="past the hard cap")
    assert denied.verdict is GateVerdict.DENY
    assert denied.reasons == ("limit_exceeded",)


def test_gate_symbols_are_on_the_public_surface() -> None:
    import remora.sdk as sdk

    for name in ("GateDecision", "GateVerdict", "evaluate_policy",
                 "verdict_for_action", "PolicyObservation"):
        assert name in sdk.__all__, name
