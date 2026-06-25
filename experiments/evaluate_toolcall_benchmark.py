from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.toolcall.baselines import all_baselines
from remora.toolcall.benchmark import ARTIFACT_PATH, load_benchmark
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v1_results.json"
SUMMARY_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v1_summary.md"


def run() -> dict[str, Any]:
    tasks = load_benchmark(ARTIFACT_PATH)
    baselines: dict[str, Any] = {}
    for baseline in all_baselines():
        outcomes = [simulate(task, baseline.decide(task)) for task in tasks]
        baselines[baseline.name] = aggregate_metrics(tasks, outcomes)

    result = {
        "benchmark": "toolcall_benchmark_v1",
        "benchmark_artifact": "artifacts/toolcall_benchmark_v1.json",
        "n_tasks": len(tasks),
        "baselines": baselines,
        "primary_metric": "unsafe_execution_rate reduction vs heuristic baselines",
        "limitations": [
            "deterministic simulator benchmark",
            "no live LLM calls",
            "no production tool calls",
            "heuristic baselines only; not real model evaluations",
            "task templates are synthetic and require external validation",
        ],
    }
    return result


def write_summary(result: dict[str, Any]) -> None:
    rows = []
    for name, metrics in result["baselines"].items():
        rows.append(
            "| {name} | {unsafe:.4f} | {utility:.4f} | {acc:.4f} | {crit:.4f} |".format(
                name=name,
                unsafe=metrics["unsafe_execution_rate"],
                utility=metrics["mean_utility"],
                acc=metrics["accuracy"],
                crit=metrics["critical_error_intercept_rate"] or 0.0,
            )
        )
    text = "\n".join(
        [
            "# REMORA Tool-Call Benchmark v1 Summary",
            "",
            f"Tasks: {result['n_tasks']}",
            "",
            "| Baseline | Unsafe execution rate | Mean utility | Accuracy | Critical intercept |",
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
    write_summary(result)
    print(f"Tool-call benchmark tasks: {result['n_tasks']}")
    for name, metrics in result["baselines"].items():
        print(
            f"{name}: unsafe={metrics['unsafe_execution_rate']:.4f} "
            f"utility={metrics['mean_utility']:.4f} accuracy={metrics['accuracy']:.4f}"
        )
    print(f"Results written to {RESULT_PATH}")
    print(f"Summary written to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
