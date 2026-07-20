from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from random import Random
from typing import Any

from remora.toolcall.baselines import all_baselines
from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_significance.json"

# ---------------------------------------------------------------------------
# Effective sample size (2026-07 review finding #2)
#
# The v2 benchmark contains 700 tasks, but they are 70 unique templates
# (7 domains x 10 scenario families) repeated 10x with cosmetic variation
# (a flavor suffix and a variant integer). A deterministic gate decides
# identically on all 10 copies, so tasks are NOT exchangeable samples.
# All inference below therefore resamples at the TEMPLATE CLUSTER level
# (n_clusters = 70), never at the task level.
# ---------------------------------------------------------------------------


def _cluster_key(task: Any) -> tuple[str, str]:
    family = str((task.context or {}).get("scenario_family", "")) or "unknown_family"
    return (task.domain, family)


def _cluster_means(tasks: list[Any], values: list[float]) -> list[float]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for task, value in zip(tasks, values, strict=True):
        grouped[_cluster_key(task)].append(value)
    return [sum(v) / len(v) for _, v in sorted(grouped.items())]


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _cluster_bootstrap_mean_ci(
    cluster_values: list[float], *, n_boot: int = 5000, seed: int = 0
) -> dict[str, float]:
    """Bootstrap over template clusters, not individual (duplicated) tasks."""
    if not cluster_values:
        return {"mean": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0}
    rng = Random(seed)
    n = len(cluster_values)
    samples: list[float] = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += cluster_values[rng.randrange(n)]
        samples.append(s / n)
    samples.sort()
    lo = samples[int(0.025 * n_boot)]
    hi = samples[int(0.975 * n_boot)]
    mean = sum(cluster_values) / n
    return {"mean": mean, "ci95_lo": lo, "ci95_hi": hi}


def _cluster_permutation_pvalue_one_sided(
    cluster_deltas: list[float], *, n_perm: int = 10000, seed: int = 0
) -> float:
    """One-sided sign-flip permutation over cluster-level mean deltas."""
    if not cluster_deltas:
        return 1.0
    rng = Random(seed)
    obs = sum(cluster_deltas) / len(cluster_deltas)
    if obs <= 0.0:
        return 1.0
    extreme = 0
    for _ in range(n_perm):
        s = 0.0
        for d in cluster_deltas:
            s += d if rng.random() < 0.5 else -d
        if (s / len(cluster_deltas)) >= obs:
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

    n_clusters = len({_cluster_key(t) for t in tasks})

    # Headline unsafe-rate CI at cluster level: a cluster counts as unsafe if
    # ANY of its (near-identical) variants produced an unsafe execution.
    unsafe_by_cluster: dict[tuple[str, str], bool] = defaultdict(bool)
    for task, u in zip(tasks, remora_unsafe, strict=True):
        unsafe_by_cluster[_cluster_key(task)] |= bool(u)
    unsafe_clusters = sum(1 for v in unsafe_by_cluster.values() if v)
    ci_lo, ci_hi = wilson_ci(unsafe_clusters, n_clusters)

    comparisons: dict[str, Any] = {}
    for name, baseline_outcomes in outcomes.items():
        if name == "remora_full_policy_gate":
            continue
        b_unsafe = [1.0 if o.unsafe_execution else 0.0 for o in baseline_outcomes]
        b_utility = [o.utility_score for o in baseline_outcomes]

        unsafe_delta = [bu - ru for bu, ru in zip(b_unsafe, remora_unsafe, strict=True)]
        utility_delta = [ru - bu for ru, bu in zip(remora_utility, b_utility, strict=True)]

        unsafe_clusters_delta = _cluster_means(tasks, unsafe_delta)
        utility_clusters_delta = _cluster_means(tasks, utility_delta)

        unsafe_ci = _cluster_bootstrap_mean_ci(unsafe_clusters_delta, n_boot=5000, seed=7)
        utility_ci = _cluster_bootstrap_mean_ci(utility_clusters_delta, n_boot=5000, seed=11)
        p_unsafe = _cluster_permutation_pvalue_one_sided(unsafe_clusters_delta, n_perm=10000, seed=17)
        p_utility = _cluster_permutation_pvalue_one_sided(utility_clusters_delta, n_perm=10000, seed=19)

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
        "n_template_clusters": n_clusters,
        "effective_sample_note": (
            "700 tasks are 70 unique templates x 10 cosmetic variants; a "
            "deterministic gate decides identically within a template, so the "
            "effective sample size is ~70. All CIs and p-values below use "
            "cluster-level (template-level) resampling."
        ),
        "remora_unsafe_rate": {
            "task_level_point_estimate": sum(remora_unsafe) / len(remora_unsafe),
            "unsafe_template_clusters": unsafe_clusters,
            "n_template_clusters": n_clusters,
            "cluster_level_wilson_ci95": [ci_lo, ci_hi],
        },
        "comparison_target": "remora_full_policy_gate",
        "method": {
            "unsafe_delta": "cluster bootstrap mean CI + cluster sign-flip permutation p-value",
            "utility_delta": "cluster bootstrap mean CI + cluster sign-flip permutation p-value",
            "cluster_definition": "domain x scenario_family template (n=70)",
            "n_bootstrap": 5000,
            "n_permutations": 10000,
        },
        "comparisons": comparisons,
        "limitations": [
            "Inference is benchmark-scoped and assumes template clusters are exchangeable samples from this synthetic benchmark.",
            "Effective sample size is the 70 unique templates, not the 700 task instances.",
            "No live LLM trajectories or production tool calls are included.",
            "Synthetic templates may induce optimistic or pessimistic bias for specific gating heuristics.",
            "Platform-fact context values (target_environment, blast_radius, authz_verified, evidence_complete) are simulator-declared.",
        ],
    }


def main() -> None:
    result = run()
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {RESULT_PATH}")
    print(
        f"remora unsafe rate: {result['remora_unsafe_rate']['task_level_point_estimate']:.4f} "
        f"cluster Wilson CI95 {result['remora_unsafe_rate']['cluster_level_wilson_ci95']}"
    )
    for name, comp in result["comparisons"].items():
        print(
            f"{name}: unsafe_delta={comp['unsafe_execution_rate_delta_baseline_minus_remora']:.4f} "
            f"p={comp['unsafe_rate_delta_pvalue_one_sided']:.2e} "
            f"utility_delta={comp['utility_delta_remora_minus_baseline']:.4f}"
        )


if __name__ == "__main__":
    main()
