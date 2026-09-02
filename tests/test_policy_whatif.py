# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What-if decision-boundary analysis (``remora.policy.whatif``).

The module answers "what would have to change for this call to reach a
verdict" by bounded search over the real engine. Two properties matter more
than any single example and both are asserted over grids here:

* soundness: every counterfactual the report names, when applied to the
  observation and decided by the same engine, yields the action it claims;
* minimality: no proper subset of a reported minimal path reaches the target.

The examples then pin the statements the front page makes: a critical
production write cannot be lifted by any model signal, a hard guard is named
as such, and an execution-profile engine never lets model signals produce
ACCEPT for anything.
"""
from __future__ import annotations

import dataclasses
import itertools
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.assess import what_if_tool_call
from remora.policy import PolicyObservation, RemoraDecisionEngine
from remora.policy.decision_engine import hard_guard_floor
from remora.policy.report import DecisionAction
from remora.policy.whatif import (
    LEVERS,
    Counterfactual,
    Lever,
    LeverKind,
    WhatIfReport,
    what_if,
)


def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation.from_tool_call(
        name=kwargs.pop("name", "tool"), arguments=kwargs.pop("arguments", {"x": 1}),
        **kwargs,
    )


def _replay(obs: PolicyObservation, path: Counterfactual) -> PolicyObservation:
    """Re-apply a counterfactual's changes to *obs* by hand."""
    return dataclasses.replace(obs, **{c.field: c.after for c in path.changes})


def _levers_by_name() -> dict[str, Lever]:
    return {lv.name: lv for lv in LEVERS}


CRITICAL_PROD_WRITE = dict(risk_tier="critical", action_type="destructive_write",
                           target_environment="prod")
STAGING_READ = dict(risk_tier="low", action_type="read", target_environment="staging")


# ---------------------------------------------------------------------------
# Lever catalogue
# ---------------------------------------------------------------------------

def test_lever_catalogue_names_are_unique_and_fields_exist() -> None:
    names = [lv.name for lv in LEVERS]
    assert len(names) == len(set(names))
    fields = {f.name for f in dataclasses.fields(PolicyObservation)}
    for lv in LEVERS:
        assert lv.fields <= fields, lv.name
        assert lv.description


def test_every_lever_kind_is_represented() -> None:
    kinds = {lv.kind for lv in LEVERS}
    assert kinds == set(LeverKind)


def test_every_hard_guard_input_has_a_lever() -> None:
    """Each observation field the hard-guard floor reads must be liftable, or
    a hard-guarded call could never be explained past the guard."""
    guarded = {
        "adversarial_detected", "schema_valid", "tool_forbidden",
        "argument_scope_valid", "intent_provenance_resolved", "coercion_detected",
        "blackmail_pattern_detected", "counterfactual_passed",
        "evidence_contradictions", "argument_tainted",
    }
    covered = set().union(*(lv.fields for lv in LEVERS))
    assert guarded <= covered


def test_lever_applies_only_when_it_changes_something() -> None:
    lv = _levers_by_name()["high_trust"]
    assert lv.applies_to(_obs(trust_score=None))
    assert not lv.applies_to(_obs(trust_score=0.95))
    assert lv.apply(_obs(trust_score=None)).trust_score == 0.95


# ---------------------------------------------------------------------------
# Headline behaviours
# ---------------------------------------------------------------------------

def test_critical_production_write_cannot_be_lifted_by_model_signals() -> None:
    report = what_if(_obs(**CRITICAL_PROD_WRITE))
    assert report.current_action is DecisionAction.ESCALATE
    assert report.model_signals_alone is None
    assert not report.confidence_can_lift
    assert report.hard_guard is None
    assert report.exhausted


def test_critical_production_write_only_reaches_accept_as_a_different_tool() -> None:
    """Every minimal path re-declares the tool: the registry must call it
    low or medium risk AND the ToolSpec must declare it read-only."""
    report = what_if(_obs(**CRITICAL_PROD_WRITE))
    assert report.reachable
    assert report.deployment_facts_required
    for path in report.minimal_paths:
        fields = {c.field: c.after for c in path.changes}
        assert fields["action_type"] == "read"
        assert fields["risk_tier"] in {"low", "medium"}
        assert LeverKind.MODEL_SIGNAL in path.kinds


def test_prompt_injection_is_a_named_hard_guard() -> None:
    report = what_if(_obs(adversarial_detected=True, **STAGING_READ), max_depth=2)
    assert report.hard_guard == "admission_firewall_blocked"
    assert report.model_signals_alone is None
    for path in report.minimal_paths:
        assert any(c.field == "adversarial_detected" and c.after is False
                   for c in path.changes)


def test_forbidden_tool_paths_all_permit_the_tool() -> None:
    report = what_if(_obs(tool_forbidden=True, **STAGING_READ), max_depth=3)
    assert report.hard_guard == "forbidden_tool_blocked"
    assert report.reachable
    for path in report.minimal_paths:
        assert any(c.field == "tool_forbidden" for c in path.changes)


def test_staging_read_is_lifted_by_model_signals_alone() -> None:
    report = what_if(_obs(**STAGING_READ))
    assert report.current_action is DecisionAction.ABSTAIN
    assert report.confidence_can_lift
    assert report.model_signals_alone is not None
    assert report.model_signals_alone.kinds == {LeverKind.MODEL_SIGNAL}
    assert report.minimal_paths[0].size == 2
    assert not report.deployment_facts_required


def test_minimal_paths_are_ordered_cheapest_first() -> None:
    report = what_if(_obs(**STAGING_READ))
    first = report.minimal_paths[0]
    assert first.levers == ("high_trust", "ordered_phase")
    assert len(first.changes) == 2


def test_abstain_reaches_verify_through_intent_authority() -> None:
    """The one deployment fact that puts a fall-through in front of a person
    is a server-resolved intent authority (authority_resolved_review)."""
    report = what_if(_obs(**STAGING_READ), target=DecisionAction.VERIFY)
    assert report.reachable
    assert report.minimal_paths[0].size == 1
    by_lever = {p.levers[0]: p for p in report.minimal_paths}
    assert "intent_authority" in by_lever
    assert by_lever["intent_authority"].reasons == ("authority_resolved_review",)


def test_already_at_target_does_no_search() -> None:
    report = what_if(_obs(trust_score=0.95, phase="ordered", **STAGING_READ))
    assert report.already_at_target
    assert report.reachable
    assert report.confidence_can_lift
    assert report.evaluations == 0
    assert report.minimal_paths == ()
    assert not report.deployment_facts_required
    assert "already ACCEPT" in report.summary()


@pytest.mark.parametrize("kwargs", [
    CRITICAL_PROD_WRITE,
    STAGING_READ,
    dict(risk_tier="medium", action_type="write", target_environment="prod"),
    dict(risk_tier="high", action_type="financial_transaction", target_environment="prod"),
])
def test_execution_profile_never_lets_model_signals_accept(kwargs) -> None:
    """Issue #35 invariant, restated as a what-if: with the execution profile
    no combination of model signals reaches ACCEPT, for any call."""
    engine = RemoraDecisionEngine(execution_profile=True)
    report = what_if(_obs(**kwargs), engine, max_depth=2)
    assert not report.already_at_target
    assert report.model_signals_alone is None


def test_grounded_read_accept_path_is_found_when_opted_in() -> None:
    """With grounded_read_accept on, the deterministic ACCEPT is reachable by
    deployment facts alone; the report names them and no model signal."""
    engine = RemoraDecisionEngine(grounded_read_accept=True)
    base = _obs(schema_valid=True, intent_authority_present=True,
                tool_matches_goal=True, expected_effect_matches=True,
                argument_values_supported=True, **STAGING_READ)
    report = what_if(base, engine, max_depth=2)
    assert report.reachable
    deployment_only = [p for p in report.minimal_paths
                       if p.kinds == {LeverKind.DEPLOYMENT_FACT}]
    assert deployment_only
    assert any("grounded_read_accept" in p.reasons for p in deployment_only)


# ---------------------------------------------------------------------------
# Soundness and minimality over a grid
# ---------------------------------------------------------------------------

_GRID = [
    dict(risk_tier=r, action_type=a, target_environment=e, **extra)
    for r in ("low", "high", "critical")
    for a in ("read", "write", "destructive_write")
    for e in ("staging", "prod")
    for extra in ({}, {"tool_forbidden": True}, {"argument_tainted": True})
]


@pytest.mark.parametrize("kwargs", _GRID, ids=lambda k: "-".join(str(v) for v in k.values()))
def test_reported_paths_are_sound_and_minimal(kwargs) -> None:
    engine = RemoraDecisionEngine()
    obs = _obs(**kwargs)
    report = what_if(obs, engine, max_depth=3)
    assert report.exhausted
    levers = _levers_by_name()
    for path in report.minimal_paths:
        # Soundness: the engine really returns the claimed action.
        replayed = engine.decide(_replay(obs, path))
        assert replayed.action is report.target
        assert tuple(r.value for r in replayed.reasons) == path.reasons
        # Minimality: dropping any lever loses the target.
        for k in range(1, path.size):
            for subset in itertools.combinations(path.levers, k):
                partial = obs
                for name in subset:
                    partial = levers[name].apply(partial)
                assert engine.decide(partial).action is not report.target, (
                    f"subset {subset} of {path.levers} already reaches the target")
    if report.model_signals_alone is not None:
        replayed = engine.decide(_replay(obs, report.model_signals_alone))
        assert replayed.action is report.target


@pytest.mark.parametrize("kwargs", _GRID, ids=lambda k: "-".join(str(v) for v in k.values()))
def test_hard_guard_field_matches_the_engine_floor(kwargs) -> None:
    obs = _obs(**kwargs)
    report = what_if(obs, max_depth=1)
    floor = hard_guard_floor(obs)
    assert report.hard_guard == (floor[1].value if floor else None)


@settings(max_examples=40, deadline=None)
@given(
    risk=st.sampled_from(["low", "medium", "high", "critical", None]),
    action=st.sampled_from(["read", "write", "deploy", "destructive_write", None]),
    env=st.sampled_from(["staging", "prod"]),
    trust=st.sampled_from([None, 0.2, 0.8]),
    phase=st.sampled_from([None, "ordered", "critical", "disordered"]),
    tainted=st.booleans(),
    schema=st.sampled_from([None, True, False]),
)
def test_property_every_named_path_replays_to_its_verdict(
    risk, action, env, trust, phase, tainted, schema,
) -> None:
    engine = RemoraDecisionEngine()
    obs = _obs(risk_tier=risk, action_type=action, target_environment=env,
               trust_score=trust, phase=phase, argument_tainted=tainted,
               schema_valid=schema)
    report = what_if(obs, engine, max_depth=2, max_evaluations=2_000)
    for path in report.minimal_paths:
        assert engine.decide(_replay(obs, path)).action is DecisionAction.ACCEPT
    assert report.evaluations <= 2_000


# ---------------------------------------------------------------------------
# Bounds and serialisation
# ---------------------------------------------------------------------------

def test_budget_exhaustion_is_reported_not_hidden() -> None:
    report = what_if(_obs(**CRITICAL_PROD_WRITE), max_depth=4, max_evaluations=50)
    assert not report.exhausted
    assert report.evaluations <= 50
    assert report.minimal_paths == ()
    assert not report.deployment_facts_required
    assert "within the evaluation budget" in report.summary()


def test_search_bound_without_a_path_says_so() -> None:
    report = what_if(_obs(**CRITICAL_PROD_WRITE), max_depth=1)
    assert report.exhausted
    assert not report.reachable
    assert "up to the search bound" in report.summary()


def test_invalid_bounds_are_rejected() -> None:
    with pytest.raises(ValueError):
        what_if(_obs(**STAGING_READ), max_depth=0)
    with pytest.raises(ValueError):
        what_if(_obs(**STAGING_READ), max_evaluations=0)


def test_model_signal_answer_is_independent_of_the_budget() -> None:
    """The model-signal sub-space is always searched first and in full, so a
    tight budget cannot turn a real lift into a false 'cannot'."""
    report = what_if(_obs(**STAGING_READ), max_depth=4, max_evaluations=20)
    assert report.model_signals_alone is not None


def test_report_round_trips_through_json() -> None:
    report = what_if(_obs(**STAGING_READ))
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["target"] == "accept"
    assert payload["current_action"] == "abstain"
    assert payload["confidence_can_lift"] is True
    assert payload["minimal_path_size"] == 2
    assert payload["search"]["exhausted"] is True
    first = payload["minimal_paths"][0]
    assert first["levers"] == ["high_trust", "ordered_phase"]
    assert {c["kind"] for c in first["changes"]} == {"model_signal"}
    assert isinstance(report, WhatIfReport)


def test_summary_names_the_hard_guard_and_the_verdict() -> None:
    text = what_if(_obs(adversarial_detected=True, **STAGING_READ), max_depth=1).summary()
    assert text.startswith("verdict now: ESCALATE")
    assert "hard guard: admission_firewall_blocked" in text
    assert "cannot reach ACCEPT" in text


def test_observation_is_never_mutated() -> None:
    obs = _obs(**CRITICAL_PROD_WRITE)
    before = dataclasses.asdict(obs)
    what_if(obs, max_depth=2)
    assert dataclasses.asdict(obs) == before


# ---------------------------------------------------------------------------
# Library entry point
# ---------------------------------------------------------------------------

def test_what_if_tool_call_uses_the_same_observation_as_assess() -> None:
    assessment, report = what_if_tool_call(
        "drop_database", {"db": "prod-main"},
        risk_tier="critical", action_type="destructive_write")
    assert assessment.action == "escalate"
    assert report.current_action is DecisionAction.ESCALATE
    assert report.current_reasons == tuple(r.value for r in assessment.decision.reasons)
    assert not report.confidence_can_lift


def test_what_if_tool_call_targets_verify_and_honours_inference() -> None:
    assessment, report = what_if_tool_call(
        "read_file", {"path": "/etc/x"}, target_environment="staging",
        infer=True, target="verify", max_depth=1)
    assert assessment.inferred == {"action_type": "read", "risk_tier": "low"}
    assert report.target is DecisionAction.VERIFY
    assert report.reachable


def test_what_if_tool_call_rejects_unknown_target() -> None:
    with pytest.raises(ValueError):
        what_if_tool_call("read_file", target="maybe")


def test_top_level_exports_resolve() -> None:
    import remora

    assert remora.what_if is what_if
    assert remora.WhatIfReport is WhatIfReport
    assert remora.what_if_tool_call is what_if_tool_call


def test_summary_lists_every_path_and_the_deployment_boundary() -> None:
    text = what_if(_obs(**CRITICAL_PROD_WRITE)).summary()
    assert "model signals alone: cannot reach ACCEPT" in text
    assert "smallest change sets reaching ACCEPT:" in text
    assert "risk_tier: 'critical' -> 'low'  [deployment_fact]" in text
    assert text.endswith("every path needs a fact only the deployment can declare")


def test_summary_names_the_model_signal_lift() -> None:
    text = what_if(_obs(**STAGING_READ)).summary()
    assert "model signals alone: reach ACCEPT via high_trust + ordered_phase" in text
    assert "deployment can declare" not in text


def test_change_serialisation_flattens_tuples_and_enums() -> None:
    from remora.policy.whatif import Change, _jsonable

    assert _jsonable(("a", "b")) == ["a", "b"]
    assert _jsonable(DecisionAction.ACCEPT) == "accept"
    assert _jsonable(0.5) == 0.5
    change = Change(lever="arguments_complete", kind=LeverKind.DEPLOYMENT_FACT,
                    field="missing_required_arguments", before=("id",), after=(),
                    description="no required argument is missing")
    payload = json.loads(json.dumps(change.to_dict()))
    assert payload["before"] == ["id"]
    assert payload["after"] == []
    assert payload["kind"] == "deployment_fact"


# ---------------------------------------------------------------------------
# Round 2: agent-alone search, single-lever effects, pruning, memo
# ---------------------------------------------------------------------------

from remora.policy.whatif import AGENT_KINDS, UNLEVERED_ENGINE_FIELDS, LeverEffect  # noqa: E402


def test_agent_alone_cannot_lift_a_critical_production_write() -> None:
    """The stronger statement: proposal changes plus model signals, with no
    deployment-declared fact, never reach ACCEPT within the bound."""
    report = what_if(_obs(**CRITICAL_PROD_WRITE))
    assert report.without_deployment is None
    assert not report.agent_alone_can_reach
    assert report.deployment_facts_required


def test_agent_alone_lifts_a_staging_read_and_names_only_agent_kinds() -> None:
    report = what_if(_obs(**STAGING_READ))
    assert report.without_deployment is not None
    assert report.without_deployment.kinds <= AGENT_KINDS
    assert report.agent_alone_can_reach
    assert not report.deployment_facts_required


def test_moving_a_low_confidence_prod_write_to_staging_is_an_agent_change() -> None:
    """A medium-risk prod write with high trust but low environment confidence
    is held only by the env-confidence gate; the agent can lift it by
    proposing a staging target, with no deployment fact changing."""
    report = what_if(_obs(risk_tier="medium", action_type="write", target_environment="prod",
                          trust_score=0.95, phase="ordered", schema_valid=True,
                          environment_confidence=0.3), max_depth=2)
    assert report.current_reasons == ("env_confidence_verify",)
    assert report.model_signals_alone is None
    assert report.without_deployment is not None
    assert report.without_deployment.levers == ("non_production_target",)
    assert report.without_deployment.kinds == {LeverKind.PROPOSAL}
    assert report.agent_alone_can_reach
    assert "environment_confirmed" in report.moving_levers


def test_single_lever_effects_cover_every_applicable_lever() -> None:
    report = what_if(_obs(**CRITICAL_PROD_WRITE), max_depth=1)
    assert tuple(e.lever for e in report.single_lever_effects) == report.levers_considered
    assert all(isinstance(e, LeverEffect) for e in report.single_lever_effects)
    moving = set(report.moving_levers)
    assert "non_production_target" in moving
    assert "read_only_action" in moving
    assert "high_trust" not in moving


def test_single_lever_effects_replay_to_their_verdict() -> None:
    engine = RemoraDecisionEngine()
    obs = _obs(**CRITICAL_PROD_WRITE)
    report = what_if(obs, engine, max_depth=1)
    levers = _levers_by_name()
    for effect in report.single_lever_effects:
        replayed = engine.decide(levers[effect.lever].apply(obs))
        assert replayed.action is effect.action
        assert effect.moves == (effect.action is not report.current_action)


@pytest.mark.parametrize("kwargs", [
    dict(adversarial_detected=True, **STAGING_READ),
    dict(tool_forbidden=True, **STAGING_READ),
    dict(argument_tainted=True, risk_tier="critical", action_type="write",
         target_environment="staging"),
    dict(schema_valid=False, **STAGING_READ),
    dict(evidence_contradictions=2, **STAGING_READ),
])
def test_hard_guard_pruning_changes_nothing_but_the_evaluation_count(kwargs) -> None:
    obs = _obs(**kwargs)
    pruned = what_if(obs, max_depth=3)
    plain = what_if(obs, max_depth=3, prune=False)
    assert pruned.pruned
    assert not plain.pruned
    assert pruned.evaluations < plain.evaluations
    assert [p.to_dict() for p in pruned.minimal_paths] == [p.to_dict() for p in plain.minimal_paths]
    assert (pruned.model_signals_alone is None) == (plain.model_signals_alone is None)
    assert (pruned.without_deployment is None) == (plain.without_deployment is None)


def test_pruning_is_not_applied_for_target_verify() -> None:
    """A tainted floor yields VERIFY itself, so a VERIFY search cannot assume
    the guard's fields must change."""
    obs = _obs(argument_tainted=True, risk_tier="critical", action_type="write",
               target_environment="staging")
    report = what_if(obs, target=DecisionAction.VERIFY, max_depth=2)
    assert not report.pruned
    assert report.reachable
    assert any(p.levers in {("risk_low",), ("risk_medium",)} for p in report.minimal_paths)


def test_pruning_never_fires_without_a_hard_guard() -> None:
    report = what_if(_obs(**CRITICAL_PROD_WRITE), max_depth=2)
    assert report.hard_guard is None
    assert not report.pruned


def test_evaluations_count_distinct_engine_calls() -> None:
    """The sub-space searches and the full search overlap; the memo makes
    the count a count of distinct combinations."""
    obs = _obs(**STAGING_READ)
    report = what_if(obs, max_depth=2)
    n = len(report.levers_considered)
    max_distinct = n + n * (n - 1) // 2   # singles + pairs, before disjointness
    assert report.evaluations <= max_distinct


def test_temperature_lever_only_matters_with_a_threshold_engine() -> None:
    obs = _obs(temperature=0.9, **STAGING_READ)
    plain = what_if(obs, max_depth=1)
    assert "low_temperature" not in plain.moving_levers
    engine = RemoraDecisionEngine(temperature_threshold=0.2)
    report = what_if(obs, engine, max_depth=1)
    assert "low_temperature" in report.moving_levers
    assert report.model_signals_alone is not None
    assert report.model_signals_alone.levers == ("low_temperature",)


def test_every_engine_read_field_is_levered_or_explained() -> None:
    """Completeness gate: when the engine starts reading a new observation
    field, it must get a lever or an entry in UNLEVERED_ENGINE_FIELDS."""
    import re
    from pathlib import Path

    import remora.policy.decision_engine as engine_module

    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    fields = {f.name for f in dataclasses.fields(PolicyObservation)}
    read = {m for m in re.findall(r"\b(?:obs|o|raw_obs)\.([a-z_0-9]+)\b", source)} & fields
    covered = set().union(*(lv.fields for lv in LEVERS))
    unexplained = read - covered - set(UNLEVERED_ENGINE_FIELDS)
    assert not unexplained, sorted(unexplained)
    stale = set(UNLEVERED_ENGINE_FIELDS) - read
    assert not stale, sorted(stale)


def test_lever_to_dict_and_report_to_dict_carry_round_two_fields() -> None:
    lever = _levers_by_name()["evidence_supports"]
    assert lever.to_dict() == {
        "name": "evidence_supports", "kind": "model_signal",
        "assignments": {"evidence_action": "answer", "evidence_confidence": 0.95},
        "description": lever.description,
    }
    payload = json.loads(json.dumps(what_if(_obs(**STAGING_READ), max_depth=2).to_dict()))
    assert payload["agent_alone_can_reach"] is True
    assert payload["without_deployment"]["kinds"] == ["model_signal"]
    assert payload["moving_levers"]
    assert {e["lever"] for e in payload["single_lever_effects"]} == set(payload["search"]["levers_considered"])
    assert payload["search"]["pruned"] is False


def test_summary_states_agent_alone_and_moving_levers() -> None:
    text = what_if(_obs(**CRITICAL_PROD_WRITE), max_depth=2).summary()
    assert "agent alone (proposal + model signals): cannot reach ACCEPT within 2 changes" in text
    assert "single levers that move the verdict: non_production_target, read_only_action" in text
