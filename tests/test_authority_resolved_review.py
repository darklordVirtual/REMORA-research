# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The fall-through for an authorised call goes to a person, not to ABSTAIN.

Found by deploying: an accurately-declared medium-risk write with valid
schema fell through every gate to ABSTAIN — no route to approval at all —
while inflating the declaration to high produced a VERIFY. The incentive
pointed toward mis-declaring risk.

The conversion is deliberately narrow: only the fall-through, only when the
deployment's own intent source resolved the authority (server-side, never
client-asserted), and only to VERIFY. A person still decides; nothing runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.policy.report import DecisionAction, DecisionReason  # noqa: E402
from tests.test_gateway_grounded_read import Obs  # noqa: E402


@pytest.fixture()
def engine():
    return RemoraDecisionEngine(grounded_read_accept=True,
                                execution_profile=True,
                                semantic_authority_floor=True)


def obs(**kw):
    o = Obs(**kw)
    o.valid_oracle_count = 0
    o.oracle_failures = 0
    return o


def test_an_authorised_fall_through_goes_to_a_person(engine):
    d = engine.decide(obs(risk_tier="medium", action_type="write",
                          mutation=True, target_environment="staging",
                          schema_valid=True))
    assert d.action is DecisionAction.VERIFY
    assert DecisionReason.AUTHORITY_RESOLVED_REVIEW in d.reasons


def test_no_resolved_authority_still_abstains(engine):
    """The conversion requires the deployment to have recognised the work
    order. Without that there is nothing for a reviewer to decide on."""
    for value in (False, None):
        d = engine.decide(obs(risk_tier="medium", action_type="write",
                              mutation=True, target_environment="staging",
                              schema_valid=True,
                              intent_authority_present=value))
        assert d.action is DecisionAction.ABSTAIN, f"authority={value}"


def test_it_never_produces_an_accept(engine):
    """Only the fall-through moves, and only to VERIFY."""
    d = engine.decide(obs(risk_tier="medium", action_type="write",
                          mutation=True, target_environment="staging",
                          schema_valid=True))
    assert d.action is not DecisionAction.ACCEPT


def test_a_grounded_staging_read_still_accepts(engine):
    """The new path must not preempt the accept it sits behind."""
    d = engine.decide(obs(risk_tier="low", target_environment="staging"))
    assert d.action is DecisionAction.ACCEPT
    assert DecisionReason.GROUNDED_READ_ACCEPT in d.reasons


def test_a_production_read_now_has_a_human_route(engine):
    """The recorded gap: low-risk production reads abstained with no route
    to approval. With a resolved authority they now reach a person."""
    d = engine.decide(obs(risk_tier="low", target_environment="prod"))
    assert d.action is DecisionAction.VERIFY
    assert DecisionReason.AUTHORITY_RESOLVED_REVIEW in d.reasons


def test_hard_blocks_are_untouched(engine):
    """A safety concern above the fall-through still wins outright."""
    d = engine.decide(obs(risk_tier="medium", action_type="write",
                          mutation=True, target_environment="staging",
                          schema_valid=True, argument_tainted=True))
    assert d.action is not DecisionAction.VERIFY or \
        DecisionReason.AUTHORITY_RESOLVED_REVIEW not in d.reasons


def test_schema_invalid_still_blocks(engine):
    d = engine.decide(obs(risk_tier="medium", action_type="write",
                          mutation=True, target_environment="staging",
                          schema_valid=False))
    assert d.action is not DecisionAction.ACCEPT
    assert DecisionReason.AUTHORITY_RESOLVED_REVIEW not in d.reasons
