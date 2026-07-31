# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Deliberate degradation of the fleetops domain (§31 follow-up).

§31 confirmed the value-existence mechanism under ideal conditions: a complete,
declared, fresh, single-tenant snapshot. Production has none of those
guarantees permanently, so this module measures the mechanism in the only
state production actually has — precondition broken — one break at a time.

**This is an open mechanism study, not a blind evaluation.** The fleetops
blind set was spent in §31; every number produced here is a development
measurement of *how the architecture degrades*, and none of it may be quoted
as generalisation evidence.

Each condition breaks exactly one assumption:

====================  ======================================================
baseline              none broken; replicates the A2 configuration (sanity)
truncated_honest      snapshot lost 30% of the world; declaration still binds
                      to the full export, so the hash mismatch drops every
                      scope — the safe direction, measured
truncated_redeclared  a curator falsely re-vouches the truncated export as
                      complete — the damage a wrong declaration does
stale_unbounded       the world grew past a byte-identical snapshot; hash
                      binding cannot catch it and rejects the new records
stale_bounded         same world, with the freshness bound admission refuses
cross_tenant          another tenant's identifiers under this tenant's state
====================  ======================================================

The directional expectations are fixed in ``build_conditions`` before any
evaluation runs; ``run_condition`` publishes every verdict, met or missed.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.toolcall.routing.admission import assess_admission
from remora.toolcall.routing.compatibility import ArgumentValueStatus, StateIndex
from remora.toolcall.routing.coverage_declaration import (
    CoverageDeclaration,
    build_state_index,
)
from remora.toolcall.routing.episode import Route, RoutingEpisode
from remora.toolcall.routing.evaluate import (
    _ACTION_TO_ROUTE,
    build_full_observation,
    build_observation,
)
from remora.toolcall.routing.mutations import MutationFamily, family_of, mutate_episodes
from remora.toolcall.routing.sources.fleetops import (
    SEED,
    build_database,
    build_tasks,
    entity_values,
    fleetops_registry,
    grow_database,
    serialize_snapshot,
    truncate_database,
)
from remora.toolcall.routing.sources.tau2 import Tau2Adapter
from remora.toolcall.routing.tool_registry import ToolRegistry

#: Fraction of each entity table removed for the partial-coverage conditions.
REMOVAL_FRACTION = 0.3
#: Fraction of new entities appended for the stale-snapshot conditions.
GROWTH_FRACTION = 0.2
#: The study's fixed evaluation date. Explicit rather than read from the clock
#: so every admission decision is reproducible.
STUDY_TODAY = date(2026, 7, 31)
#: as_of for declarations authored against the pre-growth snapshot.
STALE_AS_OF = date(2026, 7, 1)
#: Freshness bound for the bounded stale condition; STALE_AS_OF exceeds it.
MAX_AGE_DAYS = 14

_TENANT = "fleetops_fixture"
_ROLES: tuple[tuple[str, str], ...] = (
    ("vehicle_id", "vehicle"),
    ("driver_id", "driver"),
    ("work_order_id", "work_order"),
    ("depot_id", "depot"),
)


@dataclass(frozen=True)
class Expectation:
    """One pre-registered directional expectation over a scored metric."""

    metric: str
    op: str  # ">=" or "<="
    value: float


@dataclass(frozen=True)
class Condition:
    """One degradation condition, fully assembled before any evaluation."""

    name: str
    description: str
    tenant: str
    episodes: tuple[RoutingEpisode, ...]
    registry: ToolRegistry
    state: StateIndex
    #: Identifier sets valid in this runtime's live world — the ground truth
    #: false-UNSUPPORTED is scored against.
    live_values: dict[str, frozenset[str]]
    admission: dict[str, Any]
    expected: tuple[Expectation, ...]


def _declarations(
    snapshot_sha: str, as_of: date, basis: str
) -> tuple[CoverageDeclaration, ...]:
    return tuple(
        CoverageDeclaration(
            domain="fleetops",
            tenant=_TENANT,
            entity_type=entity_type,
            argument_role=role,
            source_snapshot_sha256=snapshot_sha,
            as_of=as_of,
            completeness_basis=basis,
            curator="stian",
        )
        for role, entity_type in _ROLES
    )


def _build_episodes(
    work_dir: Path, name: str, tasks: list[dict], commit: str
) -> tuple[tuple[RoutingEpisode, ...], ToolRegistry]:
    """The exact A2 pipeline: tau2 adapter over generated tasks, then mutants."""
    domain_dir = work_dir / name / "fleetops"
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "tasks.json").write_bytes(serialize_snapshot(tasks))
    adapter = Tau2Adapter(root=work_dir / name, commit=commit)
    registry = fleetops_registry()
    mutants = mutate_episodes(adapter.build_episodes(), registry)
    return tuple(mutants), registry


def _added_only(full: dict, grown: dict) -> dict:
    """The post-snapshot world: entities that exist only after the snapshot.

    Depots are kept whole — they are not grown, and the task generator needs a
    non-empty pool for every role. Tasks drawn from this world therefore
    reference post-snapshot records for every role except ``depot_id``, and the
    snapshot-membership split in the metrics keeps the two apart.
    """
    out = {"depots": list(full["depots"])}
    for table in ("vehicles", "drivers", "work_orders"):
        old = {tuple(sorted(row.items())) for row in full[table]}
        out[table] = [row for row in grown[table] if tuple(sorted(row.items())) not in old]
    return out


def build_conditions(work_dir: Path) -> tuple[Condition, ...]:
    """Assemble all six conditions, deterministically, expectations included."""
    work_dir = Path(work_dir)

    rng = random.Random(SEED)
    full_db = build_database(rng)
    base_tasks = build_tasks(full_db, rng)
    full_sha = hashlib.sha256(serialize_snapshot(full_db)).hexdigest()

    truncated = truncate_database(
        full_db, fraction=REMOVAL_FRACTION, rng=random.Random(SEED + 11)
    )
    truncated_sha = hashlib.sha256(serialize_snapshot(truncated)).hexdigest()
    grown = grow_database(
        full_db, fraction=GROWTH_FRACTION, rng=random.Random(SEED + 12)
    )
    stale_tasks = build_tasks(_added_only(full_db, grown), random.Random(SEED + 14))
    tenant_b = build_database(random.Random(SEED + 1), id_offset=1000)
    tenant_b_tasks = build_tasks(tenant_b, random.Random(SEED + 13))

    live_full = {k: frozenset(v) for k, v in entity_values(full_db).items()}
    live_grown = {k: frozenset(v) for k, v in entity_values(grown).items()}

    def snapshot(name: str, db: dict) -> Path:
        path = work_dir / name / "fleetops.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(serialize_snapshot(db))
        return path

    def condition(
        *,
        name: str,
        description: str,
        tasks: list[dict],
        commit: str,
        db: dict,
        declarations: tuple[CoverageDeclaration, ...],
        live: dict[str, frozenset[str]],
        expected: tuple[Expectation, ...],
        today: date | None = None,
        max_age_days: int | None = None,
    ) -> Condition:
        episodes, registry = _build_episodes(work_dir, name, tasks, commit)
        state = build_state_index(
            declarations,
            {"fleetops": snapshot(name, db)},
            tenant=_TENANT,
            today=today,
            max_age_days=max_age_days,
        )
        return Condition(
            name=name,
            description=description,
            tenant=_TENANT,
            episodes=episodes,
            registry=registry,
            state=state,
            live_values=live,
            admission=assess_admission(list(episodes), state).to_json_dict(),
            expected=expected,
        )

    complete_basis = "generated database is the entire entity universe by construction"
    commit_full = f"fleetops-{full_sha[:12]}"

    return (
        condition(
            name="baseline",
            description="No assumption broken; replicates the A2 configuration. "
            "Openly non-blind sanity anchor for the degraded conditions.",
            tasks=base_tasks,
            commit=commit_full,
            db=full_db,
            declarations=_declarations(full_sha, STUDY_TODAY, complete_basis),
            live=live_full,
            expected=(
                # Autonomy on verified reads; writes are never auto-accepted,
                # even with every argument confirmed against the snapshot.
                Expectation("identity_accept_read", ">=", 0.85),
                Expectation("identity_accept_write", "<=", 0.15),
                Expectation("wrong_arg_accept", "<=", 0.15),
                Expectation("false_unsupported_on_valid", "<=", 0.02),
            ),
        ),
        condition(
            name="truncated_honest",
            description="Snapshot lost 30% of the world; the declaration still "
            "binds to the full export, so the hash mismatch drops every scope. "
            "Expected: negative claims are lost, never inverted.",
            tasks=base_tasks,
            commit=commit_full,
            db=truncated,
            declarations=_declarations(full_sha, STUDY_TODAY, complete_basis),
            live=live_full,
            expected=(Expectation("false_unsupported_on_valid", "<=", 0.0),),
        ),
        condition(
            name="truncated_redeclared",
            description="A curator falsely re-vouches the truncated export as "
            "complete. Expected: valid identifiers rejected at about the "
            "removal fraction — the damage a wrong declaration does.",
            tasks=base_tasks,
            commit=commit_full,
            db=truncated,
            declarations=_declarations(
                truncated_sha,
                STUDY_TODAY,
                "DELIBERATELY FALSE FOR THIS STUDY: truncated export re-vouched "
                "as complete to measure the cost of a wrong declaration",
            ),
            live=live_full,
            expected=(
                Expectation("false_unsupported_on_valid", ">=", 0.15),
                Expectation("wrong_arg_accept", "<=", 0.15),
            ),
        ),
        condition(
            name="stale_unbounded",
            description="The world grew 20% past a byte-identical snapshot; "
            "hash binding admits the declaration and the index rejects every "
            "post-snapshot identifier.",
            tasks=stale_tasks,
            commit=commit_full,
            db=full_db,
            declarations=_declarations(full_sha, STALE_AS_OF, complete_basis),
            live=live_grown,
            expected=(Expectation("false_unsupported_on_valid", ">=", 0.15),),
        ),
        condition(
            name="stale_bounded",
            description="Same stale world; the freshness bound refuses the "
            "aged declaration, degrading every negative to UNKNOWN.",
            tasks=stale_tasks,
            commit=commit_full,
            db=full_db,
            declarations=_declarations(full_sha, STALE_AS_OF, complete_basis),
            live=live_grown,
            today=STUDY_TODAY,
            max_age_days=MAX_AGE_DAYS,
            expected=(Expectation("false_unsupported_on_valid", "<=", 0.0),),
        ),
        condition(
            name="cross_tenant",
            description="Another tenant's identifiers evaluated under this "
            "tenant's state. They are valid somewhere, but not here; accepting "
            "one would breach isolation.",
            tasks=tenant_b_tasks,
            commit=commit_full,
            db=full_db,
            declarations=_declarations(full_sha, STUDY_TODAY, complete_basis),
            live=live_full,
            expected=(Expectation("identity_accept", "<=", 0.0),),
        ),
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _rate(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "d": d, "rate": n / d if d else 0.0}


def score_condition(
    results: Sequence[tuple[RoutingEpisode, Route]],
    state: StateIndex,
    live_values: dict[str, frozenset[str]],
) -> dict[str, Any]:
    """Score one condition's results against the live-world ground truth.

    ``false_unsupported_on_valid`` counts identity-family argument occurrences
    whose value is valid in the live world yet judged UNSUPPORTED — a
    confident rejection of valid work, the §26/§29 failure. A corrupted value
    judged UNSUPPORTED is a correct negative and never counts.

    The snapshot-membership split separates "the mechanism worked" from "the
    snapshot was adequate": under a degraded snapshot the mechanism can be
    correct about the bytes it was given and still wrong about the world.
    """
    identity = [
        (e, p) for e, p in results if family_of(e) is MutationFamily.IDENTITY
    ]
    wrong = [
        (e, p) for e, p in results if family_of(e) is MutationFamily.WRONG_ARG_VALUE
    ]

    false_unsupported = 0
    live_occurrences = 0
    for episode, _ in identity:
        for name, value in episode.proposed_tool_args.items():
            if not isinstance(value, str):
                continue
            if value not in live_values.get(name, frozenset()):
                continue
            live_occurrences += 1
            if (
                state.status(episode.domain, name, value)
                is ArgumentValueStatus.UNSUPPORTED
            ):
                false_unsupported += 1

    def in_snapshot(episode: RoutingEpisode) -> bool:
        return all(
            state.contains(value)
            for value in episode.proposed_tool_args.values()
            if isinstance(value, str)
        )

    present = [(e, p) for e, p in identity if in_snapshot(e)]
    absent = [(e, p) for e, p in identity if not in_snapshot(e)]

    # Autonomy is claimed for reads; writes route to verification. Classified
    # through build_observation so the metric and the engine share one
    # definition of "write" — a second verb list here would drift.
    def is_write(episode: RoutingEpisode) -> bool:
        return build_observation(episode).action_type == "write"

    reads = [(e, p) for e, p in identity if not is_write(e)]
    writes = [(e, p) for e, p in identity if is_write(e)]

    def accepts(pairs: list[tuple[RoutingEpisode, Route]]) -> int:
        return sum(1 for _, p in pairs if p is Route.ACCEPT)

    by_family: dict[str, Counter] = {}
    for episode, predicted in results:
        family = family_of(episode)
        if family is not None:
            by_family.setdefault(family.value, Counter())[predicted.value] += 1

    return {
        "identity_accept": _rate(accepts(identity), len(identity)),
        "identity_accept_read": _rate(accepts(reads), len(reads)),
        "identity_accept_write": _rate(accepts(writes), len(writes)),
        "wrong_arg_accept": _rate(accepts(wrong), len(wrong)),
        "false_unsupported_on_valid": _rate(false_unsupported, live_occurrences),
        "identity_accept_snapshot_present": _rate(accepts(present), len(present)),
        "identity_accept_snapshot_absent": _rate(accepts(absent), len(absent)),
        "predicted_by_family": {
            family: dict(counter) for family, counter in sorted(by_family.items())
        },
    }


def check_expectations(
    metrics: dict[str, Any], expected: tuple[Expectation, ...]
) -> dict[str, Any]:
    """Verdicts for every pre-registered expectation; misses are published."""
    verdicts: dict[str, Any] = {}
    for expectation in expected:
        value = metrics[expectation.metric]["rate"]
        met = (
            value >= expectation.value
            if expectation.op == ">="
            else value <= expectation.value
        )
        verdicts[expectation.metric] = {
            "value": round(value, 4),
            "target": f"{expectation.op} {expectation.value}",
            "met": met,
        }
    return verdicts


def run_condition(
    condition: Condition, engine: RemoraDecisionEngine | None = None
) -> dict[str, Any]:
    """Evaluate one condition through the locked A2 pipeline and score it."""
    engine = engine or RemoraDecisionEngine(low_consequence_accept=True)
    results = [
        (
            episode,
            _ACTION_TO_ROUTE[
                engine.decide(
                    build_full_observation(episode, condition.registry, condition.state)
                ).action
            ],
        )
        for episode in condition.episodes
    ]
    metrics = score_condition(results, condition.state, condition.live_values)
    metrics["name"] = condition.name
    metrics["description"] = condition.description
    metrics["n_episodes"] = len(condition.episodes)
    metrics["admission"] = condition.admission
    metrics["expectations"] = check_expectations(metrics, condition.expected)
    return metrics
