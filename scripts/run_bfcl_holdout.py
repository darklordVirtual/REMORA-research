# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evaluate the sealed BFCL external blind track. Runs once, ever.

Refuses unless the manifest records the code as locked, and flips the
manifest to ``evaluated`` on the way out so a second run cannot present
itself as blind. Whatever comes out is the result: a miss is published
without retuning against this set.

Evaluation configuration (locked): the same pipeline as every prior track —
``build_full_observation`` with the sealed registry, an **empty** state index
(no bulk authority exists for BFCL and none is invented), no validator
bindings, ``RemoraDecisionEngine(low_consequence_accept=True)``.

Usage:
    python scripts/run_bfcl_holdout.py --lock <commit-sha>
    python scripts/run_bfcl_holdout.py --run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.episode import Route, RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    _wilson,
    build_full_observation,
    score_routing,
)
from remora.toolcall.routing.mutations import MutationFamily, family_of  # noqa: E402
from remora.toolcall.routing.tool_registry import ToolRegistry  # noqa: E402

HOLDOUT = REPO_ROOT / "data" / "routing_bench_bfcl"
OUT = REPO_ROOT / "results" / "routing_bench_bfcl_results.json"


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
    manifest["status"] = "locked_never_run"
    _write_manifest(manifest)
    print(f"LOCKED at {commit}. Targets were sealed with the set.")
    return 0


def run() -> int:
    manifest = _manifest()
    if manifest["status"] == "evaluated":
        print("REFUSING: already evaluated; a second run is not blind.", file=sys.stderr)
        return 2
    if manifest["status"] != "locked_never_run":
        print(
            f"REFUSING: status is {manifest['status']!r}; lock the code first.",
            file=sys.stderr,
        )
        return 2

    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in (HOLDOUT / "bfcl_holdout.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    registry = ToolRegistry.from_json_dict(
        json.loads((HOLDOUT / "registry.json").read_text(encoding="utf-8"))
    )
    state = StateIndex.from_values(set(), scopes=())
    engine = RemoraDecisionEngine(low_consequence_accept=True)

    rows = []
    for episode in episodes:
        obs = build_full_observation(episode, registry, state)
        predicted = _ACTION_TO_ROUTE[engine.decide(obs).action]
        rows.append((episode, predicted, obs))

    results = [(e, p) for e, p, _ in rows]
    scored = score_routing(results)

    def family(e: RoutingEpisode) -> str | None:
        f = family_of(e)
        return f.value if f else None

    identity = [(e, p, o) for e, p, o in rows if family(e) == MutationFamily.IDENTITY.value]
    required_unknown = [
        (e, p) for e, p, o in identity if o.unvalidated_required_arguments
    ]
    ru_accepts = sum(1 for _, p in required_unknown if p is Route.ACCEPT)

    optional_lane = [
        (e, p) for e, p, o in identity if not o.unvalidated_required_arguments
    ]
    opt_accepts = sum(1 for _, p in optional_lane if p is Route.ACCEPT)

    substituted = [
        (e, p)
        for e, p, _ in rows
        if e.predicates is not None and e.predicates.call_in_gold_set.value is False
    ]
    sub_accepts = sum(1 for _, p in substituted if p is Route.ACCEPT)

    irrelevance = [(e, p) for e, p, _ in rows if e.id.endswith(":irrelevance")]
    irr_abstains = sum(1 for _, p in irrelevance if p is Route.ABSTAIN)

    def recall(family_name: str, route: Route) -> tuple[int, int]:
        members = [(e, p) for e, p, _ in rows if family(e) == family_name]
        return sum(1 for _, p in members if p is route), len(members)

    obt_n, obt_d = recall(MutationFamily.MISSING_ARG_OBTAINABLE.value, Route.VERIFY)
    unobt_n, unobt_d = recall(MutationFamily.MISSING_ARG_UNOBTAINABLE.value, Route.ABSTAIN)

    metrics = {
        "required_unknown_auto_accept": (ru_accepts, len(required_unknown)),
        "known_wrong_call_accept": (sub_accepts, len(substituted)),
        "irrelevance_abstain_recall": (irr_abstains, len(irrelevance)),
        "obtainable_verify_recall": (obt_n, obt_d),
        "unobtainable_abstain_recall": (unobt_n, unobt_d),
    }

    verdicts = {}
    for name, (op, target) in {
        k: (v[0], v[1]) for k, v in manifest["targets"].items()
    }.items():
        n, d = metrics[name]
        value = n / d if d else 0.0
        lo, hi = _wilson(n, d)
        verdicts[name] = {
            "n": n,
            "d": d,
            "value": round(value, 4),
            "wilson95": [round(lo, 4), round(hi, 4)],
            "target": f"{op} {target}",
            "met": value >= target if op == ">=" else value <= target,
        }

    all_met = all(v["met"] for v in verdicts.values())

    for name, verdict in verdicts.items():
        print(
            f"  {name:32} {verdict['n']}/{verdict['d']} = {verdict['value']:<8}"
            f" {verdict['target']:<8} {'MET' if verdict['met'] else 'MISSED'}"
        )
    opt_rate = opt_accepts / len(optional_lane) if optional_lane else 0.0
    print(
        f"  {'identity_accept_optional_lane':32} {opt_accepts}/{len(optional_lane)}"
        f" = {opt_rate:.4f}  (reported, no target)"
    )
    print(f"\nALL PRE-REGISTERED TARGETS MET: {all_met}")

    by_family: dict[str, dict[str, int]] = {}
    for e, p, _ in rows:
        key = family(e) or ("native:" + e.id.rsplit(":", 1)[1])
        by_family.setdefault(key, {}).setdefault(p.value, 0)
        by_family[key][p.value] += 1

    report = {
        "schema": "routing_bench_bfcl_results_v1",
        "status": "evaluated_once",
        "locked_at_commit": manifest.get("locked_at_commit"),
        "holdout_sha256": manifest["sha256"],
        "n_episodes": len(episodes),
        "n_clusters": scored["effective_n"],
        "routing_accuracy_labelled": scored["routing_accuracy"],
        "routing_accuracy_cluster_wilson_95": scored["routing_accuracy_cluster_wilson_95"],
        "n_labelled": scored["n_labelled"],
        "n_unlabelled": scored["n_unlabelled"],
        "per_route": scored["per_route"],
        "confusion": scored["confusion"],
        "predicted_by_family": by_family,
        "targets": verdicts,
        "identity_accept_optional_lane": {
            "n": opt_accepts,
            "d": len(optional_lane),
            "rate": round(opt_rate, 4),
        },
        "all_targets_met": all_met,
        "caveat": manifest.get(
            "caveat",
            "Evaluated once on sealed external data (BFCL v3 live, Apache-2.0) "
            "with no authority: empty state index, no validator bindings. The "
            "wrong-argument value axis is excluded by admission (no vouchable "
            "state exists). No retuning against this set is permitted; misses "
            "are published as measured.",
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    manifest["status"] = "evaluated"
    manifest["evaluated_all_targets_met"] = all_met
    _write_manifest(manifest)
    print(f"wrote {OUT}")
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
