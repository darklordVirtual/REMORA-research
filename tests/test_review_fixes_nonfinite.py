# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review findings: non-finite numeric inputs must never reach ACCEPT."""
from __future__ import annotations

import math

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

_FIELDS = [
    "session_cumulative_risk",
    "model_misspecification_risk",
    "policy_generalization_risk",
    "environment_confidence",
    "classification_confidence",
]


def _obs(**kw: object) -> PolicyObservation:
    base: dict[str, object] = dict(
        question="q", phase="ordered", trust_score=0.9, final_H=0.3, final_D=0.08,
        risk_tier="low", action_type="read", target_environment="staging",
    )
    base.update(kw)
    return PolicyObservation(**base)  # type: ignore[arg-type]


def test_finite_baseline_accepts() -> None:
    assert RemoraDecisionEngine().decide(_obs()).action == DecisionAction.ACCEPT


@pytest.mark.parametrize("field", _FIELDS)
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_gate_input_is_not_accept(field: str, bad: float) -> None:
    report = RemoraDecisionEngine().decide(_obs(**{field: bad}))
    assert report.action != DecisionAction.ACCEPT
    assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE, DecisionAction.ABSTAIN)
