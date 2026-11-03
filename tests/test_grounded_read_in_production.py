# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Grounded reads in production: off by default, and when on it lifts one clause.

Owner decision 2026-11-03 (docs/architecture/ADR-grounded-reads-in-production.md):
a deployment may let the grounded-read path fire for a production target. The
engine flag ``grounded_read_in_production`` is part of the policy identity. It
must change nothing unless ``grounded_read_accept`` is also on, it must lift
only the environment clause, and the low-consequence path must keep excluding
production whatever the flag says.
"""
from __future__ import annotations

import pytest

from remora.policy import PolicyObservation
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason

PROD_ALIASES = ["prod", "production", "live", "PROD", " Live "]


def _grounded(**overrides) -> PolicyObservation:
    base = dict(
        question="read_sensor(PT-101)", risk_tier="low", action_type="read",
        target_environment="prod", domain="ot_plant", intent_authority_present=True,
        tool_matches_goal=True, expected_effect_matches=True,
        argument_values_supported=True, argument_values_grounded=True,
        proposed_tool_name="read_sensor",
    )
    base.update(overrides)
    return PolicyObservation(**base)


def _engine(**flags) -> RemoraDecisionEngine:
    return RemoraDecisionEngine(grounded_read_accept=True, **flags)


@pytest.mark.parametrize("env", PROD_ALIASES)
def test_off_by_default_production_still_never_accepts(env: str) -> None:
    report = _engine().decide(_grounded(target_environment=env))
    assert report.action is not DecisionAction.ACCEPT, env


@pytest.mark.parametrize("env", PROD_ALIASES)
def test_with_the_flag_a_fully_grounded_production_read_accepts(env: str) -> None:
    report = _engine(grounded_read_in_production=True).decide(_grounded(target_environment=env))
    assert report.action is DecisionAction.ACCEPT, (env, report.reasons)
    assert DecisionReason.GROUNDED_READ_ACCEPT in report.reasons


def test_the_flag_alone_changes_nothing_without_grounded_read_accept() -> None:
    engine = RemoraDecisionEngine(grounded_read_in_production=True)
    report = engine.decide(_grounded())
    assert report.action is not DecisionAction.ACCEPT
    assert DecisionReason.GROUNDED_READ_ACCEPT not in report.reasons


@pytest.mark.parametrize("broken", [
    dict(tool_matches_goal=None), dict(expected_effect_matches=False),
    dict(argument_values_supported=None), dict(argument_values_grounded=False),
    dict(intent_authority_present=None), dict(intent_authority_present=False),
    dict(risk_tier="medium"), dict(risk_tier="critical"), dict(risk_tier=None),
    dict(action_type="write"), dict(action_type="execution"), dict(action_type=None),
    dict(argument_tainted=True), dict(adversarial_detected=True), dict(schema_valid=False),
    dict(missing_required_arguments=("sensor_id",)),
])
def test_every_other_clause_still_refuses_in_production(broken: dict) -> None:
    """The flag lifts the environment clause and nothing else."""
    report = _engine(grounded_read_in_production=True).decide(_grounded(**broken))
    assert report.action is not DecisionAction.ACCEPT, broken


@pytest.mark.parametrize("env", PROD_ALIASES)
def test_low_consequence_accept_still_excludes_production(env: str) -> None:
    """The weaker path has no production opt-in; the flag must not leak into it."""
    engine = RemoraDecisionEngine(low_consequence_accept=True, grounded_read_in_production=True)
    # Not grounded (no grounding signals), so only the low-consequence path could fire.
    obs = PolicyObservation(question="read_sensor(PT-101)", risk_tier="low", action_type="read",
                            target_environment=env, domain="ot_plant")
    report = engine.decide(obs)
    assert report.action is not DecisionAction.ACCEPT, env
    assert DecisionReason.LOW_CONSEQUENCE_ACCEPT not in report.reasons


def test_staging_behaviour_is_unchanged_by_the_flag() -> None:
    for flag in (False, True):
        report = _engine(grounded_read_in_production=flag).decide(_grounded(target_environment="staging"))
        assert report.action is DecisionAction.ACCEPT


def test_the_flag_is_part_of_the_policy_identity() -> None:
    from servers import api

    assert "grounded_read_in_production" in api.ENGINE_IDENTITY_FLAGS
