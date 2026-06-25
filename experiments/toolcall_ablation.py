from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.toolcall.benchmark import load_benchmark
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_ablation_results.json"


def run() -> dict[str, Any]:
    tasks = load_benchmark()
    variants = {
        "without_evidence_flags": RemoraToolCallGate(use_evidence_flags=False),
        "with_severity_flags": RemoraToolCallGate(use_evidence_flags=False, use_counterfactual_flags=False, use_contradiction_flags=False),
        "with_counterfactual_flags": RemoraToolCallGate(use_evidence_flags=False, use_contradiction_flags=False),
        "with_contradiction_flags": RemoraToolCallGate(use_evidence_flags=False),
        "full_gate": RemoraToolCallGate(),
    }
    results = {}
    for name, gate in variants.items():
        outcomes = [simulate(task, gate.decide(task)) for task in tasks]
        results[name] = aggregate_metrics(tasks, outcomes)
    return {
        "benchmark": "toolcall_benchmark_v1",
        "n_tasks": len(tasks),
        "ablations": results,
        "limitations": [
            "deterministic simulator benchmark",
            "ablation flags use synthetic PolicyObservation features",
            "no live oracle calls",
        ],
    }


def main() -> None:
    result = run()
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Ablation tasks: {result['n_tasks']}")
    for name, metrics in result["ablations"].items():
        print(
            f"{name}: unsafe={metrics['unsafe_execution_rate']:.4f} "
            f"utility={metrics['mean_utility']:.4f}"
        )
    print(f"Results written to {RESULT_PATH}")


if __name__ == "__main__":
    main()
