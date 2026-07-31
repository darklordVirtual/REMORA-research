# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One comprehensive demonstration run of the routing system, one artifact.

Re-executes every committed study against current HEAD and aggregates the
verdicts, so a single file answers "does the system work right now":

1. fleetops degradation map (7 conditions, pre-registered expectations)
2. fleetops validator study (2 arms, 8 pre-registered targets)
3. BFCL foreign-call measurement, post-grounding, on the spent blind set —
   openly a development measurement; the blind record remains §34

Positive results live here and in README; negative findings stay first-class
in NEGATIVE_RESULTS.md. Nothing here is blind: the blind records are §26–§28,
§31 and §34, each evaluated once and never rerun.

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

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.degradation import build_conditions, run_condition  # noqa: E402
from remora.toolcall.routing.episode import RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    build_full_observation,
)
from remora.toolcall.routing.sources.bfcl import bfcl_registry  # noqa: E402
from remora.toolcall.routing.validator_study import build_study, run_study  # noqa: E402

WORK = REPO_ROOT / ".cache" / "routing_bench" / "system_demonstration"
BFCL_HOLDOUT = REPO_ROOT / "data" / "routing_bench_bfcl"
BFCL_CACHE = REPO_ROOT / ".cache" / "routing_bench" / "bfcl"
BLIND_ARTIFACT = REPO_ROOT / "results" / "routing_bench_bfcl_results.json"
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


def _bfcl_post_grounding() -> dict:
    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in (BFCL_HOLDOUT / "bfcl_holdout.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    registry = bfcl_registry(
        [
            BFCL_CACHE / "BFCL_v3_live_simple.json",
            BFCL_CACHE / "BFCL_v3_live_irrelevance_sampled.json",
        ]
    )
    state = StateIndex.from_values(set(), scopes=())
    engine = RemoraDecisionEngine(low_consequence_accept=True)

    buckets: dict[str, dict[str, int]] = {}
    for episode in episodes:
        predicted = _ACTION_TO_ROUTE[
            engine.decide(build_full_observation(episode, registry, state)).action
        ]
        suffix = episode.id.rsplit(":", 1)[1]
        key = {
            "substituted": "substituted",
            "irrelevance": "irrelevance",
            "m0": "identity",
            "m1": "obtainable",
            "m2": "unobtainable",
        }.get(suffix, "other")
        buckets.setdefault(key, {}).setdefault(predicted.value, 0)
        buckets[key][predicted.value] += 1

    def rate(key: str, route: str) -> float:
        counts = buckets.get(key, {})
        total = sum(counts.values())
        return counts.get(route, 0) / total if total else 0.0

    blind = json.loads(BLIND_ARTIFACT.read_text(encoding="utf-8"))
    return {
        "note": (
            "development measurement on the spent §34 set; the blind record "
            "stands at 86.8% and is not superseded by this number"
        ),
        "wrong_call_accept_blind_prefix": blind["targets"][
            "known_wrong_call_accept"
        ]["value"],
        "wrong_call_accept_post_grounding": round(rate("substituted", "accept"), 4),
        "identity_accept_post_grounding": round(rate("identity", "accept"), 4),
        "irrelevance_abstain": round(rate("irrelevance", "abstain"), 4),
        "obtainable_verify": round(rate("obtainable", "verify"), 4),
        "unobtainable_abstain": round(rate("unobtainable", "abstain"), 4),
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
    bfcl = _bfcl_post_grounding() if BFCL_CACHE.exists() else {"status": "skipped"}

    report = {
        "schema": "system_demonstration_v1",
        "status": "development_measurement_not_blind",
        "run_at_commit": commit,
        "degradation_study": degradation,
        "validator_study": validator,
        "bfcl_foreign_calls": bfcl,
        "caveat": (
            "Aggregated re-execution of the committed studies at current HEAD. "
            "Blind records (§26–§28, §31, §34) were each evaluated once and are "
            "not superseded by anything here."
        ),
    }
    OUT.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode())

    print(f"degradation:      {degradation['n_conditions']} conditions, "
          f"all expectations met: {degradation['all_expectations_met']}")
    print(f"validator study:  all targets met: {validator['all_targets_met']} "
          f"(read utility {validator['read_utility_without_validators']:.0%} -> "
          f"{validator['read_utility_with_validators']:.0%})")
    if "wrong_call_accept_post_grounding" in bfcl:
        print(f"BFCL foreign:     wrong-call accept "
              f"{bfcl['wrong_call_accept_blind_prefix']:.1%} (blind record) -> "
              f"{bfcl['wrong_call_accept_post_grounding']:.1%} (post-grounding, dev)")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
