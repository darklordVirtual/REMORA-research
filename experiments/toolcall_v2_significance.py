from __future__ import annotations

import json
from pathlib import Path
from random import Random
from typing import Any

from remora.toolcall.baselines import all_baselines
from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_significance.json"


def _bootstrap_mean_ci(
    values: list[float], *, n_boot: int = 5000, seed: int = 0
) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0}
    rng = Random(seed)
    n = len(values)
    samples: list[float] = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += values[rng.randrange(n)]
        samples.append(s / n)
    samples.sort()
    lo = samples[int(0.025 * n_boot)]
    hi = samples[int(0.975 * n_boot)]
    mean = sum(values) / n
    return {"mean": mean, "ci95_lo": lo, "ci95_hi": hi}


def _permutation_pvalue_one_sided(
    deltas: list[float], *, n_perm: int = 10000, seed: int = 0
) -> float:
    """One-sided paired sign-flip permutation p-value for mean(delta) > 0."""
    if not deltas:
        return 1.0
    rng = Random(seed)
    obs = sum(deltas) / len(deltas)
    if obs <= 0.0:
        return 1.0
    extreme = 0
    for _ in range(n_perm):
        s = 0.0
        for d in deltas:
            s += d if rng.random() < 0.5 else -d
        if (s / len(deltas)) >= obs:
            extreme += 1
    # add-one smoothing
    return (extreme + 1) / (n_perm + 1)


def run() -> dict[str, Any]:
    tasks = load_benchmark_v2()
    outcomes = {
        baseline.name: [simulate(task, baseline.decide(task)) for task in tasks]
        for baseline in all_baselines()
    }
    remora = outcomes["remora_full_policy_gate"]
    remora_unsafe = [1.0 if o.unsafe_execution else 0.0 for o in remora]
    remora_utility = [o.utility_score for o in remora]

    comparisons: dict[str, Any] = {}
    for name, baseline_outcomes in outcomes.items():
        if name == "remora_full_policy_gate":
            continue
        b_unsafe = [1.0 if o.unsafe_execution else 0.0 for o in baseline_outcomes]
        b_utility = [o.utility_score for o in baseline_outcomes]

        unsafe_delta = [bu - ru for bu, ru in zip(b_unsafe, remora_unsafe, strict=True)]
        utility_delta = [ru - bu for ru, bu in zip(remora_utility, b_utility, strict=True)]

        unsafe_ci = _bootstrap_mean_ci(unsafe_delta, n_boot=5000, seed=7)
        utility_ci = _bootstrap_mean_ci(utility_delta, n_boot=5000, seed=11)
        p_unsafe = _permutation_pvalue_one_sided(unsafe_delta, n_perm=10000, seed=17)
        p_utility = _permutation_pvalue_one_sided(utility_delta, n_perm=10000, seed=19)

        comparisons[name] = {
            "unsafe_execution_rate_delta_baseline_minus_remora": unsafe_ci["mean"],
            "unsafe_rate_delta_ci95": [unsafe_ci["ci95_lo"], unsafe_ci["ci95_hi"]],
            "unsafe_rate_delta_pvalue_one_sided": p_unsafe,
            "utility_delta_remora_minus_baseline": utility_ci["mean"],
            "utility_delta_ci95": [utility_ci["ci95_lo"], utility_ci["ci95_hi"]],
            "utility_delta_pvalue_one_sided": p_utility,
        }

    return {
        "benchmark": "toolcall_benchmark_v2",
        "n_tasks": len(tasks),
        "comparison_target": "remora_full_policy_gate",
        "method": {
            "unsafe_delta": "paired bootstrap mean CI + sign-flip permutation p-value",
            "utility_delta": "paired bootstrap mean CI + sign-flip permutation p-value",
            "n_bootstrap": 5000,
            "n_permutations": 10000,
        },
        "comparisons": comparisons,
        "limitations": [
            "Inference is benchmark-scoped and assumes tasks are exchangeable samples from this synthetic benchmark.",
            "No live LLM trajectories or production tool calls are included.",
            "Synthetic templates may induce optimistic or pessimistic bias for specific gating heuristics.",
        ],
    }


def main() -> None:
    result = run()
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {RESULT_PATH}")
    for name, comp in result["comparisons"].items():
        print(
            f"{name}: unsafe_delta={comp['unsafe_execution_rate_delta_baseline_minus_remora']:.4f} "
            f"p={comp['unsafe_rate_delta_pvalue_one_sided']:.2e} "
            f"utility_delta={comp['utility_delta_remora_minus_baseline']:.4f}"
        )


if __name__ == "__main__":
    main()
