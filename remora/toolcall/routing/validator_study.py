# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-registered validator-resolution study (§33).

§32 left one measured gap: under UNKNOWN, 50% of corrupted identifiers were
accepted on read-only calls, because nothing bound an argument role to the
tool that can confirm it. This study measures the declarative validator
bindings closing that gap — in the regime production actually has when **no
bulk export exists at all**: an empty state index. Every value verdict is
UNKNOWN, a closed-world declaration is impossible, and the only authority
available is a per-value point lookup against the system of record.

**Openly non-blind mechanism study**, like §32: the fleetops blind budget was
spent in §31. The eight targets below were pre-registered in external review
before this module ran; every verdict is published, met or missed.

Two arms over the same 540 episodes and the same engine:

``without_validators``
    Required-role reads have no resolver. The arm exists to prove the regime
    fails closed: zero autonomous accepts and zero read utility — the honest
    cost the bindings must then recover.

``with_validators``
    The four fleetops roles are bound to their point-lookup tools. VERIFY
    carries a plan, the validator answers exists/absent from the live world,
    and the whole router re-runs on the verdict.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.report import DecisionAction
from remora.policy.resolution import ResolutionOutcome, validate_and_reenter
from remora.toolcall.routing.compatibility import StateIndex
from remora.toolcall.routing.degradation import _build_episodes
from remora.toolcall.routing.episode import RoutingEpisode
from remora.toolcall.routing.evaluate import build_full_observation, build_observation
from remora.toolcall.routing.mutations import MutationFamily, family_of
from remora.toolcall.routing.sources.fleetops import (
    SEED,
    build_database,
    build_tasks,
    entity_values,
    serialize_snapshot,
)
from remora.toolcall.routing.tool_registry import ToolRegistry
from remora.toolcall.routing.validators import ArgumentValidator, ValidatorRegistry

_TENANT = "fleetops_fixture"
_FOREIGN_TENANT = "fleetops_tenant_b"
#: A distinctly named foreign-tenant binding: if it ever appears in a plan,
#: tenant scoping has failed and the metric catches it.
_FOREIGN_TOOL = "b_get_vehicle"

#: role -> validating tool. The declared truth the correct-validator metric
#: scores against.
_BINDINGS: dict[str, str] = {
    "vehicle_id": "get_vehicle",
    "driver_id": "get_driver",
    "work_order_id": "get_work_order",
    "depot_id": "list_depot_vehicles",
}

#: The eight pre-registered targets, fixed in external review before this
#: module first ran. (metric, op, value); ops read as in §32.
TARGETS: dict[str, tuple[str, float]] = {
    "required_unknown_auto_accept": ("<=", 0.0),
    "correct_validator_chosen": (">=", 0.95),
    "valid_id_completion_read": (">=", 0.85),
    "corrupt_id_accept_after_resolver": ("<=", 0.05),
    "write_auto_accept": ("<=", 0.0),
    "false_absent_on_valid": ("<=", 0.0),
    "cross_tenant_validator_use": ("<=", 0.0),
    "attempts_exceeded": ("<=", 0.0),
}


@dataclass(frozen=True)
class Study:
    episodes: tuple[RoutingEpisode, ...]
    registry: ToolRegistry
    #: Empty: the regime under study has no bulk data at all.
    state: StateIndex
    validators: ValidatorRegistry
    #: The system of record point lookups consult — the live world.
    live_values: dict[str, frozenset[str]]


def build_study(work_dir) -> Study:
    rng = random.Random(SEED)
    db = build_database(rng)
    tasks = build_tasks(db, rng)
    sha = __import__("hashlib").sha256(serialize_snapshot(db)).hexdigest()
    episodes, registry = _build_episodes(
        work_dir, "validator_study", tasks, f"fleetops-{sha[:12]}"
    )

    declared = tuple(
        ArgumentValidator(
            argument_role=role,
            tool=tool,
            input_argument=role,
            tenant=_TENANT,
        )
        for role, tool in _BINDINGS.items()
    ) + (
        # The foreign binding that must never be consulted.
        ArgumentValidator(
            argument_role="vehicle_id",
            tool=_FOREIGN_TOOL,
            input_argument="vehicle_id",
            tenant=_FOREIGN_TENANT,
        ),
    )
    return Study(
        episodes=episodes,
        registry=registry,
        state=StateIndex.from_values(set(), scopes=()),
        validators=ValidatorRegistry(declared).scoped(_TENANT),
        live_values={k: frozenset(v) for k, v in entity_values(db).items()},
    )


def _rate(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "d": d, "rate": n / d if d else 0.0}


def _make_validator(
    episode: RoutingEpisode,
    live: dict[str, frozenset[str]],
    consulted: list[str],
    false_absent_on_valid: list[str],
) -> Callable[[str, str], bool | None]:
    """Point lookup against the system of record, instrumented for metrics."""

    def validator(source_tool: str, argument: str) -> bool | None:
        consulted.append(source_tool)
        value = episode.proposed_tool_args.get(argument)
        if not isinstance(value, str):
            return None
        exists = value in live.get(argument, frozenset())
        # A false absent — verdict False on a live-valid value — is impossible
        # here by construction, because the study's validator consults the
        # live world directly. The instrumentation stays anyway: it is the
        # check a production validator would be held to, and the metric being
        # 0 *by construction* is stated in §33 rather than presented as a
        # finding.
        if not exists and isinstance(value, str) and value in live.get(argument, frozenset()):
            false_absent_on_valid.append(argument)
        return exists

    return validator


def _run_arm(study: Study, *, with_validators: bool) -> dict[str, Any]:
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    validators = study.validators if with_validators else None
    declared_tools = frozenset(_BINDINGS.values())

    outcomes: list[tuple[RoutingEpisode, ResolutionOutcome]] = []
    consulted_all: list[str] = []
    false_absent: list[str] = []

    for episode in study.episodes:
        obs = build_full_observation(
            episode, study.registry, study.state, validators=validators
        )
        outcome = validate_and_reenter(
            obs,
            engine,
            validator=_make_validator(
                episode, study.live_values, consulted_all, false_absent
            ),
        )
        outcomes.append((episode, outcome))

    def is_write(episode: RoutingEpisode) -> bool:
        return build_observation(episode, study.registry).action_type == "write"

    identity = [
        (e, o) for e, o in outcomes if family_of(e) is MutationFamily.IDENTITY
    ]
    wrong = [
        (e, o) for e, o in outcomes if family_of(e) is MutationFamily.WRONG_ARG_VALUE
    ]
    id_reads = [(e, o) for e, o in identity if not is_write(e)]
    id_writes = [(e, o) for e, o in identity if is_write(e)]

    def final_accepts(pairs) -> int:
        return sum(
            1 for _, o in pairs if o.final_report.action is DecisionAction.ACCEPT
        )

    # Correct-validator: among initial validation plans, every source tool is
    # the declared binding for one of the episode's argument roles.
    # Carry the plan itself, not the outcome it came from: the filter below
    # establishes that it is present, and re-reading the optional field would
    # discard that.
    planned = [
        o.plan
        for _, o in outcomes
        if o.plan is not None and o.plan.resolver == "argument_validation"
    ]
    correct = sum(
        1
        for plan in planned
        if all(
            tool == _BINDINGS.get(role)
            for role, tool in zip(plan.target_arguments, plan.source_tools)
        )
    )

    initial_accepts = sum(
        1
        for _, o in identity + wrong
        if o.initial_report.action is DecisionAction.ACCEPT
    )
    foreign_consultations = sum(1 for t in consulted_all if t not in declared_tools)
    exhausted = sum(
        1 for _, o in outcomes if o.violation and "max_attempts" in o.violation
    )

    final_by_family: dict[str, Counter] = {}
    for episode, outcome in outcomes:
        family = family_of(episode)
        if family is not None:
            final_by_family.setdefault(family.value, Counter())[
                outcome.final_report.action.value
            ] += 1

    metrics: dict[str, Any] = {
        "required_unknown_auto_accept": _rate(initial_accepts, len(identity + wrong)),
        "correct_validator_chosen": _rate(correct, len(planned)),
        "valid_id_completion_read": _rate(final_accepts(id_reads), len(id_reads)),
        "corrupt_id_accept_after_resolver": _rate(final_accepts(wrong), len(wrong)),
        "write_auto_accept": _rate(final_accepts(id_writes), len(id_writes)),
        "false_absent_on_valid": _rate(len(false_absent), len(consulted_all)),
        "cross_tenant_validator_use": _rate(
            foreign_consultations, len(consulted_all)
        ),
        "attempts_exceeded": _rate(exhausted, len(outcomes)),
        "n_episodes": len(outcomes),
        "n_plans": len(planned),
        "n_validator_consultations": len(consulted_all),
        "final_by_family": {
            family: dict(counter)
            for family, counter in sorted(final_by_family.items())
        },
    }

    if with_validators:
        metrics["targets"] = {
            name: {
                "value": round(metrics[name]["rate"], 4),
                "target": f"{op} {value}",
                "met": (
                    metrics[name]["rate"] >= value
                    if op == ">="
                    else metrics[name]["rate"] <= value
                ),
            }
            for name, (op, value) in TARGETS.items()
        }
    return metrics


def run_study(study: Study) -> dict[str, Any]:
    return {
        "arms": {
            "without_validators": _run_arm(study, with_validators=False),
            "with_validators": _run_arm(study, with_validators=True),
        }
    }
