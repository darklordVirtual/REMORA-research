# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evaluate the sealed grounding holdout. Runs once, ever.

Refuses to run if status is not ``locked_never_run``. On completion flips
status to ``evaluated`` so a second run cannot present itself as blind.

Pre-registered targets (SAP §36, 2026-07-31):
  wrong_call_accept                      ≤ 20 %
  gold_autonomy                          ≥ 70 %
  coincidental_overlap_wrong_call_accept ≤ 10 %
  write_autonomous_accept                = 0 %
  cross_tenant_accept                    = 0 %

Usage:
    python scripts/run_grounding_holdout.py --lock <commit-sha>
    python scripts/run_grounding_holdout.py --run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.episode import Route, RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    build_full_observation,
)
from remora.toolcall.routing.tool_registry import ToolRegistry  # noqa: E402
from remora.toolcall.routing.validators import ValidatorRegistry  # noqa: E402

HOLDOUT = REPO_ROOT / "data" / "grounding_holdout_v1"
OUT = REPO_ROOT / "results" / "grounding_holdout_v1_results.json"


def _manifest() -> dict:
    return json.loads((HOLDOUT / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(m: dict) -> None:
    (HOLDOUT / "manifest.json").write_bytes(
        (json.dumps(m, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)


def _meets(value: float, op: str, threshold: float) -> bool:
    if op == "<=":
        return value <= threshold
    if op == ">=":
        return value >= threshold
    raise ValueError(f"Unknown operator: {op!r}")


def lock(commit: str) -> int:
    m = _manifest()
    if m["status"] != "sealed_never_run":
        print(f"REFUSING: status is {m['status']!r}", file=sys.stderr)
        return 2
    m["locked_at_commit"] = commit
    m["status"] = "locked_never_run"
    _write_manifest(m)
    print(f"LOCKED at {commit}. Targets sealed.")
    return 0


def run() -> int:
    manifest = _manifest()
    if manifest["status"] == "evaluated":
        print("REFUSING: already evaluated; a second run is not blind.", file=sys.stderr)
        return 2
    if manifest["status"] != "locked_never_run":
        print(
            f"REFUSING: status is {manifest['status']!r}; run --lock <commit> first.",
            file=sys.stderr,
        )
        return 2

    # Integrity check: episode file must match the sealed hash.
    episodes_path = HOLDOUT / "episodes.jsonl"
    actual_sha = _sha256_file(episodes_path)
    sealed_sha = manifest["episodes_sha256"]
    if actual_sha != sealed_sha:
        print(
            f"INTEGRITY FAILURE: episodes.jsonl sha256 mismatch\n"
            f"  sealed:  {sealed_sha}\n"
            f"  actual:  {actual_sha}",
            file=sys.stderr,
        )
        return 2

    # Load episodes — only observable fields are exposed to the gate.
    raw_episodes: list[dict] = [
        json.loads(line) for line in episodes_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # Sealed fields are stripped before building observations; kept for scoring.
    sealed: dict[str, dict[str, Any]] = {
        ep["id"]: {
            "grounding_category": ep["grounding_category"],
            "write_call": ep.get("write_call", False),
            "cross_tenant": ep.get("cross_tenant", False),
            "validator_binding": ep.get("validator_binding"),
            "route": ep.get("route"),
        }
        for ep in raw_episodes
    }

    episodes = [RoutingEpisode.from_json_dict(ep) for ep in raw_episodes]

    # Minimal registry and empty state (no bulk authority — consistent with §34).
    registry = ToolRegistry({})
    state = StateIndex.from_values(set())
    engine = RemoraDecisionEngine(low_consequence_accept=True)

    results: list[tuple[RoutingEpisode, Route]] = []
    per_category: dict[str, list[tuple[RoutingEpisode, Route]]] = defaultdict(list)

    for episode in episodes:
        obs = build_full_observation(episode, registry, state)
        report = engine.decide(obs)
        predicted = _ACTION_TO_ROUTE[report.action]
        results.append((episode, predicted))
        cat = sealed[episode.id]["grounding_category"]
        per_category[cat].append((episode, predicted))

    # ── Primary target scoring ────────────────────────────────────────────────
    wrong_calls = [
        (e, p) for e, p in results
        if e.predicates is not None and e.predicates.call_in_gold_set.value is False
    ]
    coincidental = [
        (e, p) for e, p in results
        if sealed[e.id]["grounding_category"] == "foreign_coincidental"
    ]
    gold = [
        (e, p) for e, p in results
        if sealed[e.id]["grounding_category"] in ("gold_direct", "gold_derived", "validator_grounded")
    ]
    writes = [
        (e, p) for e, p in results
        if sealed[e.id].get("write_call", False)
    ]
    cross_tenant = [
        (e, p) for e, p in results
        if sealed[e.id].get("cross_tenant", False)
    ]

    def _rate(items: list[tuple], predicate) -> tuple[float, int, int]:
        if not items:
            return 0.0, 0, 0
        hits = sum(1 for _, p in items if predicate(p))
        return hits / len(items), hits, len(items)

    wrong_call_accept, wca_n, wca_total = _rate(wrong_calls, lambda p: p is Route.ACCEPT)
    gold_autonomy, ga_n, ga_total = _rate(gold, lambda p: p is Route.ACCEPT)
    coincidental_accept, co_n, co_total = _rate(coincidental, lambda p: p is Route.ACCEPT)
    write_accept, wa_n, wa_total = _rate(writes, lambda p: p is Route.ACCEPT)
    cross_tenant_accept, ct_n, ct_total = _rate(cross_tenant, lambda p: p is Route.ACCEPT)

    targets = manifest["targets"]
    target_results: dict[str, Any] = {}
    all_met = True
    for name, (op, threshold), measured in [
        ("wrong_call_accept", targets["wrong_call_accept"], wrong_call_accept),
        ("gold_autonomy", targets["gold_autonomy"], gold_autonomy),
        ("coincidental_overlap_wrong_call_accept",
         targets["coincidental_overlap_wrong_call_accept"], coincidental_accept),
        ("write_autonomous_accept", targets["write_autonomous_accept"], write_accept),
        ("cross_tenant_accept", targets["cross_tenant_accept"], cross_tenant_accept),
    ]:
        met = _meets(measured, op, threshold)
        all_met = all_met and met
        target_results[name] = {"target": f"{op} {threshold}", "measured": round(measured, 4), "met": met}

    # Per-category breakdown
    category_breakdown: dict[str, Any] = {}
    for cat, items in per_category.items():
        n = len(items)
        accepted = sum(1 for _, p in items if p is Route.ACCEPT)
        verified = sum(1 for _, p in items if p is Route.VERIFY)
        abstained = sum(1 for _, p in items if p is Route.ABSTAIN)
        escalated = sum(1 for _, p in items if p is Route.ESCALATE)
        category_breakdown[cat] = {
            "n": n,
            "accepted": accepted,
            "verified": verified,
            "abstained": abstained,
            "escalated": escalated,
            "accept_rate": round(accepted / n, 4) if n else 0.0,
        }

    output: dict[str, Any] = {
        "schema": "grounding_holdout_v1_results",
        "status": "evaluated",
        "locked_at_commit": manifest["locked_at_commit"],
        "n_episodes": len(results),
        "all_primary_targets_met": all_met,
        "primary_targets": target_results,
        "per_category": category_breakdown,
        "raw_counts": {
            "wrong_calls": {"accepted": wca_n, "total": wca_total},
            "gold": {"accepted": ga_n, "total": ga_total},
            "coincidental": {"accepted": co_n, "total": co_total},
            "writes": {"accepted": wa_n, "total": wa_total},
            "cross_tenant": {"accepted": ct_n, "total": ct_total},
        },
        "caveat": (
            "Synthetic sealed episodes; not independently sourced data. "
            "This is the first sealed track for grounding; interpret per CLAIM-015 caveats. "
            "wrong_tool_all_grounded category measures coincidental-pass boundary — "
            "a high accept rate there is the key open risk."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(output, indent=2) + "\n").encode("utf-8"))

    manifest["status"] = "evaluated"
    manifest["result_sha256"] = _sha256_file(OUT)
    _write_manifest(manifest)

    print(f"Evaluated {len(results)} episodes.")
    print(f"All primary targets met: {all_met}")
    for name, res in target_results.items():
        mark = "✓" if res["met"] else "✗"
        print(f"  {mark} {name}: {res['measured']:.1%} (target {res['target']})")
    print(f"\nResult: {OUT}")
    return 0 if all_met else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", metavar="COMMIT",
                        help="Lock the sealed set at this commit SHA before evaluating.")
    parser.add_argument("--run", action="store_true",
                        help="Run the evaluation (requires status locked_never_run).")
    args = parser.parse_args()
    if args.lock:
        return lock(args.lock)
    if args.run:
        return run()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
