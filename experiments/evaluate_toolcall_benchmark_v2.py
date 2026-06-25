from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from remora.toolcall.baselines import all_baselines
from remora.toolcall.benchmark_v2 import ARTIFACT_PATH_V2, load_benchmark_v2
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_results.json"
HEURISTIC_RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_heuristic_results.json"
SUMMARY_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_summary.md"


def _false_accept_count_by_failure_mode(tasks: list[Any], outcomes: list[Any]) -> dict[str, int]:
    by_id = {task.task_id: task for task in tasks}
    counts: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        if not outcome.false_accept:
            continue
        task = by_id[outcome.task_id]
        mode = task.expected_failure_mode or "unknown_failure_mode"
        counts[mode] += 1
    return dict(sorted(counts.items()))


def run() -> dict[str, Any]:
    tasks = load_benchmark_v2(ARTIFACT_PATH_V2)
    baselines: dict[str, Any] = {}
    outcomes_by_baseline: dict[str, list[Any]] = {}
    for baseline in all_baselines():
        outcomes = [simulate(task, baseline.decide(task)) for task in tasks]
        outcomes_by_baseline[baseline.name] = outcomes
        metrics = aggregate_metrics(tasks, outcomes)
        metrics["false_accept_count_by_failure_mode"] = _false_accept_count_by_failure_mode(tasks, outcomes)
        baselines[baseline.name] = metrics

    remora_unsafe = baselines["remora_full_policy_gate"]["unsafe_execution_rate"]
    best_utility = max(m["mean_utility"] for m in baselines.values())
    for name, metrics in baselines.items():
        metrics["unsafe_execution_rate_delta_vs_remora_full_policy_gate"] = (
            metrics["unsafe_execution_rate"] - remora_unsafe
        )
        metrics["utility_delta_vs_best_baseline"] = metrics["mean_utility"] - best_utility
        majority_unsafe = baselines["majority_vote_heuristic"]["unsafe_execution_rate"]
        metrics["unsafe_execution_reduction_vs_majority"] = majority_unsafe - metrics["unsafe_execution_rate"]

    result = {
        "benchmark": "toolcall_benchmark_v2",
        "benchmark_artifact": "artifacts/toolcall_benchmark_v2.json",
        "n_tasks": len(tasks),
        "baselines": baselines,
        "primary_metric": "unsafe_execution_rate reduction vs heuristic baselines",
        "limitations": [
            "deterministic simulator benchmark",
            "no live LLM calls",
            "no production tool calls",
            "heuristic baselines only; not real model evaluations",
            "synthetic adversarial templates require external validation",
        ],
    }
    return result


def write_summary(result: dict[str, Any]) -> None:
    rows = []
    for name, metrics in result["baselines"].items():
        rows.append(
            "| {name} | {unsafe:.4f} | {delta:+.4f} | {utility:.4f} | {acc:.4f} |".format(
                name=name,
                unsafe=metrics["unsafe_execution_rate"],
                delta=metrics["unsafe_execution_rate_delta_vs_remora_full_policy_gate"],
                utility=metrics["mean_utility"],
                acc=metrics["accuracy"],
            )
        )
    text = "\n".join(
        [
            "# REMORA Tool-Call Benchmark v2 Summary",
            "",
            f"Tasks: {result['n_tasks']}",
            "",
            "| Baseline | Unsafe execution rate | Delta vs remora_full_policy_gate | Mean utility | Accuracy |",
            "|---|---:|---:|---:|---:|",
            *rows,
            "",
            "Limitations:",
            *[f"- {item}" for item in result["limitations"]],
            "",
        ]
    )
    SUMMARY_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    result = run()
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    HEURISTIC_RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_summary(result)
    print(f"Tool-call benchmark v2 tasks: {result['n_tasks']}")
    for name, metrics in result["baselines"].items():
        print(
            f"{name}: unsafe={metrics['unsafe_execution_rate']:.4f} "
            f"delta_vs_remora={metrics['unsafe_execution_rate_delta_vs_remora_full_policy_gate']:+.4f} "
            f"utility={metrics['mean_utility']:.4f} accuracy={metrics['accuracy']:.4f}"
        )
    print(f"Results written to {RESULT_PATH}")
    print(f"Heuristic alias written to {HEURISTIC_RESULT_PATH}")
    print(f"Summary written to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
