# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Generate the fleetops white-box domain — a closed-world Track A substrate.

Thin wrapper: the generator lives in
``remora.toolcall.routing.sources.fleetops`` so the degradation study derives
its conditions from the same code that built the sealed Track A2 set.
``tests/test_fleetops_domain.py`` pins the output byte-for-byte against the
snapshot hash in the A2 manifest.

Usage:
    python scripts/build_fleetops_domain.py
"""
from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.toolcall.routing.sources.fleetops import (  # noqa: E402
    N_DEPOTS,
    N_DRIVERS,
    N_VEHICLES,
    N_WORK_ORDERS,
    SEED,
    _TOOLS,
    build_database,
    build_tasks,
    canonical_json_bytes,
    serialize_snapshot,
)

DB_OUT = REPO_ROOT / ".cache" / "routing_bench" / "tau2_db" / "fleetops.json"
TASKS_OUT = REPO_ROOT / ".cache" / "routing_bench" / "fleetops" / "fleetops" / "tasks.json"


def main() -> int:
    rng = random.Random(SEED)
    db = build_database(rng)
    tasks = build_tasks(db, rng)

    DB_OUT.parent.mkdir(parents=True, exist_ok=True)
    TASKS_OUT.parent.mkdir(parents=True, exist_ok=True)
    DB_OUT.write_bytes(serialize_snapshot(db))
    TASKS_OUT.write_bytes(canonical_json_bytes(tasks))
    digest = hashlib.sha256(DB_OUT.read_bytes()).hexdigest()
    print(
        f"database: {N_VEHICLES} vehicles, {N_DRIVERS} drivers, "
        f"{N_WORK_ORDERS} work orders, {N_DEPOTS} depots"
    )
    print(f"tasks:    {len(tasks)} clusters over {len(_TOOLS)} tools")
    print(f"db sha256: {digest}")
    print(f"wrote {DB_OUT}")
    print(f"wrote {TASKS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
