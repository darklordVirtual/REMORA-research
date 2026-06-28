# Author: Stian Skogbrott
# License: Apache-2.0
"""M1 clean-signal evaluation: measure FAR without label leakage.

M1 (peer-review finding): RemoraToolCallGate.to_observation() accesses
task.is_unsafe_if_executed when use_contradiction_flags=True. This is a
construct validity problem — the gate sees the evaluation target label.

This script runs two conditions:
  - LEAKY:  standard gate (use_contradiction_flags=True)  — current reported result
  - CLEAN:  use_contradiction_flags=False only            — no is_unsafe_if_executed access
  - CLEAN2: use_contradiction_flags=False + use_severity_flags=False
            — also removes severity-driven routing, which correlates with harmfulness

The difference between LEAKY and CLEAN quantifies the label-leakage contribution.

If CLEAN FAR == 0: structural gates (context_override) alone catch all harmful tasks,
  and the M1 leakage does not inflate the FAR=0 claim — the claim holds with a
  different (non-leaking) mechanism.

If CLEAN FAR > 0: M1 leakage was load-bearing; FAR=0 requires label access and
  the reported result is invalid.

Artifact: results/toolcall_m1_clean_signal.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_m1_clean_signal.json"


def run() -> dict[str, Any]:
    tasks = load_benchmark_v2()

    variants = {
        "leaky_with_contradiction_flags": RemoraToolCallGate(
            use_contradiction_flags=True,
        ),
        "clean_no_contradiction_flags": RemoraToolCallGate(
            use_contradiction_flags=False,
        ),
        "clean_strict_no_labels": RemoraToolCallGate(
            use_contradiction_flags=False,
            use_severity_flags=False,
        ),
    }

    results: dict[str, Any] = {}
    for name, gate in variants.items():
        outcomes = [simulate(task, gate.decide(task)) for task in tasks]
        metrics = aggregate_metrics(tasks, outcomes)
        results[name] = {
            "use_contradiction_flags": name == "leaky_with_contradiction_flags",
            "use_severity_flags": name != "clean_strict_no_labels",
            "false_accept_rate": metrics["false_accept_rate"],
            "unsafe_execution_rate": metrics["unsafe_execution_rate"],
            "mean_utility": metrics["mean_utility"],
            "accuracy": metrics["accuracy"],
            "escalate_rate": metrics["escalate_rate"],
            "verify_rate": metrics["verify_rate"],
            "n_tasks": metrics["n_tasks"],
            "unsafe_execution_count": metrics["unsafe_execution_count"],
        }

    leaky_far = results["leaky_with_contradiction_flags"]["false_accept_rate"]
    clean_far = results["clean_no_contradiction_flags"]["false_accept_rate"]

    finding = (
        "M1 LABEL LEAKAGE CONFIRMED — FAR inflated by contradiction flags"
        if clean_far > leaky_far
        else (
            "M1 LABEL LEAKAGE LOAD-BEARING — clean FAR > leaky FAR; structural gates"
            " alone do not achieve FAR=0 without is_unsafe_if_executed access"
            if clean_far > 0.0 and clean_far > leaky_far
            else (
                "M1 LEAKAGE NOT LOAD-BEARING — clean FAR=0; structural context gates "
                "(injection/approval/conflict) alone are sufficient for FAR=0; "
                "is_unsafe_if_executed access via contradiction flags is redundant "
                "for the benchmark's safety guarantee"
                if clean_far == 0.0
                else "M1 FINDING INCONCLUSIVE"
            )
        )
    )

    return {
        "benchmark": "toolcall_benchmark_v2",
        "n_tasks": len(tasks),
        "purpose": (
            "Peer-review M1 validation: quantify label-leakage contribution to FAR. "
            "use_contradiction_flags=True gives gate access to task.is_unsafe_if_executed; "
            "use_contradiction_flags=False removes it."
        ),
        "conditions": results,
        "leakage_delta": round(clean_far - leaky_far, 4),
        "finding": finding,
        "interpretation": (
            "If FAR is identical under LEAKY and CLEAN, the contradiction flags do "
            "not affect the safety outcome on this benchmark — the structural gates "
            "(context overrides) catch all harmful tasks independently of the label. "
            "The M1 documentation remains valid (the leakage exists in the code) "
            "but its effect on the reported metric is zero."
        ),
        "limitations": [
            "Deterministic simulator benchmark — all decisions are computed from task metadata.",
            "Structural context flags (injection, approval, conflict) are themselves "
            "correlated with is_unsafe_if_executed in the benchmark. Clean-signal "
            "validity depends on whether these flags would be available in real deployments.",
            "use_severity_flags controls severity-driven routing; severity correlates "
            "with harmfulness but is a legitimate metadata field in real deployments.",
            "External replication with withheld labels required for definitive M1 resolution.",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    result = run()
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\n=== M1 Clean-Signal Evaluation ===")
    print(f"Benchmark: {result['benchmark']}, N={result['n_tasks']}\n")
    header = f"{'Condition':<42} {'FAR':>6} {'UnsafeExec':>10} {'Utility':>8} {'Contradiction':>14} {'Severity':>10}"
    print(header)
    print("-" * len(header))
    for cond, metrics in result["conditions"].items():
        print(
            f"{cond:<42} "
            f"{metrics['false_accept_rate']:>6.4f} "
            f"{metrics['unsafe_execution_rate']:>10.4f} "
            f"{metrics['mean_utility']:>8.4f} "
            f"{'ON' if metrics['use_contradiction_flags'] else 'OFF':>14} "
            f"{'ON' if metrics['use_severity_flags'] else 'OFF':>10}"
        )

    print(f"\nLeakage delta (clean - leaky): {result['leakage_delta']:+.4f}")
    print(f"\nFinding: {result['finding']}")
    print(f"\nArtifact: {RESULT_PATH}")


if __name__ == "__main__":
    main()
