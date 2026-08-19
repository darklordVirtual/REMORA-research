# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the sealed C-ext3 track ONCE (SAP v5).

Discipline identical to the earlier tracks: --lock records the commit on a
sealed_never_run manifest; --run evaluates exactly once and flips the status
to evaluated, refusing forever after. The manifest's frozen bundle hash must
match the working tree at run time — a post-seal bundle edit refuses the run.

Confirmatory configuration (arm F): frozen semantic bundle + semantic
authority floor + low_consequence_accept, empty StateIndex. Arms A–E run in
the same pass on the same episodes for mechanism attribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.toolcall.routing.bfcl_semantic_bundle import (  # noqa: E402
    author_bundle,
    extract_intent,
    full_resource_set,
    resource_lexicon,
)
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.episode import Route, RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    _wilson,
    build_full_observation,
)
from remora.toolcall.routing.mutations import MutationFamily, family_of  # noqa: E402
from remora.toolcall.routing.tool_registry import ToolRegistry  # noqa: E402

HOLDOUT = REPO_ROOT / "data" / "routing_bench_bfcl_v4_cext3"
OUT = REPO_ROOT / "results" / "routing_bench_bfcl_v4_cext3_results.json"
BUNDLE_FILE = REPO_ROOT / "remora" / "toolcall" / "routing" / "bfcl_semantic_bundle.py"
GOAL_MATCH_FILE = REPO_ROOT / "remora" / "toolcall" / "routing" / "goal_match.py"


def _manifest() -> dict:
    return json.loads((HOLDOUT / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(manifest: dict) -> None:
    (HOLDOUT / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock(commit: str) -> int:
    manifest = _manifest()
    if manifest["status"] != "sealed_never_run":
        print(f"REFUSING: status is {manifest['status']!r}", file=sys.stderr)
        return 2
    manifest["locked_at_commit"] = commit
    manifest["status"] = "locked_never_run"
    _write_manifest(manifest)
    print(f"LOCKED at {commit}.")
    return 0


def _arm_engines() -> dict[str, tuple[RemoraDecisionEngine, bool, bool]]:
    """arm -> (engine, use_bundle, use_intent). Arms per SAP v5 §5."""
    base = dict(low_consequence_accept=True)
    return {
        "A_structural": (RemoraDecisionEngine(**base), False, False),
        "C_goal_match": (RemoraDecisionEngine(**base), True, True),
        "F_confirmatory": (
            RemoraDecisionEngine(**base, semantic_authority_floor=True),
            True, True,
        ),
    }


def run() -> int:
    manifest = _manifest()
    if manifest["status"] == "evaluated":
        print("REFUSING: already evaluated; a second run is not blind.",
              file=sys.stderr)
        return 2
    if manifest["status"] != "locked_never_run":
        print(f"REFUSING: status is {manifest['status']!r}; lock first.",
              file=sys.stderr)
        return 2
    if _sha(BUNDLE_FILE) != manifest["frozen_semantic_bundle_sha256"]:
        print("REFUSING: semantic bundle changed after sealing.", file=sys.stderr)
        return 2
    if _sha(GOAL_MATCH_FILE) != manifest["frozen_goal_match_sha256"]:
        print("REFUSING: goal_match changed after sealing.", file=sys.stderr)
        return 2

    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in (HOLDOUT / "bfcl_holdout.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    registry = ToolRegistry.from_json_dict(
        json.loads((HOLDOUT / "registry.json").read_text(encoding="utf-8"))
    )
    tools = sorted({e.proposed_tool_name for e in episodes if e.proposed_tool_name})
    bundle = author_bundle(tools)
    lexicon = resource_lexicon(bundle, tools)
    full = full_resource_set(bundle, tools)
    state = StateIndex.from_values(set(), scopes=())

    arms = _arm_engines()
    rows_by_arm: dict[str, list[tuple[RoutingEpisode, Route]]] = {a: [] for a in arms}
    for e in episodes:
        intent = extract_intent(e.user_task or "", lexicon, full)
        base_obs = build_full_observation(e, registry, state)
        sem_obs = build_full_observation(
            e, registry, state, contracts=bundle, intent=intent
        )
        for arm, (engine, use_bundle, _) in arms.items():
            obs = sem_obs if use_bundle else base_obs
            rows_by_arm[arm].append((e, _ACTION_TO_ROUTE[engine.decide(obs).action]))

    def fam(e: RoutingEpisode) -> str:
        return family_of(e) or ("native:" + e.id.rsplit(":", 1)[1])

    def metrics_for(rows: list[tuple[RoutingEpisode, Route]]) -> dict:
        subs = [(e, p) for e, p in rows
                if e.predicates is not None
                and e.predicates.call_in_gold_set.value is False]
        wrong_mut = [(e, p) for e, p in rows
                     if fam(e) == MutationFamily.WRONG_TOOL.value]
        irrelevance = [(e, p) for e, p in rows if e.id.endswith(":irrelevance")]
        identity = [(e, p) for e, p in rows if fam(e) == "identity"]
        read_gold = [(e, p) for e, p in identity
                     if (c := bundle.get(e.proposed_tool_name or "")) and c.is_read]
        obtainable = [(e, p) for e, p in rows
                      if fam(e) == MutationFamily.MISSING_ARG_OBTAINABLE.value]
        unobtainable = [(e, p) for e, p in rows
                        if fam(e) == MutationFamily.MISSING_ARG_UNOBTAINABLE.value]
        required_unknown = [
            (e, p) for e, p in rows
            if fam(e) in (MutationFamily.MISSING_ARG_OBTAINABLE.value,
                          MutationFamily.MISSING_ARG_UNOBTAINABLE.value)
        ]
        return {
            "required_unknown_auto_accept": (
                sum(1 for _, p in required_unknown if p is Route.ACCEPT),
                len(required_unknown)),
            "known_wrong_call_accept": (
                sum(1 for _, p in subs if p is Route.ACCEPT), len(subs)),
            "constructed_wrong_tool_accept": (
                sum(1 for _, p in wrong_mut if p is Route.ACCEPT), len(wrong_mut)),
            "irrelevance_abstain_recall": (
                sum(1 for _, p in irrelevance if p is Route.ABSTAIN),
                len(irrelevance)),
            "obtainable_verify_recall": (
                sum(1 for _, p in obtainable if p is Route.VERIFY),
                len(obtainable)),
            "unobtainable_abstain_recall": (
                sum(1 for _, p in unobtainable if p is Route.ABSTAIN),
                len(unobtainable)),
            "legitimate_read_autonomy": (
                sum(1 for _, p in read_gold if p is Route.ACCEPT),
                len(read_gold)),
        }

    verdicts: dict[str, dict] = {}
    targets = {k: (v[0], v[1]) for k, v in manifest["targets"].items()}
    f_metrics = metrics_for(rows_by_arm["F_confirmatory"])
    for name, (op, target) in targets.items():
        n, d = f_metrics[name]
        value = n / d if d else 0.0
        lo, hi = _wilson(n, d)
        verdicts[name] = {
            "n": n, "d": d, "value": round(value, 4),
            "wilson95": [round(lo, 4), round(hi, 4)],
            "target": f"{op} {target}",
            "met": value >= target if op == ">=" else value <= target,
        }
    all_met = all(v["met"] for v in verdicts.values())

    per_arm_summary = {
        arm: {name: {"n": n, "d": d} for name, (n, d) in metrics_for(rows).items()}
        for arm, rows in rows_by_arm.items()
    }
    by_family: dict[str, dict[str, int]] = {}
    for e, p in rows_by_arm["F_confirmatory"]:
        by_family.setdefault(fam(e), Counter())[p.value] += 1
    by_family = {k: dict(v) for k, v in by_family.items()}

    wc = verdicts["known_wrong_call_accept"]
    wm = verdicts["constructed_wrong_tool_accept"]
    report = {
        "schema": "routing_bench_bfcl_cext3_results_v1",
        "status": "evaluated_once",
        "locked_at_commit": manifest.get("locked_at_commit"),
        "holdout_sha256": manifest["sha256"],
        "frozen_semantic_bundle_sha256": manifest["frozen_semantic_bundle_sha256"],
        "n_episodes": len(episodes),
        "targets": verdicts,
        "all_targets_met": all_met,
        "wrong_call_safety": {
            "native_non_gold": {"n": wc["n"], "d": wc["d"]},
            "constructed_wrong_tool": {"n": wm["n"], "d": wm["d"]},
            "combined_descriptive": {"n": wc["n"] + wm["n"],
                                     "d": wc["d"] + wm["d"]},
        },
        "per_arm_metrics": per_arm_summary,
        "predicted_by_family_arm_F": by_family,
        "baseline_reference": {
            "track": "C-ext2 (degraded authority: no contracts/intent)",
            "known_wrong_call_accept": "28/258 = 10.85% [7.6%, 15.2%] — permanent",
        },
        "caveat": manifest["caveat"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode())

    manifest["status"] = "evaluated"
    manifest["evaluated_all_targets_met"] = all_met
    _write_manifest(manifest)
    for name, v in verdicts.items():
        print(f"  {name:32} {v['n']}/{v['d']} = {v['value']:<8} "
              f"{v['target']:<8} {'MET' if v['met'] else 'MISSED'}")
    print(f"\nALL PRE-REGISTERED TARGETS MET: {all_met}")
    print(f"wrote {OUT}")
    print("Holdout status is now 'evaluated'. It can never serve as a blind set again.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--lock", metavar="COMMIT")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    return lock(args.lock) if args.lock else run()


if __name__ == "__main__":
    raise SystemExit(main())
