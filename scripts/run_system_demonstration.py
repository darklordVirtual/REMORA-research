# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One comprehensive demonstration run of the routing system, one artifact.

Re-executes every committed study against current HEAD and aggregates the
verdicts, so a single file answers "does the system work right now":

1. fleetops degradation map (7 conditions, pre-registered expectations)
2. fleetops validator study (2 arms, 8 pre-registered targets)
3. BFCL v4 sealed external confirmation, read from its immutable one-run
   artifact (the sealed benchmark is not re-executed here)

The development studies are rerun; the sealed BFCL result is only referenced.

Usage:
    python scripts/run_system_demonstration.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.toolcall.routing.degradation import build_conditions, run_condition  # noqa: E402
from remora.toolcall.routing.validator_study import build_study, run_study  # noqa: E402

WORK = REPO_ROOT / ".cache" / "routing_bench" / "system_demonstration"
BFCL_V4_ARTIFACT = REPO_ROOT / "results" / "routing_bench_bfcl_v4_results.json"
OUT = REPO_ROOT / "results" / "system_demonstration_v1.json"


def _degradation() -> dict:
    conditions = [run_condition(c) for c in build_conditions(WORK / "degradation")]
    return {
        "n_conditions": len(conditions),
        "all_expectations_met": all(
            v["met"] for m in conditions for v in m["expectations"].values()
        ),
        "conditions": {
            m["name"]: {
                "identity_accept_read": m["identity_accept_read"]["rate"],
                "wrong_arg_accept": m["wrong_arg_accept"]["rate"],
                "false_unsupported_on_valid": m["false_unsupported_on_valid"]["rate"],
                "admission": m["admission"]["status"],
                "expectations_met": all(v["met"] for v in m["expectations"].values()),
            }
            for m in conditions
        },
    }


def _validator_study() -> dict:
    result = run_study(build_study(WORK / "validator_study"))
    arm = result["arms"]["with_validators"]
    return {
        "all_targets_met": all(v["met"] for v in arm["targets"].values()),
        "targets": arm["targets"],
        "read_utility_without_validators": result["arms"]["without_validators"][
            "valid_id_completion_read"
        ]["rate"],
        "read_utility_with_validators": arm["valid_id_completion_read"]["rate"],
    }


def _bfcl_v4_confirmation() -> dict:
    sealed = json.loads(BFCL_V4_ARTIFACT.read_text(encoding="utf-8"))
    return {
        "status": "sealed_artifact_reference_not_rerun",
        "all_targets_met": sealed["all_targets_met"],
        "n_episodes": sealed["n_episodes"],
        "holdout_sha256": sealed["holdout_sha256"],
        "routing_accuracy_labelled": sealed["routing_accuracy_labelled"],
        "known_wrong_call_accept": sealed["targets"]["known_wrong_call_accept"],
    }


def main() -> int:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout.strip()

    degradation = _degradation()
    validator = _validator_study()
    bfcl = _bfcl_v4_confirmation()

    report = {
        "schema": "system_demonstration_v1",
        "status": "development_rerun_plus_sealed_artifact_reference",
        "run_at_commit": commit,
        "degradation_study": degradation,
        "validator_study": validator,
        "bfcl_foreign_calls": bfcl,
        "caveat": (
            "The degradation and validator studies are development reruns. "
            "The BFCL v4 sealed result is referenced from its immutable artifact "
            "and is not re-executed here."
        ),
    }
    OUT.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode())

    print(f"degradation:      {degradation['n_conditions']} conditions, "
          f"all expectations met: {degradation['all_expectations_met']}")
    print(f"validator study:  all targets met: {validator['all_targets_met']} "
          f"(read utility {validator['read_utility_without_validators']:.0%} -> "
          f"{validator['read_utility_with_validators']:.0%})")
    print(f"BFCL v4 sealed:   all targets met: {bfcl['all_targets_met']} "
          f"(artifact referenced, not rerun)")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
