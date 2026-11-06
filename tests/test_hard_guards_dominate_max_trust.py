# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every hard guard holds against a maximally trusted observation.

SDD-AS-v1 AS-014 (hard guards dominate the signal) and the non-finite half
of AS-013. Each case starts from one observation that ACCEPTs on the
probabilistic path (ordered phase, trust 1.0, evidence "answer" at
confidence 1.0, low risk, read-only, schema valid) and changes exactly one
security signal. The trust and evidence inputs stay at their maximum, so a
case passes only if the guard, not a weaker score, removes the ACCEPT.

Scope: this pins the decision. That a non-ACCEPT decision yields no grant,
and so no executor call, is covered by the token and dispatch tests.
"""
from __future__ import annotations

import math

import pytest

from remora.policy.decision_engine import (
    _FINITE_GATE_FIELDS,
    RemoraDecisionEngine,
    hard_guard_floor,
)
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason

MAX_TRUST = dict(
    question="Get reservation details for EHGLP3",
    action_type="read",
    proposed_tool_name="get_reservation_details",
    phase="ordered",
    trust_score=1.0,
    evidence_action="answer",
    evidence_confidence=1.0,
    schema_valid=True,
    risk_tier="low",
)

ENGINES = [
    pytest.param(RemoraDecisionEngine(), id="default"),
    pytest.param(RemoraDecisionEngine(low_consequence_accept=True,
                                      grounded_read_accept=True), id="opt-in-accept"),
]

#: One entry per guard in ``hard_guard_floor``, in its order.
GUARDS = [
    pytest.param({"adversarial_detected": True},
                 DecisionReason.ADMISSION_FIREWALL_BLOCKED, id="adversarial"),
    pytest.param({"schema_valid": False},
                 DecisionReason.MALFORMED_CALL_BLOCKED, id="schema"),
    pytest.param({"tool_forbidden": True},
                 DecisionReason.FORBIDDEN_TOOL_BLOCKED, id="forbidden-tool"),
    pytest.param({"argument_scope_valid": False},
                 DecisionReason.CROSS_TENANT_ARGUMENT_BLOCKED, id="scope"),
    pytest.param({"intent_provenance_required": True, "intent_provenance_resolved": False},
                 DecisionReason.INTENT_PROVENANCE_REQUIRED, id="provenance"),
    pytest.param({"intent_scope_status": "out_of_scope"},
                 DecisionReason.INTENT_SCOPE_MISMATCH, id="intent-scope"),
    pytest.param({"intent_scope_status": "unbound"},
                 DecisionReason.INTENT_AUTHORITY_UNBOUND, id="intent-unbound"),
    pytest.param({"coercion_detected": True},
                 DecisionReason.COERCION_BLOCKED, id="coercion"),
    pytest.param({"blackmail_pattern_detected": True},
                 DecisionReason.BLACKMAIL_BLOCKED, id="blackmail"),
    pytest.param({"counterfactual_passed": False},
                 DecisionReason.COUNTERFACTUAL_FAILED, id="counterfactual"),
    pytest.param({"evidence_contradictions": 1},
                 DecisionReason.EVIDENCE_CONTRADICTED, id="contradiction"),
    pytest.param({"argument_tainted": True, "untrusted_controlled_arguments": ("recipient",)},
                 DecisionReason.UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT, id="taint-sensitive"),
    pytest.param({"argument_tainted": True},
                 DecisionReason.TAINTED_ARGUMENT_VERIFY, id="taint"),
]


def _obs(**overrides) -> PolicyObservation:
    return PolicyObservation(**{**MAX_TRUST, **overrides})


@pytest.mark.parametrize("engine", ENGINES)
def test_the_baseline_accepts(engine):
    # Without this the cases below could pass because nothing ever accepts.
    assert engine.decide(_obs()).action is DecisionAction.ACCEPT


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(("override", "reason"), GUARDS)
def test_a_hard_guard_removes_the_accept_at_maximum_trust(engine, override, reason):
    obs = _obs(**override)
    floor = hard_guard_floor(obs)
    assert floor is not None and floor[1] is reason
    report = engine.decide(obs)
    assert report.action is not DecisionAction.ACCEPT
    assert report.action is floor[0]
    assert reason in report.reasons


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", _FINITE_GATE_FIELDS)
def test_a_non_finite_gate_input_never_accepts(engine, field, value):
    # Every comparison with NaN is False, so a NaN that slipped past the
    # gates would leave the maximum trust above in charge. AS-013 asks that
    # it is refused, not interpreted.
    report = engine.decide(_obs(**{field: value}))
    assert report.action is not DecisionAction.ACCEPT
    if math.isnan(value) or (value < 0 and field.endswith("_risk")):
        # NaN, and -inf on a risk field, pass every threshold above, so only
        # the non-finite floor can stop them. +inf on a risk field is already
        # over a risk threshold, which is the stricter reason to stop.
        assert DecisionReason.NON_FINITE_INPUT_VERIFY in report.reasons
