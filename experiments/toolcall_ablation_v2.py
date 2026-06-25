from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_ablation.json"
LEGACY_RESULT_PATH = REPO_ROOT / "results" / "toolcall_ablation_v2_results.json"


def run() -> dict[str, Any]:
    tasks = load_benchmark_v2()
    variants = {
        "remora_without_temperature": RemoraToolCallGate(use_temperature_signal=False),
        "remora_without_phase": RemoraToolCallGate(use_phase_signal=False),
        "remora_without_evidence": RemoraToolCallGate(use_evidence_flags=False),
        "remora_without_counterfactual": RemoraToolCallGate(use_counterfactual_flags=False),
        "remora_without_hard_blocks": RemoraToolCallGate(
            use_hard_blocks=False,
            use_context_overrides=False,
            use_contradiction_flags=False,
            use_counterfactual_flags=False,
        ),
        "remora_full": RemoraToolCallGate(),
    }
    results = {}
    for name, gate in variants.items():
        outcomes = [simulate(task, gate.decide(task)) for task in tasks]
        results[name] = aggregate_metrics(tasks, outcomes)
    return {
        "benchmark": "toolcall_benchmark_v2",
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
    LEGACY_RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Ablation v2 tasks: {result['n_tasks']}")
    for name, metrics in result["ablations"].items():
        print(
            f"{name}: unsafe={metrics['unsafe_execution_rate']:.4f} "
            f"utility={metrics['mean_utility']:.4f} "
            f"accuracy={metrics['accuracy']:.4f}"
        )
    print(f"Results written to {RESULT_PATH}")
    print(f"Legacy alias written to {LEGACY_RESULT_PATH}")


if __name__ == "__main__":
    main()
