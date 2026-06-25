"""Tool-call stress replay benchmark for thousands of policy decisions.

Purpose
-------
Measure how REMORA and baseline gates behave under large replay volumes
(1k-100k synthetic tool-call decisions) using the v3 benchmark task schema.

Example
-------
python experiments/toolcall_stress_replay.py --n-calls 10000 --seed 7

Outputs:
- results/toolcall_stress_replay_10000.json
- Console summary with safety/utility/throughput metrics
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import random
import time
from typing import Any

from remora.toolcall.baselines_v3 import all_v3_baselines
from remora.toolcall.benchmark_v3 import load_v3_tasks
from remora.toolcall.scoring_v3 import aggregate_v3_metrics, score_v3_outcome
from remora.toolcall.schema_v3 import ToolCallTaskV3

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"


def build_stress_tasks(n_calls: int, seed: int = 42) -> list[ToolCallTaskV3]:
    """Create a replay corpus with `n_calls` tasks by resampling v3 tasks.

    We sample with replacement across all layers and assign unique IDs so the
    scoring pipeline remains transparent for large-scale replay experiments.
    """
    if n_calls < 1:
        raise ValueError("n_calls must be >= 1")

    tasks_by_layer = load_v3_tasks()
    source = [t for layer_tasks in tasks_by_layer.values() for t in layer_tasks]
    rng = random.Random(seed)

    out: list[ToolCallTaskV3] = []
    for i in range(n_calls):
        t = rng.choice(source)
        out.append(replace(t, id=f"stress_{i:07d}_{t.id}"))
    return out


def _extra_metrics(tasks: list[ToolCallTaskV3], outcomes: list[Any]) -> dict[str, float | int]:
    """Add governance-facing metrics not in aggregate_v3_metrics."""
    n = len(tasks)
    if n == 0:
        return {
            "human_review_burden_pct": 0.0,
            "critical_actions": 0,
            "critical_unsafe_execute": 0,
            "critical_false_accept_rate": 0.0,
            "missing_evidence_proxy_count": 0,
        }

    # In v3 policy space, VERIFY/ESCALATE implies human review burden proxy.
    review = sum(1 for o in outcomes if o.result.decision in {"VERIFY", "ESCALATE"})

    critical_tasks = [t for t in tasks if t.severity == "critical"]
    critical_ids = {t.id for t in critical_tasks}
    critical_unsafe = sum(
        1
        for o in outcomes
        if o.task_id in critical_ids and o.result.decision == "EXECUTE" and o.unsafe_execution
    )

    # Evidence proxy: in v3 this corresponds to decisions that defer execution.
    missing_evidence_proxy = sum(
        1 for o in outcomes if o.result.decision in {"VERIFY", "ABSTAIN", "ESCALATE"}
    )

    return {
        "human_review_burden_pct": round((review / n) * 100.0, 2),
        "critical_actions": len(critical_tasks),
        "critical_unsafe_execute": critical_unsafe,
        "critical_false_accept_rate": (
            round((critical_unsafe / len(critical_tasks)) * 100.0, 4)
            if critical_tasks
            else 0.0
        ),
        "missing_evidence_proxy_count": missing_evidence_proxy,
    }


def run_stress_evaluation(n_calls: int = 10000, seed: int = 42) -> dict[str, Any]:
    """Run stress replay across all v3 baselines and return a results payload."""
    tasks = build_stress_tasks(n_calls=n_calls, seed=seed)
    baselines = all_v3_baselines()

    results: dict[str, Any] = {
        "benchmark": "toolcall_stress_replay_v1",
        "n_calls": n_calls,
        "seed": seed,
        "baselines": {},
    }

    for baseline in baselines:
        t0 = time.perf_counter()
        outcomes = [score_v3_outcome(t, baseline.decide(t)) for t in tasks]
        elapsed = time.perf_counter() - t0

        agg = aggregate_v3_metrics(tasks, outcomes)
        extra = _extra_metrics(tasks, outcomes)

        results["baselines"][baseline.name] = {
            "metrics": agg,
            "governance_metrics": extra,
            "performance": {
                "elapsed_seconds": round(elapsed, 4),
                "decisions_per_second": round(n_calls / max(elapsed, 1e-9), 2),
                "mean_decision_ms": round((elapsed * 1000.0) / n_calls, 4),
            },
        }

    # Delta block focused on REMORA vs naive caller
    remora = results["baselines"].get("remora_full_policy_gate_v3", {})
    naive = results["baselines"].get("naive_tool_caller", {})
    if remora and naive:
        r_m = remora["metrics"]
        n_m = naive["metrics"]
        r_g = remora["governance_metrics"]
        n_g = naive["governance_metrics"]
        results["delta_vs_naive"] = {
            "unsafe_execution_rate_delta": round(
                r_m["unsafe_execution_rate"] - n_m["unsafe_execution_rate"], 6
            ),
            "mean_utility_delta": round(r_m["mean_utility"] - n_m["mean_utility"], 6),
            "human_review_burden_pct_delta": round(
                r_g["human_review_burden_pct"] - n_g["human_review_burden_pct"], 3
            ),
            "critical_false_accept_rate_delta": round(
                r_g["critical_false_accept_rate"] - n_g["critical_false_accept_rate"], 6
            ),
        }

    return results


def _print_summary(payload: dict[str, Any]) -> None:
    print("Tool-Call Stress Replay Summary")
    print(f"n_calls: {payload['n_calls']}")
    print(f"seed: {payload['seed']}")
    print()
    print(f"{'Baseline':<30} {'Unsafe%':>10} {'Utility':>10} {'Review%':>10} {'d/s':>12}")
    print("-" * 78)

    for name, b in payload["baselines"].items():
        m = b["metrics"]
        g = b["governance_metrics"]
        p = b["performance"]
        print(
            f"{name:<30} "
            f"{m['unsafe_execution_rate']*100:>9.2f} "
            f"{m['mean_utility']:>10.3f} "
            f"{g['human_review_burden_pct']:>10.2f} "
            f"{p['decisions_per_second']:>12.1f}"
        )

    delta = payload.get("delta_vs_naive")
    if delta:
        print("\nDelta vs naive_tool_caller:")
        print(json.dumps(delta, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run tool-call stress replay benchmark")
    parser.add_argument("--n-calls", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None, help="Optional explicit output path")
    args = parser.parse_args()

    payload = run_stress_evaluation(n_calls=args.n_calls, seed=args.seed)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"toolcall_stress_replay_{args.n_calls}.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    print(f"Results: {out_path}")
    _print_summary(payload)


if __name__ == "__main__":
    main()
