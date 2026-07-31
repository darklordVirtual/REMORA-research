# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the fleetops white-box domain as a package module.

The generator moved from ``scripts/build_fleetops_domain.py`` into
``remora.toolcall.routing.sources.fleetops`` so the degradation study (§31
follow-up) can derive its conditions from the same code that built the sealed
Track A2 set. The decisive test pins that move: the database built here must
reproduce the exact snapshot hash recorded in the A2 manifest.

The degradation transforms are tested for the properties the study leans on:
determinism, the removal fraction, and disjointness of grown or foreign-tenant
identifier spaces. A transform that silently overlapped identifier spaces
would make cross-tenant rejection unmeasurable.
"""
from __future__ import annotations

import hashlib
import random

from remora.toolcall.routing.sources.fleetops import (
    N_DRIVERS,
    N_VEHICLES,
    N_WORK_ORDERS,
    SEED,
    build_database,
    build_tasks,
    entity_values,
    fleetops_registry,
    grow_database,
    serialize_snapshot,
    truncate_database,
)

#: Snapshot hash sealed in data/routing_bench_trackA2/manifest.json. The lift
#: from script to package must not change a byte of the generated database.
A2_DB_SHA256 = "3cc32d402dfa27b7acfe0b4eaaae69d3cf55e408e7fd75da815d42dd689db665"


def _db() -> dict:
    return build_database(random.Random(SEED))


# ---------------------------------------------------------------------------
# The lift is byte-identical
# ---------------------------------------------------------------------------

def test_database_snapshot_reproduces_the_a2_hash() -> None:
    """The package build must equal the bytes the A2 declarations bind to."""
    digest = hashlib.sha256(serialize_snapshot(_db())).hexdigest()
    assert digest == A2_DB_SHA256


def test_database_is_deterministic_from_seed() -> None:
    assert _db() == _db()


def test_tasks_are_deterministic() -> None:
    rng_a, rng_b = random.Random(SEED), random.Random(SEED)
    assert build_tasks(build_database(rng_a), rng_a) == build_tasks(
        build_database(rng_b), rng_b
    )


def test_tasks_reference_only_database_entities() -> None:
    """No task may reference an entity the database lacks (§29 circularity)."""
    rng = random.Random(SEED)
    db = build_database(rng)
    valid = {v for values in entity_values(db).values() for v in values}
    for task in build_tasks(db, rng):
        for action in task["evaluation_criteria"]["actions"]:
            for value in action["arguments"].values():
                assert value in valid


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_requires_the_argument_roles_each_tool_uses() -> None:
    registry = fleetops_registry()
    expected = {
        "get_vehicle": ("vehicle_id",),
        "get_work_order": ("work_order_id",),
        "get_driver": ("driver_id",),
        "list_depot_vehicles": ("depot_id",),
        "assign_driver": ("work_order_id", "driver_id"),
        "close_work_order": ("work_order_id",),
    }
    assert {
        name: signature.required_params
        for name, signature in registry.signatures.items()
    } == expected


# ---------------------------------------------------------------------------
# entity_values — the live-world ground truth the degradation study scores by
# ---------------------------------------------------------------------------

def test_entity_values_maps_roles_to_identifier_sets() -> None:
    values = entity_values(_db())
    assert set(values) == {"vehicle_id", "driver_id", "work_order_id", "depot_id"}
    assert len(values["vehicle_id"]) == N_VEHICLES
    assert len(values["driver_id"]) == N_DRIVERS
    assert len(values["work_order_id"]) == N_WORK_ORDERS
    assert "V-0001" in values["vehicle_id"]


# ---------------------------------------------------------------------------
# Truncation — the partial-coverage condition
# ---------------------------------------------------------------------------

def test_truncation_removes_the_requested_fraction() -> None:
    truncated = truncate_database(_db(), fraction=0.3, rng=random.Random(1))
    assert len(truncated["vehicles"]) == N_VEHICLES - int(N_VEHICLES * 0.3)
    assert len(truncated["drivers"]) == N_DRIVERS - int(N_DRIVERS * 0.3)
    assert len(truncated["work_orders"]) == N_WORK_ORDERS - int(N_WORK_ORDERS * 0.3)


def test_truncation_is_deterministic() -> None:
    db = _db()
    assert truncate_database(db, fraction=0.3, rng=random.Random(1)) == (
        truncate_database(db, fraction=0.3, rng=random.Random(1))
    )


def test_truncation_keeps_only_original_entities_and_all_depots() -> None:
    db = _db()
    truncated = truncate_database(db, fraction=0.3, rng=random.Random(1))
    original = entity_values(db)
    remaining = entity_values(truncated)
    for role in ("vehicle_id", "driver_id", "work_order_id"):
        assert remaining[role] < original[role]
    assert remaining["depot_id"] == original["depot_id"]


def test_truncation_does_not_mutate_its_input() -> None:
    db = _db()
    before = serialize_snapshot(db)
    truncate_database(db, fraction=0.3, rng=random.Random(1))
    assert serialize_snapshot(db) == before


# ---------------------------------------------------------------------------
# Growth — the stale-snapshot condition
# ---------------------------------------------------------------------------

def test_growth_appends_disjoint_entities() -> None:
    db = _db()
    grown = grow_database(db, rng=random.Random(2), fraction=0.2)
    old, new = entity_values(db), entity_values(grown)
    for role in ("vehicle_id", "driver_id", "work_order_id"):
        assert old[role] < new[role]
        added = new[role] - old[role]
        assert added, role
        assert not added & old[role]


def test_growth_is_deterministic() -> None:
    db = _db()
    assert grow_database(db, rng=random.Random(2), fraction=0.2) == (
        grow_database(db, rng=random.Random(2), fraction=0.2)
    )


def test_growth_does_not_mutate_its_input() -> None:
    db = _db()
    before = serialize_snapshot(db)
    grow_database(db, rng=random.Random(2), fraction=0.2)
    assert serialize_snapshot(db) == before


# ---------------------------------------------------------------------------
# Foreign tenant — the ambiguous-scope condition
# ---------------------------------------------------------------------------

def test_offset_universe_has_disjoint_identifiers() -> None:
    """Tenant B's identifiers must never collide with tenant A's.

    A collision would make cross-tenant rejection unmeasurable: a B identifier
    that also exists in A is simply valid in A, and rejecting it would be
    wrong rather than isolation.
    """
    tenant_a = _db()
    tenant_b = build_database(random.Random(SEED + 1), id_offset=1000)
    a, b = entity_values(tenant_a), entity_values(tenant_b)
    for role in ("vehicle_id", "driver_id", "work_order_id", "depot_id"):
        assert not a[role] & b[role], role


def test_default_offset_is_zero_and_preserves_the_a2_bytes() -> None:
    explicit = build_database(random.Random(SEED), id_offset=0)
    assert hashlib.sha256(serialize_snapshot(explicit)).hexdigest() == A2_DB_SHA256
