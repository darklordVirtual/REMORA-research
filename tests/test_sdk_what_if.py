# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The policy what-if, reachable through ``remora.sdk`` (remora.sdk.whatif).

A host that may import only ``remora.sdk`` (an embedding simulator, for one)
needs the decision-boundary analysis of ``remora.policy.whatif`` on the same
terms as :func:`remora.sdk.evaluate_policy`: pure, deterministic, read-only
over the engine, and analysable under the engine flags the execution surface
runs with. The analysis grants nothing; these tests also pin that it answers
exactly what the internal function answers for the same engine.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

import remora.sdk as sdk
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction
from remora.policy.whatif import what_if as internal_what_if


def _bounded_write(**overrides: object) -> PolicyObservation:
    """A reversible low-tier write inside a signed ToolSpec and a metered limit."""
    obs = PolicyObservation.from_tool_call(
        name="chw.set_supply_setpoint.v1",
        arguments={"plant": "CHW", "value": 18.5, "target": "run-1|CHW.SP"},
        risk_tier="low",
        action_type="write",
        target_environment="simulation",
        trust_score=None,
        phase=None,
        schema_valid=True,
        rollback_available=True,
        session_id="dcsim",
    )
    obs = dataclasses.replace(obs, toolspec_enforced=True, cumulative_limit_metered=True)
    return dataclasses.replace(obs, **overrides) if overrides else obs


def test_the_surface_is_exported() -> None:
    for name in ("EngineOptions", "WhatIfReport", "what_if"):
        assert name in sdk.__all__
        assert hasattr(sdk, name)


def test_engine_options_default_to_the_library_engine() -> None:
    options = sdk.EngineOptions()
    assert not any(dataclasses.asdict(options).values())


def test_execution_surface_options_mirror_the_enforcing_engine() -> None:
    options = sdk.EngineOptions.execution_surface()
    assert options.execution_profile is True
    assert options.strict_monotone is True
    assert options.bounded_write_accept is False
    on = sdk.EngineOptions.execution_surface(
        bounded_write_accept=True, bounded_write_intent_optional=True)
    assert on.bounded_write_accept and on.bounded_write_intent_optional
    assert on.execution_profile


def test_report_matches_the_internal_analysis_for_the_same_engine() -> None:
    obs = _bounded_write()
    options = sdk.EngineOptions.execution_surface(
        bounded_write_accept=True, bounded_write_intent_optional=True)
    engine = RemoraDecisionEngine(**dataclasses.asdict(options))
    expected = internal_what_if(obs, engine, target=DecisionAction.ACCEPT,
                                max_depth=3, max_evaluations=5_000)
    got = sdk.what_if(obs, target="accept", max_depth=3, max_evaluations=5_000,
                      engine_options=options)
    assert isinstance(got, sdk.WhatIfReport)
    assert got.to_dict() == expected.to_dict()


def test_bounded_write_is_accepted_only_under_the_opt_in_flags() -> None:
    obs = _bounded_write()
    on = sdk.what_if(obs, engine_options=sdk.EngineOptions.execution_surface(
        bounded_write_accept=True, bounded_write_intent_optional=True))
    assert on.current_action is DecisionAction.ACCEPT
    assert on.already_at_target
    off = sdk.what_if(obs, max_depth=2, max_evaluations=2_000,
                      engine_options=sdk.EngineOptions.execution_surface())
    assert off.current_action is not DecisionAction.ACCEPT


def test_a_write_outside_the_schema_names_the_hard_guard_and_no_model_path() -> None:
    obs = _bounded_write(schema_valid=False)
    report = sdk.what_if(obs, max_depth=2, max_evaluations=5_000,
                         engine_options=sdk.EngineOptions.execution_surface(
                             bounded_write_accept=True, bounded_write_intent_optional=True))
    assert report.current_action is not DecisionAction.ACCEPT
    assert report.hard_guard is not None
    assert report.model_signals_alone is None


def test_the_report_is_json_and_deterministic() -> None:
    obs = _bounded_write(rollback_available=False)
    options = sdk.EngineOptions.execution_surface(
        bounded_write_accept=True, bounded_write_intent_optional=True)
    first = sdk.what_if(obs, max_depth=2, max_evaluations=3_000, engine_options=options)
    second = sdk.what_if(obs, max_depth=2, max_evaluations=3_000, engine_options=options)
    text = json.dumps(first.to_dict(), sort_keys=True)
    assert text == json.dumps(second.to_dict(), sort_keys=True)


def test_the_analysis_grants_nothing_and_leaves_the_observation_alone() -> None:
    obs = _bounded_write(rollback_available=False)
    before = dataclasses.asdict(obs)
    report = sdk.what_if(obs, max_depth=2, max_evaluations=3_000)
    assert dataclasses.asdict(obs) == before
    text = json.dumps(report.to_dict())
    for word in ("execution_token", "execution_grant", "lease"):
        assert word not in text


def test_target_accepts_the_enum_and_its_value() -> None:
    obs = _bounded_write(rollback_available=False)
    a = sdk.what_if(obs, target=DecisionAction.VERIFY, max_depth=1, max_evaluations=500)
    b = sdk.what_if(obs, target="verify", max_depth=1, max_evaluations=500)
    assert a.to_dict() == b.to_dict()
    assert a.target is DecisionAction.VERIFY


def test_bad_bounds_and_targets_are_refused() -> None:
    obs = _bounded_write()
    with pytest.raises(ValueError):
        sdk.what_if(obs, max_depth=0)
    with pytest.raises(ValueError):
        sdk.what_if(obs, max_evaluations=0)
    with pytest.raises(ValueError):
        sdk.what_if(obs, target="approve")
