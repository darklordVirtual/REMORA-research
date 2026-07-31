# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the pre-registered validator-resolution study (§33).

**Openly non-blind.** Mechanism study in the empty-index regime: no bulk
export, no closed-world declaration possible, every value verdict UNKNOWN.
Measures whether declared point-lookup validators recover read utility
without opening a single unsafe path. Targets were pre-registered in
external review before the study module first ran.

Usage:
    python scripts/run_fleetops_validator_study.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.toolcall.routing.validator_study import (  # noqa: E402
    TARGETS,
    build_study,
    run_study,
)

WORK_DIR = REPO_ROOT / ".cache" / "routing_bench" / "fleetops_validator_study"
OUT = REPO_ROOT / "results" / "fleetops_validator_study_results.json"


def main() -> int:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout.strip()

    result = run_study(build_study(WORK_DIR))

    for arm_name, metrics in result["arms"].items():
        print(f"== {arm_name}")
        for name in TARGETS:
            v = metrics[name]
            print(f"  {name:34} {v['n']}/{v['d']} = {v['rate']:.3f}")

    verdicts = result["arms"]["with_validators"]["targets"]
    all_met = all(v["met"] for v in verdicts.values())
    misses = [k for k, v in verdicts.items() if not v["met"]]
    if misses:
        print(f"TARGETS MISSED: {', '.join(misses)}")

    report = {
        "schema": "fleetops_validator_study_results_v1",
        "status": "mechanism_study_not_blind",
        "run_at_commit": commit,
        "preregistered_targets": {k: f"{op} {v}" for k, (op, v) in TARGETS.items()},
        "all_targets_met": all_met,
        **result,
        "caveat": (
            "Open (non-blind) mechanism study on the generated fleetops domain "
            "in the empty-index regime. The study's validator consults the "
            "live world directly, so false_absent_on_valid is 0 by "
            "construction; a production validator must be held to that check "
            "separately. Not evidence of generalisation to external domains."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"\nALL PRE-REGISTERED TARGETS MET: {all_met}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
