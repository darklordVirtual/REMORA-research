# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The bounded-write ACCEPT path: opt-in, default off, and only a fall-through.

Issue #1233: on the execution surface no write could reach ACCEPT under any
truthful configuration, so a bounded optimization step the operator's own
contract allows without approval still needed a person. ``bounded_write_accept``
is a third deterministic ACCEPT path for exactly ``action_type == "write"``,
at or below a configured tier, reversible, schema-valid, outside production,
under an enforced signed ToolSpec and a cumulative-limit meter (both facts only
the server sets), with every negative check of the low-consequence path.

These tests pin the engine half: each condition missing on its own makes the
decision exactly what the engine without the flag decides, so the path can only
convert a fall-through. The execution API half is in
``tests/test_bounded_write_accept_api.py``.
"""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason

#: The execution surface's own configuration, as ``_engine_from_env`` builds it.
SURFACE = dict(execution_profile=True, strict_monotone=True)


def _engine(**flags) -> RemoraDecisionEngine:
    return RemoraDecisionEngine(**{**SURFACE, "bounded_write_accept": True, **flags})


def _off(**flags) -> RemoraDecisionEngine:
    return RemoraDecisionEngine(**{**SURFACE, **flags})


def _bounded(**overrides) -> PolicyObservation:
    base = dict(
        question="run_fan_minutes(AHU-1, 10)", action_type="write", risk_tier="low",
        domain="building_automation", target_environment="staging",
        rollback_available=True, schema_valid=True,
        toolspec_enforced=True, cumulative_limit_metered=True,
        intent_authority_present=True, proposed_tool_name="run_fan_minutes",
    )
    base.update(overrides)
    return PolicyObservation(**base)


def test_a_bounded_write_is_accepted_under_its_own_reason() -> None:
    report = _engine().decide(_bounded())
    assert report.action is DecisionAction.ACCEPT, report.reasons
    assert DecisionReason.BOUNDED_WRITE_ACCEPT in report.reasons
    assert report.reasons[-1] is DecisionReason.BOUNDED_WRITE_ACCEPT
    assert DecisionReason.BOUNDED_WRITE_ACCEPT.value == "bounded_write_accept"
    assert DecisionReason.LOW_CONSEQUENCE_ACCEPT not in report.reasons
    assert DecisionReason.GROUNDED_READ_ACCEPT not in report.reasons
    assert "bounded write" in report.coverage_policy


def test_the_path_is_off_by_default() -> None:
    engine = RemoraDecisionEngine()
    assert engine.bounded_write_accept is False
    assert engine.bounded_write_medium_tier is False
    assert engine.bounded_write_intent_optional is False
    assert _off().decide(_bounded()).action is not DecisionAction.ACCEPT


#: One case per condition. Each removes exactly one thing the path needs.
REFUSALS: dict[str, tuple[dict, dict]] = {
    # (engine flags, observation overrides)
    "flag_off": ({"bounded_write_accept": False}, {}),
    "destructive_write": ({}, {"action_type": "destructive_write"}),
    "security_change": ({}, {"action_type": "security_change"}),
    "financial_transaction": ({}, {"action_type": "financial_transaction"}),
    "deploy": ({}, {"action_type": "deploy"}),
    "production_write": ({}, {"action_type": "production_write"}),
    "delete": ({}, {"action_type": "delete"}),
    "execution": ({}, {"action_type": "execution"}),
    "unknown_action_type": ({}, {"action_type": None}),
    "tier_medium_above_default_ceiling": ({}, {"risk_tier": "medium"}),
    "tier_high_above_medium_ceiling": ({"bounded_write_medium_tier": True},
                                       {"risk_tier": "high"}),
    "tier_critical": ({"bounded_write_medium_tier": True}, {"risk_tier": "critical"}),
    "tier_unknown": ({}, {"risk_tier": None}),
    "rollback_unknown": ({}, {"rollback_available": None}),
    "no_rollback": ({}, {"rollback_available": False}),
    "schema_unknown": ({}, {"schema_valid": None}),
    "schema_invalid": ({}, {"schema_valid": False}),
    "production_target": ({}, {"target_environment": "prod"}),
    "production_alias": ({}, {"target_environment": "production"}),
    "live_target": ({}, {"target_environment": "live"}),
    "unknown_target": ({}, {"target_environment": None}),
    "toolspec_not_enforced": ({}, {"toolspec_enforced": False}),
    "toolspec_unknown": ({}, {"toolspec_enforced": None}),
    "no_meter": ({}, {"cumulative_limit_metered": False}),
    "meter_unknown": ({}, {"cumulative_limit_metered": None}),
    "intent_absent": ({}, {"intent_authority_present": None}),
    "intent_unresolved": ({}, {"intent_authority_present": False}),
    # Every negative check of the low-consequence path.
    "tainted": ({}, {"argument_tainted": True}),
    "forbidden": ({}, {"tool_forbidden": True}),
    "adversarial": ({}, {"adversarial_detected": True}),
    "coercion": ({}, {"coercion_detected": True}),
    "blackmail": ({}, {"blackmail_pattern_detected": True}),
    "distribution_shift": ({}, {"distribution_shift_detected": True}),
    "counterfactual_failed": ({}, {"counterfactual_passed": False}),
    "contradicted": ({}, {"evidence_contradictions": 1}),
    "unsatisfiable_arguments": ({}, {"arguments_satisfiable": False}),
    "unsupported_argument_values": ({}, {"argument_values_supported": False}),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_each_missing_condition_falls_through_to_the_existing_outcome(case: str) -> None:
    flags, overrides = REFUSALS[case]
    obs = _bounded(**overrides)
    on = _engine(**flags).decide(obs)
    off = _off(**{k: v for k, v in flags.items() if k != "bounded_write_accept"}).decide(obs)
    assert DecisionReason.BOUNDED_WRITE_ACCEPT not in on.reasons, case
    assert on.action is not DecisionAction.ACCEPT, case
    assert (on.action, on.reasons) == (off.action, off.reasons), case


def test_a_medium_ceiling_accepts_a_medium_write() -> None:
    report = _engine(bounded_write_medium_tier=True).decide(_bounded(risk_tier="medium"))
    assert report.action is DecisionAction.ACCEPT, report.reasons
    assert DecisionReason.BOUNDED_WRITE_ACCEPT in report.reasons


def test_the_medium_ceiling_alone_changes_nothing_without_the_path() -> None:
    obs = _bounded(risk_tier="medium")
    alone = _off(bounded_write_medium_tier=True).decide(obs)
    assert (alone.action, alone.reasons) == (_off().decide(obs).action,
                                             _off().decide(obs).reasons)


def test_intent_authority_is_required_unless_the_deployment_says_otherwise() -> None:
    obs = _bounded(intent_authority_present=None)
    assert _engine().decide(obs).action is not DecisionAction.ACCEPT
    relaxed = _engine(bounded_write_intent_optional=True).decide(obs)
    assert relaxed.action is DecisionAction.ACCEPT, relaxed.reasons
    assert DecisionReason.BOUNDED_WRITE_ACCEPT in relaxed.reasons


def test_an_intent_that_did_not_resolve_refuses_even_when_intent_is_optional() -> None:
    """Optional means "none presented" may pass; a presented intent that failed
    to resolve is a negative fact, not an absence."""
    report = _engine(bounded_write_intent_optional=True).decide(
        _bounded(intent_authority_present=False))
    assert report.action is not DecisionAction.ACCEPT


@pytest.mark.parametrize("action_type", ["read", "read_only", "query", "list"])
def test_reads_are_not_this_paths_business(action_type: str) -> None:
    report = _engine().decide(_bounded(action_type=action_type))
    assert DecisionReason.BOUNDED_WRITE_ACCEPT not in report.reasons


def test_a_decision_some_other_check_lowers_is_never_raised() -> None:
    """Over a grid of safety signals, the path never turns a non-ACCEPT the
    engine without it decides into an ACCEPT except at the fall-through."""
    signals = [dict(argument_tainted=True), dict(tool_forbidden=True),
               dict(adversarial_detected=True), dict(schema_valid=False),
               dict(rollback_available=False), dict(environment_mismatch_detected=True),
               dict(state_transition_uncertain=True), dict(argument_scope_valid=False),
               dict(tool_matches_goal=False), dict(expected_effect_matches=False),
               dict(intent_scope_status="out_of_scope"),
               dict(missing_required_arguments=("minutes",)),
               dict(unvalidated_required_arguments=("unit",))]
    for signal in signals:
        obs = _bounded(**signal)
        on, off = _engine().decide(obs), _off().decide(obs)
        assert on.action is not DecisionAction.ACCEPT, signal
        assert (on.action, on.reasons) == (off.action, off.reasons), signal


def test_explain_names_the_path() -> None:
    trace = _engine().explain(_bounded())
    rows = {row.rule: row for row in trace.rule_evaluations}
    assert rows["bounded_write_accept"].triggered is True
    assert trace.action == "accept"


# ── Policy identity and the execution surface's configuration ────────────────

def test_the_flags_join_the_identity_only_when_on() -> None:
    from servers import api

    for flag in ("bounded_write_accept", "bounded_write_medium_tier",
                 "bounded_write_intent_optional"):
        assert flag in api.ENGINE_IDENTITY_FLAGS
    off = api.engine_mode_identity(_off())
    assert not any(name.startswith("bounded_write") for name in off)
    on = api.engine_mode_identity(_engine())
    assert on == {**off, "bounded_write_accept": True}


def _clear(monkeypatch) -> None:
    for var in ("REMORA_BOUNDED_WRITE_ACCEPT", "REMORA_BOUNDED_WRITE_MAX_TIER",
                "REMORA_BOUNDED_WRITE_REQUIRE_INTENT"):
        monkeypatch.delenv(var, raising=False)


def test_the_api_reads_the_opt_in_and_defaults_off(monkeypatch) -> None:
    from servers import execution_api

    _clear(monkeypatch)
    engine = execution_api._engine_from_env()
    assert engine.bounded_write_accept is False
    assert engine.bounded_write_medium_tier is False
    assert engine.bounded_write_intent_optional is False
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("REMORA_BOUNDED_WRITE_ACCEPT", value)
        assert execution_api._engine_from_env().bounded_write_accept is True, value
    for value in ("0", "false", "", "off"):
        monkeypatch.setenv("REMORA_BOUNDED_WRITE_ACCEPT", value)
        assert execution_api._engine_from_env().bounded_write_accept is False, value


@pytest.mark.parametrize("value,medium", [("", False), ("low", False), (" LOW ", False),
                                          ("medium", True), ("Medium", True)])
def test_the_tier_ceiling_is_low_or_medium(monkeypatch, value: str, medium: bool) -> None:
    from servers import execution_api

    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_BOUNDED_WRITE_MAX_TIER", value)
    assert execution_api._engine_from_env().bounded_write_medium_tier is medium


@pytest.mark.parametrize("value", ["high", "critical", "unknown", "lowest", "1"])
def test_any_other_tier_ceiling_refuses_to_start(monkeypatch, value: str) -> None:
    from servers import execution_api

    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_BOUNDED_WRITE_MAX_TIER", value)
    with pytest.raises(ValueError, match="REMORA_BOUNDED_WRITE_MAX_TIER"):
        execution_api._engine_from_env()


def test_intent_is_required_unless_explicitly_turned_off(monkeypatch) -> None:
    from servers import execution_api

    _clear(monkeypatch)
    assert execution_api._engine_from_env().bounded_write_intent_optional is False
    for value in ("0", "false", "no", "off"):
        monkeypatch.setenv("REMORA_BOUNDED_WRITE_REQUIRE_INTENT", value)
        assert execution_api._engine_from_env().bounded_write_intent_optional is True, value
    for value in ("1", "true", "", "anything"):
        monkeypatch.setenv("REMORA_BOUNDED_WRITE_REQUIRE_INTENT", value)
        assert execution_api._engine_from_env().bounded_write_intent_optional is False, value
