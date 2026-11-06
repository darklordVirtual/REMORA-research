# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Property tests over the grounded-read path (test plan item 5, 2026-11-04).

Random observations, many seeds: the path may ACCEPT only when every clause
holds, and with the production opt-in off it may never ACCEPT a production
target. Each property is stated as the engine's rule, not as an example.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from remora.policy import PolicyObservation
from remora.policy.decision_engine import (
    RemoraDecisionEngine,
    _MUTATING_TYPES,
    _NON_ACTUATING_TYPES,
    _PROD_ENVS,
    _READ_ONLY_ACTION_TYPES,
    _READ_ONLY_TYPES,
)
from remora.policy.report import DecisionAction, DecisionReason

# The grounded-read path's read-only set, restricted to what the engine's
# unknown-action-type guard recognises. Found on 2026-11-04 by this file's first
# property under mutmut's clean run: "get", "search" and "lookup" are in the
# read-only set but the guard floors them to VERIFY, so they can never ground.
GROUNDABLE = _READ_ONLY_ACTION_TYPES & (_READ_ONLY_TYPES | _MUTATING_TYPES | _NON_ACTUATING_TYPES)


def test_the_groundable_vocabulary_is_pinned():
    assert GROUNDABLE == {"read", "list", "query", "read_only"}
    assert _READ_ONLY_ACTION_TYPES - GROUNDABLE == {"get", "search", "lookup"}


tri = st.sampled_from([True, False, None])
envs = st.sampled_from(["prod", "production", "live", "staging", "dev", "pilot", "PROD", " Live ", "", None])
tiers = st.sampled_from(["low", "medium", "high", "critical", "LOW", None, "unknown"])
actions = st.sampled_from(sorted(_READ_ONLY_ACTION_TYPES) + ["write", "execution", "delete", None, "unknown"])


@st.composite
def observations(draw):
    return PolicyObservation(
        question="read_sensor(PT-101)",
        risk_tier=draw(tiers), action_type=draw(actions), target_environment=draw(envs),
        domain="ot_plant",
        intent_authority_present=draw(tri),
        tool_matches_goal=draw(tri), expected_effect_matches=draw(tri),
        argument_values_supported=draw(tri), argument_values_grounded=draw(tri),
        argument_tainted=draw(st.booleans()), adversarial_detected=draw(st.booleans()),
        schema_valid=draw(tri),
        proposed_tool_name="read_sensor",
    )


def _every_clause_holds(obs: PolicyObservation, allow_production: bool) -> bool:
    env = (obs.target_environment or "").strip().lower()
    return (
        (obs.action_type or "").strip().lower() in GROUNDABLE
        and (obs.risk_tier or "").strip().lower() == "low"
        and (allow_production or env not in _PROD_ENVS)
        and obs.intent_authority_present is True
        and obs.tool_matches_goal is True and obs.expected_effect_matches is True
        and obs.argument_values_supported is True and obs.argument_values_grounded is True
        and not obs.argument_tainted and not obs.adversarial_detected
        and obs.schema_valid is not False
    )


@settings(max_examples=600, deadline=None)
@given(observations(), st.booleans())
def test_grounded_accept_only_when_every_clause_holds(obs, allow_production):
    engine = RemoraDecisionEngine(grounded_read_accept=True, grounded_read_in_production=allow_production)
    report = engine.decide(obs)
    grounded = DecisionReason.GROUNDED_READ_ACCEPT in report.reasons
    if grounded:
        assert report.action is DecisionAction.ACCEPT
        assert _every_clause_holds(obs, allow_production), obs
    if _every_clause_holds(obs, allow_production):
        # Every clause of the path holds; the only things that may still stop it are
        # hard guards above it, which this observation does not trigger.
        assert report.action is DecisionAction.ACCEPT, (obs, report.reasons)


@settings(max_examples=400, deadline=None)
@given(observations())
def test_production_never_accepts_without_the_opt_in(obs):
    if (obs.target_environment or "").strip().lower() not in _PROD_ENVS:
        return
    report = RemoraDecisionEngine(grounded_read_accept=True).decide(obs)
    assert report.action is not DecisionAction.ACCEPT, obs


@settings(max_examples=400, deadline=None)
@given(observations())
def test_the_opt_in_never_accepts_a_write_or_a_higher_tier(obs):
    report = RemoraDecisionEngine(grounded_read_accept=True, grounded_read_in_production=True).decide(obs)
    if report.action is DecisionAction.ACCEPT:
        assert (obs.action_type or "").strip().lower() in _READ_ONLY_ACTION_TYPES
        assert (obs.risk_tier or "").strip().lower() == "low"
