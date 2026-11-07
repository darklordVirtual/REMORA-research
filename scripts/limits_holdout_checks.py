#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Checks S1 to S3 of plan v4 (docs/assurance/ot_limits_holdout_plan_v4.md §5).

    python scripts/limits_holdout_checks.py SHIFTS.json [...] --policy LIMITS.json \\
        --trusted-key KEY_FILE --out CHECKS.json

Each shift is replayed as scripts/run_limits_holdout.py replays it, and the
guard's own ledger is read afterwards. S1: every write that sets FIC-220 to
exactly 0 runs. S2: every PIC-101 write made while the plant holds FIC-220 at 0
runs and is charged nothing, at reservation or after the fact. S3: every
FIC-220 write whose target lies between the plant's value and 0 runs and is
charged nothing. A failure in any is a defect in the mechanism, not a measure.
This script was written after the v4 run; the checks' definitions were fixed
in the plan before it.
"""
from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_limits_holdout as holdout  # noqa: E402


def _charged(db: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    with sqlite3.connect(db) as conn:
        for op, amount in conn.execute("SELECT operation_id, amount FROM limit_reservation"):
            base = op.split("#", 1)[0]
            out[base] = out.get(base, 0) + int(amount)
    return out


def check(shifts: list[dict[str, Any]], policy) -> dict[str, Any]:
    registry = holdout._registry()
    pristine = copy.deepcopy(registry.PLANT)
    start = Decimal(str(pristine["loops"]["FIC-220"]["setpoint"]))
    found: dict[str, list[dict[str, Any]]] = {"S1": [], "S2": [], "S3": []}
    with tempfile.TemporaryDirectory() as tmp:
        for shift in shifts:
            rows = holdout.replay_shift(shift, policy, registry, pristine, Path(tmp))
            charged = _charged(Path(tmp) / f"{shift['shift_id']}.db")
            fic = start
            for w, row in zip(shift["writes"], rows, strict=True):
                op = f"{shift['shift_id']}:{row['index']:03d}"
                ran = row["outcome"] == "ran"
                entry = {"shift_id": shift["shift_id"], "index": row["index"]}
                if w["tool"] == "adjust_setpoint" and w["args"]["loop"] == "FIC-220":
                    target = Decimal(str(w["args"]["value"]))
                    if target == 0:
                        found["S1"].append({**entry, "ok": ran})
                    elif 0 < target < fic:
                        found["S3"].append({**entry, "ok": ran and charged.get(op, 0) == 0})
                    if ran:
                        fic = target
                elif (w["tool"] == "adjust_setpoint" and w["args"]["loop"] == "PIC-101"
                      and fic == 0):
                    found["S2"].append({**entry, "ok": ran and charged.get(op, 0) == 0})
    return {name: {"writes": len(items), "held": sum(i["ok"] for i in items),
                   "failures": [i for i in items if not i["ok"]]}
            for name, items in found.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("shifts", nargs="+", type=Path)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--trusted-key", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    policy, digest, _ = holdout.load_policy(
        args.policy, args.trusted_key.read_text(encoding="utf-8").split())
    shifts: list[dict[str, Any]] = []
    for path in args.shifts:
        shifts.extend(holdout.validate(json.loads(path.read_text(encoding="utf-8"))))
    result = {"policy_sha256": digest, "checks": check(shifts, policy)}
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, c in result["checks"].items():
        print(f"{name}: {c['held']}/{c['writes']} held")
    return 0 if all(not c["failures"] for c in result["checks"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
