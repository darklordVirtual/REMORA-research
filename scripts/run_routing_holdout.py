# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evaluate the blind held-out routing benchmark. Runs once, ever.

Refuses unless the manifest records the code as locked, and flips the manifest
to ``evaluated`` on the way out so a second run cannot present itself as blind.
Whatever comes out is the result: a miss is published without retuning against
this set.

Usage:
    python scripts/run_routing_holdout.py --lock <commit-sha>   # record the lock
    python scripts/run_routing_holdout.py --run                 # evaluate, once
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.episode import RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    build_full_observation,
    build_observation,
    score_routing,
)
from remora.toolcall.routing.mutations import MutationFamily, family_of  # noqa: E402
from remora.toolcall.routing.tool_registry import (  # noqa: E402
    ToolRegistry,
    extract_from_python,
)

HOLDOUT = REPO_ROOT / "data" / "routing_bench_holdout"
CACHE = REPO_ROOT / ".cache" / "routing_bench"
OUT = REPO_ROOT / "results" / "routing_bench_holdout_results.json"

#: Frozen before the holdout was ever loaded. See HOLDOUT_STATUS.md.
TARGETS: dict[str, tuple[str, float]] = {
    "autonomy_eligible_identity_accept": (">=", 0.70),
    "wrong_argument_accept_rate": ("<=", 0.20),
    "obtainable_verify_recall": (">=", 0.70),
    "unobtainable_abstain_recall": (">=", 0.70),
    "discrimination_gap_pp": (">=", 40.0),
}


def _manifest() -> dict:
    return json.loads((HOLDOUT / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(manifest: dict) -> None:
    (HOLDOUT / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )


def lock(commit: str) -> int:
    manifest = _manifest()
    if manifest["status"] != "sealed_never_run":
        print(f"REFUSING: status is {manifest['status']!r}", file=sys.stderr)
        return 2
    manifest["locked_at_commit"] = commit
    manifest["locked_targets"] = {k: [op, v] for k, (op, v) in TARGETS.items()}
    manifest["status"] = "locked_never_run"
    _write_manifest(manifest)
    print(f"LOCKED at {commit}. Targets frozen: {list(TARGETS)}")
    return 0


def run() -> int:
    manifest = _manifest()
    if manifest["status"] == "evaluated":
        print(
            "REFUSING: this holdout has already been evaluated. A second run is "
            "not blind, and its result would not mean what the first one does.",
            file=sys.stderr,
        )
        return 2
    if manifest["status"] != "locked_never_run":
        print(
            f"REFUSING: status is {manifest['status']!r}. Lock the code first "
            "with --lock <commit-sha>; evaluating before the code is frozen "
            "makes the holdout a development set.",
            file=sys.stderr,
        )
        return 2

    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in (HOLDOUT / "telecom_holdout.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    tool_paths = [
        q
        for root in (CACHE / "toolsandbox" / "tools", CACHE / "tau2_tools")
        if root.exists()
        for q in sorted(root.glob("*.py"))
    ]
    registry = ToolRegistry(extract_from_python(tool_paths))
    state = StateIndex.from_json_files(sorted((CACHE / "tau2_db").glob("*.json")))
    engine = RemoraDecisionEngine(low_consequence_accept=True)

    results = [
        (ep, _ACTION_TO_ROUTE[engine.decide(build_full_observation(ep, registry, state)).action])
        for ep in episodes
    ]
    scored = score_routing(results)

    by_family: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for episode, predicted in results:
        family = family_of(episode)
        if family is not None:
            by_family[family.value][predicted.value] += 1

    def rate(family: MutationFamily, route: str) -> tuple[int, int, float]:
        counter = by_family[family.value]
        total = sum(counter.values())
        return counter[route], total, (counter[route] / total if total else 0.0)

    id_acc_n, id_acc_d, _ = rate(MutationFamily.IDENTITY, "accept")
    eligible = sum(
        1
        for ep, _ in results
        if family_of(ep) is MutationFamily.IDENTITY
        and build_observation(ep, registry).action_type == "read"
    )
    wrong_n, wrong_d, wrong_rate = rate(MutationFamily.WRONG_ARG_VALUE, "accept")
    _, _, obtainable = rate(MutationFamily.MISSING_ARG_OBTAINABLE, "verify")
    _, _, unobtainable = rate(MutationFamily.MISSING_ARG_UNOBTAINABLE, "abstain")
    identity_rate = id_acc_n / id_acc_d if id_acc_d else 0.0

    metrics = {
        "autonomy_eligible_identity_accept": id_acc_n / eligible if eligible else 0.0,
        "wrong_argument_accept_rate": wrong_rate,
        "obtainable_verify_recall": obtainable,
        "unobtainable_abstain_recall": unobtainable,
        "discrimination_gap_pp": 100.0 * (identity_rate - wrong_rate),
    }

    verdicts = {}
    for name, (op, target) in TARGETS.items():
        value = metrics[name]
        verdicts[name] = {
            "value": round(value, 4),
            "target": f"{op} {target}",
            "met": value >= target if op == ">=" else value <= target,
        }

    all_met = all(v["met"] for v in verdicts.values())

    print(f"episodes {len(episodes)}  clusters {scored['effective_n']}")
    print(f"accuracy {scored['routing_accuracy']:.1%}  "
          f"cluster-CI {scored['routing_accuracy_cluster_wilson_95']}\n")
    for name, verdict in verdicts.items():
        print(f"  {name:<38} {verdict['value']:>8}   {verdict['target']:<8} "
              f"{'MET' if verdict['met'] else 'MISSED'}")
    print(f"\nALL TARGETS MET: {all_met}")

    report = {
        "schema": "routing_bench_holdout_results_v1",
        "status": "evaluated_once",
        "locked_at_commit": manifest.get("locked_at_commit"),
        "holdout_sha256": manifest["sha256"],
        "n_episodes": len(episodes),
        "n_clusters": scored["effective_n"],
        "routing_accuracy": scored["routing_accuracy"],
        "routing_accuracy_cluster_wilson_95": scored["routing_accuracy_cluster_wilson_95"],
        "per_route": scored["per_route"],
        "confusion": scored["confusion"],
        "predicted_by_family": {k: dict(v) for k, v in sorted(by_family.items())},
        "targets": verdicts,
        "all_targets_met": all_met,
        "caveat": (
            "Evaluated once on a blind set whose clusters never appeared in "
            "development. No retuning against this set is permitted; a missed "
            "target is published as measured."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest["status"] = "evaluated"
    manifest["evaluated_all_targets_met"] = all_met
    _write_manifest(manifest)
    print(f"\nwrote {OUT}")
    print("Holdout status is now 'evaluated'. It can never serve as a blind set again.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lock", metavar="COMMIT")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if args.lock:
        raise SystemExit(lock(args.lock))
    if args.run:
        raise SystemExit(run())
    ap.error("pass --lock <commit-sha> or --run")


if __name__ == "__main__":
    main()
