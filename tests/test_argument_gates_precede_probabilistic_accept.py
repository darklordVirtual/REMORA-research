# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Argument gates must take precedence over every probabilistic ACCEPT path."""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason


def _obs(**kw) -> PolicyObservation:
    d = dict(
        question="read it", trust_score=0.9, phase="ordered",
        action_type="read", schema_valid=True,
    )
    d.update(kw)
    return PolicyObservation(**d)


ENGINES = {
    "conformal": lambda: RemoraDecisionEngine(conformal_trust_threshold=0.5),
    "mondrian": lambda: RemoraDecisionEngine(conformal_phase_thresholds={"ordered": 0.5}),
    "ordered": RemoraDecisionEngine,
}


@pytest.mark.parametrize("name", sorted(ENGINES))
def test_missing_args_with_resolver_verifies(name):
    rep = ENGINES[name]().decide(_obs(
        missing_required_arguments=("x",), argument_resolver_tools=("lookup",)))
    assert rep.action is DecisionAction.VERIFY
    assert DecisionReason.ARGUMENT_RESOLUTION_REQUIRED in rep.reasons


@pytest.mark.parametrize("name", sorted(ENGINES))
def test_missing_args_without_resolver_not_accept(name):
    rep = ENGINES[name]().decide(_obs(missing_required_arguments=("x",)))
    assert rep.action is not DecisionAction.ACCEPT


@pytest.mark.parametrize("name", sorted(ENGINES))
def test_ungrounded_values_verify(name):
    rep = ENGINES[name]().decide(_obs(argument_values_grounded=False))
    assert rep.action is DecisionAction.VERIFY
    assert DecisionReason.UNGROUNDED_ARGUMENT_VALUES_VERIFY in rep.reasons


@pytest.mark.parametrize("name", sorted(ENGINES))
def test_unvalidated_args_not_accept(name):
    rep = ENGINES[name]().decide(_obs(
        unvalidated_required_arguments=("id",), argument_resolver_tools=("lookup",)))
    assert rep.action is DecisionAction.VERIFY
