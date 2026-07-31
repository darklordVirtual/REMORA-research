# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for declarative argument-validator bindings (§32 follow-up).

§32 measured the UNKNOWN gap: with no closed-world coverage, 50% of corrupted
identifiers were accepted on read-only calls, because nothing bound
``vehicle_id`` to the tool that can confirm it — ``get_vehicle`` *is* the
validator, but name-derived resolver matching cannot see that.

The binding is declarative, not name-derived: a deployment names which tool
validates which argument role, under which tenant, with what attempt budget.
The resolver validates and re-enters; it never overrides policy — it only
changes what the fresh observation can say about the value.

The invariants:

* a validator that is not authoritative cannot be declared — a VERIFY grounded
  on a non-authoritative lookup would be §29 with extra steps
* validators are tenant-bound; a foreign tenant's validator is never consulted
* exists → re-enter with the value confirmed; reads may then ACCEPT
* absent → the call is blocked, never retried into acceptance
* unknown / error → ABSTAIN; a validation that cannot happen is not promised
* the attempt budget is enforced; UNKNOWN+OPTIONAL never routes to VERIFY
  (the §21 constant blocker must not be rebuilt one level up)
"""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.report import DecisionAction
from remora.policy.resolution import validate_and_reenter
from remora.toolcall.routing.compatibility import StateIndex
from remora.toolcall.routing.episode import RoutingEpisode
from remora.toolcall.routing.evaluate import build_full_observation
from remora.toolcall.routing.sources.fleetops import fleetops_registry
from remora.toolcall.routing.validation import ValidationRequirement, requirement_for
from remora.toolcall.routing.validators import (
    ArgumentValidator,
    ValidatorInvalid,
    ValidatorRegistry,
)

TENANT = "fleetops_fixture"


def _validator(**overrides) -> ArgumentValidator:
    base = dict(
        argument_role="vehicle_id",
        tool="get_vehicle",
        input_argument="vehicle_id",
        tenant=TENANT,
    )
    base.update(overrides)
    return ArgumentValidator(**base)


def _episode(tool: str = "get_vehicle", args: dict | None = None) -> RoutingEpisode:
    return RoutingEpisode(
        id="tau2:fleetops:t:v",
        source_dataset="tau2",
        source_commit="test",
        cluster_id="tau2:fleetops:t:v",
        user_task="Look up get vehicle V-0001 for the dispatcher.",
        available_tools=(tool,),
        untrusted_context=None,
        proposed_tool_name=tool,
        proposed_tool_args=args if args is not None else {"vehicle_id": "V-0001"},
        domain="fleetops",
        notes=("mutation:identity",),
    )


#: An index with values but no coverage scopes: every verdict is UNKNOWN —
#: the §32 uncovered regime the validator binding exists to close.
UNCOVERED = StateIndex.from_values({"V-0001", "D-0001"}, scopes=())

ENGINE = RemoraDecisionEngine(low_consequence_accept=True)


# ---------------------------------------------------------------------------
# Binding construction and scoping
# ---------------------------------------------------------------------------

def test_a_non_authoritative_validator_is_refused() -> None:
    with pytest.raises(ValidatorInvalid, match="authoritative"):
        _validator(authoritative=False)


@pytest.mark.parametrize(
    "field", ["argument_role", "tool", "input_argument", "tenant"]
)
def test_every_binding_field_is_mandatory(field: str) -> None:
    with pytest.raises(ValidatorInvalid, match=field):
        _validator(**{field: " "})


def test_registry_is_tenant_scoped() -> None:
    registry = ValidatorRegistry((_validator(),))
    assert registry.for_argument("vehicle_id", tenant=TENANT) is not None
    assert registry.for_argument("vehicle_id", tenant="other_tenant") is None


def test_scoped_registry_drops_foreign_tenants() -> None:
    registry = ValidatorRegistry(
        (_validator(), _validator(argument_role="driver_id", tenant="tenant_b"))
    )
    scoped = registry.scoped(TENANT)
    assert scoped.for_argument("vehicle_id", tenant=TENANT) is not None
    assert scoped.for_argument("driver_id", tenant=TENANT) is None


def test_bindings_round_trip_through_json() -> None:
    registry = ValidatorRegistry((_validator(max_attempts=2),))
    loaded = ValidatorRegistry.from_json_dict(registry.to_json_dict())
    assert loaded == registry


# ---------------------------------------------------------------------------
# Validation requirement — fleet operands steer the action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["vehicle_id", "driver_id", "depot_id"])
def test_fleet_operands_require_validation(role: str) -> None:
    assert requirement_for(role) is ValidationRequirement.REQUIRED


def test_descriptive_arguments_stay_optional() -> None:
    """The anti-constant-blocker: UNKNOWN+OPTIONAL must keep its lane open."""
    assert requirement_for("make") is ValidationRequirement.OPTIONAL


# ---------------------------------------------------------------------------
# Wiring — the declared binding reaches the plan
# ---------------------------------------------------------------------------

def test_declared_validator_surfaces_as_the_resolver() -> None:
    """Name-derivation cannot map get_vehicle to vehicle_id; the binding can."""
    validators = ValidatorRegistry((_validator(),)).scoped(TENANT)
    obs = build_full_observation(
        _episode(), fleetops_registry(), UNCOVERED, validators=validators
    )
    assert "vehicle_id" in obs.unvalidated_required_arguments
    assert obs.argument_resolver_tools == ("get_vehicle",)


def test_unknown_required_without_validator_has_no_resolver() -> None:
    obs = build_full_observation(_episode(), fleetops_registry(), UNCOVERED)
    assert "vehicle_id" in obs.unvalidated_required_arguments
    assert obs.argument_resolver_tools == ()


def test_unknown_optional_does_not_route_to_verify() -> None:
    """A read whose only arguments are OPTIONAL must stay autonomous under
    UNKNOWN — routing it to VERIFY would rebuild the §21 constant blocker."""
    from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature

    registry = ToolRegistry(
        {
            "search_vehicles": ToolSignature(
                name="search_vehicles", required_params=("make",), effect="read"
            )
        }
    )
    episode = RoutingEpisode(
        id="tau2:fleetops:t:opt",
        source_dataset="tau2",
        source_commit="test",
        cluster_id="tau2:fleetops:t:opt",
        user_task="Find Volvo trucks in the fleet.",
        available_tools=("search_vehicles",),
        untrusted_context=None,
        proposed_tool_name="search_vehicles",
        proposed_tool_args={"make": "Volvo"},
        domain="fleetops",
        notes=("mutation:identity",),
    )
    obs = build_full_observation(episode, registry, UNCOVERED)
    assert obs.unvalidated_required_arguments == ()
    report = ENGINE.decide(obs)
    assert report.action is DecisionAction.ACCEPT


# ---------------------------------------------------------------------------
# validate_and_reenter — tri-state outcome, bounded authority
# ---------------------------------------------------------------------------

def _observation(episode: RoutingEpisode | None = None):
    validators = ValidatorRegistry((_validator(),)).scoped(TENANT)
    return build_full_observation(
        episode or _episode(), fleetops_registry(), UNCOVERED, validators=validators
    )


def test_initial_decision_is_verify_with_a_validation_plan() -> None:
    report = ENGINE.decide(_observation())
    assert report.action is DecisionAction.VERIFY
    assert report.resolution_plan is not None
    assert report.resolution_plan.source_tools == ("get_vehicle",)


def test_existing_value_completes_to_accept_on_reentry() -> None:
    outcome = validate_and_reenter(
        _observation(), ENGINE, validator=lambda tool, arg: True
    )
    assert outcome.initial_report.action is DecisionAction.VERIFY
    assert outcome.final_report.action is DecisionAction.ACCEPT
    assert outcome.provenance == {"vehicle_id": "get_vehicle"}


def test_absent_value_is_blocked_not_retried() -> None:
    outcome = validate_and_reenter(
        _observation(), ENGINE, validator=lambda tool, arg: False
    )
    assert outcome.final_report.action is not DecisionAction.ACCEPT


def test_unknown_verdict_abstains() -> None:
    """A validation that cannot happen is not promised."""
    outcome = validate_and_reenter(
        _observation(), ENGINE, validator=lambda tool, arg: None
    )
    assert outcome.final_report.action is DecisionAction.ABSTAIN


def test_validator_error_is_contained_and_abstains() -> None:
    def broken(tool: str, arg: str):
        raise ConnectionError("registry unreachable")

    outcome = validate_and_reenter(_observation(), ENGINE, validator=broken)
    assert outcome.final_report.action is DecisionAction.ABSTAIN
    assert outcome.violation is not None


def test_a_write_does_not_become_autonomous_after_validation() -> None:
    """Validated evidence unlocks read autonomy, never write autonomy."""
    episode = _episode(tool="assign_driver", args={"work_order_id": "WO-00001", "driver_id": "D-0001"})
    validators = ValidatorRegistry(
        (
            _validator(argument_role="driver_id", tool="get_driver", input_argument="driver_id"),
            _validator(argument_role="work_order_id", tool="get_work_order", input_argument="work_order_id"),
        )
    ).scoped(TENANT)
    obs = build_full_observation(
        episode, fleetops_registry(), UNCOVERED, validators=validators
    )
    outcome = validate_and_reenter(obs, ENGINE, validator=lambda tool, arg: True)
    assert outcome.final_report.action is not DecisionAction.ACCEPT
    assert outcome.violation is None


def test_two_facts_fit_within_a_one_attempt_budget() -> None:
    """The attempt budget is per fact, not per plan.

    A two-argument read validated once per argument must complete without a
    budget violation; counting attempts across the plan turned every
    multi-argument call into a spurious ResolutionExhausted.
    """
    from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature

    registry = ToolRegistry(
        {
            "get_assignment": ToolSignature(
                name="get_assignment",
                required_params=("work_order_id", "driver_id"),
                effect="read",
            )
        }
    )
    episode = RoutingEpisode(
        id="tau2:fleetops:t:two",
        source_dataset="tau2",
        source_commit="test",
        cluster_id="tau2:fleetops:t:two",
        user_task="Look up the assignment for WO-00001 and D-0001.",
        available_tools=("get_assignment",),
        untrusted_context=None,
        proposed_tool_name="get_assignment",
        proposed_tool_args={"work_order_id": "WO-00001", "driver_id": "D-0001"},
        domain="fleetops",
        notes=("mutation:identity",),
    )
    validators = ValidatorRegistry(
        (
            _validator(argument_role="driver_id", tool="get_driver", input_argument="driver_id"),
            _validator(argument_role="work_order_id", tool="get_work_order", input_argument="work_order_id"),
        )
    ).scoped(TENANT)
    obs = build_full_observation(episode, registry, UNCOVERED, validators=validators)
    outcome = validate_and_reenter(obs, ENGINE, validator=lambda tool, arg: True)
    assert outcome.violation is None
    assert outcome.provenance == {
        "work_order_id": "get_work_order",
        "driver_id": "get_driver",
    }
    assert outcome.final_report.action is DecisionAction.ACCEPT
