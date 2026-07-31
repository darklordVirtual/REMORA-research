# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""fleetops white-box domain — generator, registry, and degradation transforms.

Originally an ad-hoc script; lifted into the package so the degradation study
(§31 follow-up) derives its conditions from the same code that built the sealed
Track A2 set. ``tests/test_fleetops_domain.py`` pins the lift byte-for-byte
against the snapshot hash in the A2 manifest — the declarations in
``data/routing_bench_trackA2/manifest.json`` bind to those exact bytes.

The domain exists because no external dataset could carry an honest
closed-world declaration (§30): here the database *is* the entire entity
universe by construction, so completeness is a fact about the generator.

The degradation transforms deliberately break that fact, one precondition at a
time, so the study can measure the mechanism where production actually lives:

``truncate_database``
    Removes a fraction of the entities. Valid identifiers now point at records
    the snapshot lacks — the partial-coverage condition (§29).

``grow_database``
    Appends new entities the snapshot has never seen. A declaration whose
    bytes still match is now stale — hash binding cannot catch this, only a
    freshness bound can.

``build_database(id_offset=...)``
    A disjoint identifier universe for a second tenant — the ambiguous-scope
    condition, where a value is valid somewhere but not here.
"""
from __future__ import annotations

import json
import random

from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature

#: Fixed so the snapshot hash is reproducible; a declaration binds to bytes.
SEED = 20260731

N_VEHICLES = 120
N_DRIVERS = 80
N_WORK_ORDERS = 200
N_DEPOTS = 6
N_TASK_CLUSTERS = 90

_DEPOT_CITIES = ["oslo", "bergen", "trondheim", "stavanger", "tromso", "kristiansand"]
_MAKES = ["Volvo", "Scania", "MAN", "Mercedes", "DAF"]
_STATUSES = ["open", "assigned", "closed"]

#: (tool, argument roles). Read-only tools first so the identity family has
#: autonomy-eligible episodes; the mutating ones exercise the write path.
_TOOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("get_vehicle", ("vehicle_id",)),
    ("get_work_order", ("work_order_id",)),
    ("get_driver", ("driver_id",)),
    ("list_depot_vehicles", ("depot_id",)),
    ("assign_driver", ("work_order_id", "driver_id")),
    ("close_work_order", ("work_order_id",)),
)

_PHRASING = [
    "Look up {desc} for the dispatcher.",
    "The depot manager needs {desc}.",
    "A customer called about {desc}.",
    "Please handle {desc} before the shift ends.",
]


def _vehicle(index: int, rng: random.Random, depots: list[dict]) -> dict:
    return {
        "vehicle_id": f"V-{index:04d}",
        "make": rng.choice(_MAKES),
        "depot_id": rng.choice(depots)["depot_id"],
        "odometer_km": rng.randrange(1000, 400000),
    }


def _driver(index: int, rng: random.Random, depots: list[dict]) -> dict:
    return {
        "driver_id": f"D-{index:04d}",
        "licence_class": rng.choice(["C", "CE", "D"]),
        "depot_id": rng.choice(depots)["depot_id"],
    }


def _work_order(index: int, rng: random.Random, vehicles: list[dict]) -> dict:
    return {
        "work_order_id": f"WO-{index:05d}",
        "vehicle_id": rng.choice(vehicles)["vehicle_id"],
        "status": rng.choice(_STATUSES),
        "summary": rng.choice(
            ["brake inspection", "tyre change", "annual service", "oil change"]
        ),
    }


def build_database(rng: random.Random, *, id_offset: int = 0) -> dict:
    """Generate the complete entity universe.

    *id_offset* shifts every identifier sequence, producing a universe disjoint
    from the default one — a second tenant. The default of 0 reproduces the
    exact bytes the Track A2 declarations were written against.
    """
    depots = [
        {"depot_id": f"DP-{i:03d}", "city": _DEPOT_CITIES[(i - id_offset) % len(_DEPOT_CITIES)]}
        for i in range(1 + id_offset, N_DEPOTS + 1 + id_offset)
    ]
    vehicles = [
        _vehicle(i, rng, depots) for i in range(1 + id_offset, N_VEHICLES + 1 + id_offset)
    ]
    drivers = [
        _driver(i, rng, depots) for i in range(1 + id_offset, N_DRIVERS + 1 + id_offset)
    ]
    work_orders = [
        _work_order(i, rng, vehicles)
        for i in range(1 + id_offset, N_WORK_ORDERS + 1 + id_offset)
    ]
    return {
        "depots": depots,
        "vehicles": vehicles,
        "drivers": drivers,
        "work_orders": work_orders,
    }


def build_tasks(db: dict, rng: random.Random) -> list[dict]:
    """Draw tasks from the database, so no task can reference a missing entity."""
    pools = {
        "vehicle_id": [v["vehicle_id"] for v in db["vehicles"]],
        "driver_id": [d["driver_id"] for d in db["drivers"]],
        "work_order_id": [w["work_order_id"] for w in db["work_orders"]],
        "depot_id": [d["depot_id"] for d in db["depots"]],
    }
    tasks: list[dict] = []
    for index in range(N_TASK_CLUSTERS):
        tool, roles = _TOOLS[index % len(_TOOLS)]
        arguments = {role: rng.choice(pools[role]) for role in roles}
        desc = f"{tool.replace('_', ' ')} {' '.join(arguments.values())}"
        tasks.append(
            {
                "id": f"fleet-{index:04d}",
                "description": {"purpose": f"Exercise {tool} on real fleet records."},
                "user_scenario": {
                    "instructions": {
                        "domain": "fleetops",
                        "reason_for_call": _PHRASING[index % len(_PHRASING)].format(
                            desc=desc
                        ),
                        "task_instructions": "Use the fleet tools to resolve it.",
                    }
                },
                "evaluation_criteria": {
                    "actions": [
                        {
                            "action_id": f"{index}_0",
                            "name": tool,
                            "arguments": arguments,
                            "info": None,
                        }
                    ],
                    "nl_assertions": [],
                },
            }
        )
    return tasks


def serialize_snapshot(db: dict) -> bytes:
    """The canonical snapshot bytes a coverage declaration binds to."""
    return (json.dumps(db, indent=1, sort_keys=True) + "\n").encode("utf-8")


def entity_values(db: dict) -> dict[str, set[str]]:
    """Identifier sets per argument role — the live-world ground truth."""
    return {
        "vehicle_id": {v["vehicle_id"] for v in db["vehicles"]},
        "driver_id": {d["driver_id"] for d in db["drivers"]},
        "work_order_id": {w["work_order_id"] for w in db["work_orders"]},
        "depot_id": {d["depot_id"] for d in db["depots"]},
    }


def fleetops_registry() -> ToolRegistry:
    """Signatures for the six domain tools, as an integrator would register them."""
    return ToolRegistry(
        {
            name: ToolSignature(name=name, required_params=roles)
            for name, roles in _TOOLS
        }
    )


# ---------------------------------------------------------------------------
# Degradation transforms
# ---------------------------------------------------------------------------

def truncate_database(db: dict, *, fraction: float, rng: random.Random) -> dict:
    """A copy with *fraction* of each entity table removed, depots kept.

    The removed records are the partial-coverage condition: their identifiers
    remain valid in the live world but absent from this snapshot, so a
    closed-world declaration over these bytes is false by exactly *fraction*.
    """
    out = {"depots": list(db["depots"])}
    for table in ("vehicles", "drivers", "work_orders"):
        rows = db[table]
        removed = set(rng.sample(range(len(rows)), int(len(rows) * fraction)))
        out[table] = [row for i, row in enumerate(rows) if i not in removed]
    return out


def grow_database(db: dict, *, fraction: float, rng: random.Random) -> dict:
    """A copy with *fraction* new entities appended — the world after the snapshot.

    Identifier sequences continue past the current maximum, so every added
    identifier is valid in the grown world and absent from the original bytes.
    A declaration over the original snapshot still hash-matches those bytes;
    only its ``as_of`` date betrays that it predates these records.
    """

    def next_index(rows: list[dict], key: str) -> int:
        return max(int(row[key].rsplit("-", 1)[1]) for row in rows) + 1

    depots = list(db["depots"])
    vehicles = list(db["vehicles"])
    start = next_index(vehicles, "vehicle_id")
    vehicles += [
        _vehicle(i, rng, depots)
        for i in range(start, start + int(len(vehicles) * fraction))
    ]
    drivers = list(db["drivers"])
    start = next_index(drivers, "driver_id")
    drivers += [
        _driver(i, rng, depots)
        for i in range(start, start + int(len(drivers) * fraction))
    ]
    work_orders = list(db["work_orders"])
    start = next_index(work_orders, "work_order_id")
    work_orders += [
        _work_order(i, rng, vehicles)
        for i in range(start, start + int(len(work_orders) * fraction))
    ]
    return {
        "depots": depots,
        "vehicles": vehicles,
        "drivers": drivers,
        "work_orders": work_orders,
    }
