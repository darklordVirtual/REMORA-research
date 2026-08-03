# SPDX-License-Identifier: BUSL-1.1
"""``expected_effect_matches``: the declared-effect authority.

The discipline under test is the same one ``goal_match`` established: a model
may propose an intent, and may not thereby assert SUPPORTED. Every clause that
reaches SUPPORTED must be re-derivable from the task text and the deployment's
own contract, and everything unestablished must land on UNKNOWN rather than
drifting toward either verdict.
"""
from __future__ import annotations

import pytest

from remora.policy import PolicyObservation, RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason
from remora.toolcall.routing.effect_prediction import (
    EffectConsistency,
    effect_consistent,
    predict_state_delta,
)
from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.routing.tool_contract import ToolContract

TASK = "Please close work order 4471 for me."


def _close_contract(**overrides) -> ToolContract:
    defaults = dict(
        tool="close_work_order",
        capability="work_order_management",
        effect="close",
        resource_type="work_order",
        mutation=True,
        argument_roles={"work_order_id": "target_resource"},
        state_delta={"work_order.status": "closed"},
        preconditions=("closure_approved",),
    )
    defaults.update(overrides)
    return ToolContract(**defaults)


def _read_contract(**overrides) -> ToolContract:
    defaults = dict(
        tool="get_work_order",
        capability="work_order_management",
        effect="read",
        resource_type="work_order",
        mutation=False,
        argument_roles={"work_order_id": "target_resource"},
    )
    defaults.update(overrides)
    return ToolContract(**defaults)


def _intent(**overrides) -> TaskIntent:
    defaults = dict(
        operation="close",
        resource_type="work_order",
        requested_effect="close",
        target_entities=("target_resource",),
        source_spans=("close work order 4471",),
        proposed_by="test",
    )
    defaults.update(overrides)
    return TaskIntent(**defaults)


def _verdict(contract, intent, args=None, task=TASK) -> EffectConsistency:
    return effect_consistent(
        contract=contract,
        intent=intent,
        proposed_args=args or {"work_order_id": "4471"},
        task_text=task,
    ).verdict


# ── SUPPORTED requires a positive, re-derivable declaration ──────────────────


def test_declared_write_on_the_named_resource_is_supported() -> None:
    assert _verdict(_close_contract(), _intent()) is EffectConsistency.SUPPORTED


def test_read_request_served_by_a_read_tool_is_supported() -> None:
    intent = _intent(
        operation="show", requested_effect="read", source_spans=("work order 4471",)
    )
    assert _verdict(_read_contract(), intent) is EffectConsistency.SUPPORTED


# ── Established contradictions ───────────────────────────────────────────────


def test_read_request_served_by_a_mutating_tool_is_contradicted() -> None:
    """The headline case: the user asked to see it, the tool would close it."""
    intent = _intent(
        operation="show", requested_effect="read", source_spans=("work order 4471",)
    )
    result = effect_consistent(
        contract=_close_contract(),
        intent=intent,
        proposed_args={"work_order_id": "4471"},
        task_text=TASK,
    )
    assert result.verdict is EffectConsistency.CONTRADICTED
    assert "read" in result.reason
    assert result.as_bool is False


def test_change_request_served_by_a_read_only_tool_is_contradicted() -> None:
    result = effect_consistent(
        contract=_read_contract(),
        intent=_intent(),
        proposed_args={"work_order_id": "4471"},
        task_text=TASK,
    )
    assert result.verdict is EffectConsistency.CONTRADICTED
    assert "cannot achieve" in result.reason


def test_declared_post_state_on_a_different_resource_is_contradicted() -> None:
    """Caught here and nowhere earlier: the labels all agree, the delta does not.

    ``resource_type`` says work_order and ``effect`` says close, so the goal
    matcher is satisfied. The declared post-state writes an invoice.
    """
    contract = _close_contract(state_delta={"invoice.status": "void"})
    result = effect_consistent(
        contract=contract,
        intent=_intent(),
        proposed_args={"work_order_id": "4471"},
        task_text=TASK,
    )
    assert result.verdict is EffectConsistency.CONTRADICTED
    assert "invoice" in result.reason


# ── Everything unestablished lands on UNKNOWN ────────────────────────────────


def test_no_contract_is_unknown() -> None:
    assert _verdict(None, _intent()) is EffectConsistency.UNKNOWN


def test_no_intent_is_unknown() -> None:
    assert _verdict(_close_contract(), None) is EffectConsistency.UNKNOWN


def test_intent_not_quoted_from_the_task_is_unknown() -> None:
    """A fabricated intent must not be able to establish anything."""
    invented = _intent(source_spans=("delete every work order",))
    assert _verdict(_close_contract(), invented) is EffectConsistency.UNKNOWN


def test_mutating_tool_with_no_declared_delta_is_unknown_not_supported() -> None:
    """A tightening: a matching label is not a declared effect.

    ``goal_match`` says SUPPORTED here, because the effect labels agree. This
    authority declines, because nothing declares what the call would change.
    """
    contract = _close_contract(state_delta={})
    result = effect_consistent(
        contract=contract,
        intent=_intent(),
        proposed_args={"work_order_id": "4471"},
        task_text=TASK,
    )
    assert result.verdict is EffectConsistency.UNKNOWN
    assert result.as_bool is None


# ── The contract itself must not be self-contradictory ───────────────────────


def test_read_contract_declaring_a_state_delta_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="read cannot leave a changed state"):
        ToolContract(
            tool="get_work_order",
            capability="work_order_management",
            effect="read",
            resource_type="work_order",
            mutation=False,
            state_delta={"work_order.status": "closed"},
        )


def test_contracts_round_trip_through_json_with_the_new_fields() -> None:
    contract = _close_contract()
    from remora.toolcall.routing.tool_contract import ToolContractRegistry

    registry = ToolContractRegistry([contract])
    restored = ToolContractRegistry.from_json_dict(registry.to_json_dict())
    assert restored.get("close_work_order") == contract


def test_prediction_reports_undeclared_separately_from_empty() -> None:
    """A mutating tool with no delta is undeclared, not harmless."""
    predicted = predict_state_delta(_close_contract(state_delta={}))
    assert predicted is not None
    assert predicted.mutates is True
    assert predicted.declared is False
    assert predicted.changes == {}


# ── Policy integration: tightens only ────────────────────────────────────────


def _observation(**overrides) -> PolicyObservation:
    defaults = dict(question="close work order 4471", action_type="state_change")
    defaults.update(overrides)
    return PolicyObservation(**defaults)


def test_contradicted_effect_escalates_a_write() -> None:
    report = RemoraDecisionEngine().decide(
        _observation(expected_effect_matches=False)
    )
    assert report.action is DecisionAction.ESCALATE
    assert DecisionReason.EXPECTED_EFFECT_CONTRADICTED in report.reasons


def test_contradicted_effect_abstains_on_a_read() -> None:
    report = RemoraDecisionEngine().decide(
        _observation(action_type="read", expected_effect_matches=False)
    )
    assert report.action is DecisionAction.ABSTAIN
    assert DecisionReason.EXPECTED_EFFECT_CONTRADICTED in report.reasons


@pytest.mark.parametrize("value", [None, True])
def test_unknown_or_supported_effect_never_fires_the_gate(value) -> None:
    """The gate may tighten a route; it may never be the thing that loosens one.

    An established True must not buy autonomy either — it only removes this
    one refutation, leaving every other floor exactly where it was.
    """
    report = RemoraDecisionEngine().decide(
        _observation(expected_effect_matches=value)
    )
    assert DecisionReason.EXPECTED_EFFECT_CONTRADICTED not in report.reasons


def test_supported_effect_does_not_relax_a_critical_tier_floor() -> None:
    baseline = RemoraDecisionEngine().decide(
        _observation(risk_tier="critical", expected_effect_matches=None)
    )
    with_signal = RemoraDecisionEngine().decide(
        _observation(risk_tier="critical", expected_effect_matches=True)
    )
    assert with_signal.action is baseline.action
