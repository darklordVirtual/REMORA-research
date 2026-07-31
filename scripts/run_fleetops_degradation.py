# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the fleetops degradation study (§31 follow-up).

**Openly non-blind.** The fleetops blind set was spent in §31; this measures
how the architecture degrades when its precondition breaks, one assumption at
a time. Nothing here may be quoted as generalisation evidence.

Unlike the Track A2 runner — assembled inline and never committed, a
reproducibility gap this script exists to close — every condition, date and
threshold is fixed in ``remora.toolcall.routing.degradation`` and the whole
study reruns deterministically from source.

Usage:
    python scripts/run_fleetops_degradation.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.toolcall.routing.degradation import (  # noqa: E402
    GROWTH_FRACTION,
    MAX_AGE_DAYS,
    REMOVAL_FRACTION,
    STALE_AS_OF,
    STUDY_TODAY,
    build_conditions,
    run_condition,
)
from remora.toolcall.routing.evaluate import _wilson  # noqa: E402

WORK_DIR = REPO_ROOT / ".cache" / "routing_bench" / "fleetops_degradation"
OUT = REPO_ROOT / "results" / "fleetops_degradation_results.json"

_HEADLINE = ("identity_accept", "wrong_arg_accept", "false_unsupported_on_valid")


def main() -> int:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout.strip()

    conditions = build_conditions(WORK_DIR)
    evaluated = []
    for cond in conditions:
        metrics = run_condition(cond)
        for name in _HEADLINE:
            lo, hi = _wilson(metrics[name]["n"], metrics[name]["d"])
            metrics[name]["wilson95"] = [round(lo, 4), round(hi, 4)]
        evaluated.append(metrics)

        head = "  ".join(
            f"{name}={metrics[name]['n']}/{metrics[name]['d']}"
            f"={metrics[name]['rate']:.3f}"
            for name in _HEADLINE
        )
        misses = [k for k, v in metrics["expectations"].items() if not v["met"]]
        print(f"{metrics['name']:22} {head}  admission={metrics['admission']['status']}")
        if misses:
            print(f"{'':22} EXPECTATION MISSED: {', '.join(misses)}")

    all_met = all(
        v["met"] for m in evaluated for v in m["expectations"].values()
    )
    report = {
        "schema": "fleetops_degradation_results_v2",
        "status": "mechanism_study_not_blind",
        "run_at_commit": commit,
        "study_parameters": {
            "removal_fraction": REMOVAL_FRACTION,
            "growth_fraction": GROWTH_FRACTION,
            "study_today": STUDY_TODAY.isoformat(),
            "stale_as_of": STALE_AS_OF.isoformat(),
            "max_age_days": MAX_AGE_DAYS,
        },
        "all_expectations_met": all_met,
        "conditions": evaluated,
        "caveat": (
            "Open (non-blind) mechanism study on the generated fleetops domain "
            "after its blind budget was spent in §31. Measures how the "
            "architecture degrades when the closed-world precondition breaks; "
            "not evidence of generalisation to external domains."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"\nALL PRE-REGISTERED EXPECTATIONS MET: {all_met}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
