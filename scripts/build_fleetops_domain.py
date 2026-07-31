# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Generate the fleetops white-box domain — a closed-world Track A substrate.

Four blind sets were spent without testing argument discrimination (§26–§29),
each for the same reason: no available domain had an authoritative state table
whose completeness anyone could honestly declare. tau2's telecom state does not
cover the arguments its tasks use; banking's does not either.

This domain is generated rather than borrowed, which is what makes the
completeness claim truthful: the database *is* the entire entity universe by
construction, so a closed-world declaration is a fact about the generator rather
than an assumption about someone else's export.

**The limitation this creates, stated up front.** A synthetic domain with a
perfect state table is the best case for a value-existence check. Passing here
is necessary, not sufficient: it shows the mechanism works when its precondition
holds, and says nothing about domains whose state is partial, stale or
ambiguously scoped. Those are the conditions §26 and §29 measured, and they are
not reproduced here.

Independence properties, each one a failure mode from an earlier section:

* The database is generated first and the tasks are drawn from it, so no task
  can reference an entity the database lacks — task-derived state was the
  circularity risk flagged in review.
* Identifiers are structured (``V-0001``) so a corrupted variant is
  syntactically plausible but genuinely absent, rather than absent for a reason
  the detector could pattern-match.
* Generation is deterministic from a fixed seed and carries no timestamp, so the
  snapshot hash a coverage declaration binds to is reproducible.

Usage:
    python scripts/build_fleetops_domain.py
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_OUT = REPO_ROOT / ".cache" / "routing_bench" / "tau2_db" / "fleetops.json"
TASKS_OUT = REPO_ROOT / ".cache" / "routing_bench" / "fleetops" / "fleetops" / "tasks.json"

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


def build_database(rng: random.Random) -> dict:
    depots = [
        {"depot_id": f"DP-{i:03d}", "city": _DEPOT_CITIES[i % len(_DEPOT_CITIES)]}
        for i in range(1, N_DEPOTS + 1)
    ]
    vehicles = [
        {
            "vehicle_id": f"V-{i:04d}",
            "make": rng.choice(_MAKES),
            "depot_id": rng.choice(depots)["depot_id"],
            "odometer_km": rng.randrange(1000, 400000),
        }
        for i in range(1, N_VEHICLES + 1)
    ]
    drivers = [
        {
            "driver_id": f"D-{i:04d}",
            "licence_class": rng.choice(["C", "CE", "D"]),
            "depot_id": rng.choice(depots)["depot_id"],
        }
        for i in range(1, N_DRIVERS + 1)
    ]
    work_orders = [
        {
            "work_order_id": f"WO-{i:05d}",
            "vehicle_id": rng.choice(vehicles)["vehicle_id"],
            "status": rng.choice(_STATUSES),
            "summary": rng.choice(
                ["brake inspection", "tyre change", "annual service", "oil change"]
            ),
        }
        for i in range(1, N_WORK_ORDERS + 1)
    ]
    return {
        "depots": depots,
        "vehicles": vehicles,
        "drivers": drivers,
        "work_orders": work_orders,
    }


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


def main() -> None:
    rng = random.Random(SEED)
    db = build_database(rng)
    tasks = build_tasks(db, rng)

    DB_OUT.parent.mkdir(parents=True, exist_ok=True)
    TASKS_OUT.parent.mkdir(parents=True, exist_ok=True)
    DB_OUT.write_text(
        json.dumps(db, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    TASKS_OUT.write_text(
        json.dumps(tasks, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = hashlib.sha256(DB_OUT.read_bytes()).hexdigest()
    print(
        f"database: {N_VEHICLES} vehicles, {N_DRIVERS} drivers, "
        f"{N_WORK_ORDERS} work orders, {N_DEPOTS} depots"
    )
    print(f"tasks:    {len(tasks)} clusters over {len(_TOOLS)} tools")
    print(f"db sha256: {digest}")
    print(f"wrote {DB_OUT}")
    print(f"wrote {TASKS_OUT}")


if __name__ == "__main__":
    sys.exit(main())
