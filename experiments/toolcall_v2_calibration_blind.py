from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from remora.toolcall.baselines import ToolCallBaseline, all_baselines
from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.schema import ToolCallDecision, ToolCallOutcome, ToolCallTask
from remora.toolcall.simulators import simulate
from remora.toolcall.splits_v2 import BLIND_FAMILIES, split_tasks_v2

REPO_ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_calibration.json"
BLIND_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_blind_test.json"
CALIBRATION_ALIAS = REPO_ROOT / "results" / "calibration_result.json"
BLIND_ALIAS = REPO_ROOT / "results" / "blind_test_result.json"


def _apply_execute_threshold(decision: ToolCallDecision, threshold: float) -> ToolCallDecision:
    if decision.action != "EXECUTE":
        return decision
    if decision.confidence is None or decision.confidence < threshold:
        return replace(
            decision,
            action="VERIFY",
            reasons=tuple(decision.reasons) + ("calibrated_execute_threshold",),
        )
    return decision


def _evaluate_with_threshold(
    tasks: list[ToolCallTask], baseline: ToolCallBaseline, threshold: float
) -> tuple[list[ToolCallOutcome], dict[str, Any]]:
    outcomes = [simulate(task, _apply_execute_threshold(baseline.decide(task), threshold)) for task in tasks]
    return outcomes, aggregate_metrics(tasks, outcomes)


def _select_threshold(tasks: list[ToolCallTask], baseline: ToolCallBaseline) -> dict[str, Any]:
    candidates = [i / 20 for i in range(21)]  # 0.00 .. 1.00
    best: dict[str, Any] | None = None
    for t in candidates:
        _, metrics = _evaluate_with_threshold(tasks, baseline, t)
        key = (
            metrics["unsafe_execution_rate"],
            -metrics["mean_utility"],
            -metrics["accuracy"],
            t,
        )
        if best is None or key < best["key"]:
            best = {"threshold": t, "metrics": metrics, "key": key}
    assert best is not None
    return {"threshold": best["threshold"], "metrics": best["metrics"]}


def _with_comparison_fields(metrics_by_baseline: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {k: dict(v) for k, v in metrics_by_baseline.items()}
    majority_unsafe = out["majority_vote_heuristic"]["unsafe_execution_rate"]
    best_utility = max(v["mean_utility"] for v in out.values())
    for metrics in out.values():
        metrics["unsafe_execution_reduction_vs_majority"] = (
            majority_unsafe - metrics["unsafe_execution_rate"]
        )
        metrics["utility_delta_vs_best_baseline"] = metrics["mean_utility"] - best_utility
    return out


def run() -> tuple[dict[str, Any], dict[str, Any]]:
    tasks = load_benchmark_v2()
    splits = split_tasks_v2(tasks)
    baselines = all_baselines()

    calibration_selected: dict[str, Any] = {}
    validation_metrics: dict[str, Any] = {}
    blind_metrics: dict[str, Any] = {}

    for baseline in baselines:
        selected = _select_threshold(splits["calibration"], baseline)
        threshold = float(selected["threshold"])
        calibration_selected[baseline.name] = {
            "execute_confidence_min": threshold,
            "calibration_metrics": selected["metrics"],
        }

        _, val_m = _evaluate_with_threshold(splits["validation"], baseline, threshold)
        _, blind_m = _evaluate_with_threshold(splits["blind_test"], baseline, threshold)
        validation_metrics[baseline.name] = val_m
        blind_metrics[baseline.name] = blind_m

    validation_metrics = _with_comparison_fields(validation_metrics)
    blind_metrics = _with_comparison_fields(blind_metrics)

    n_total = len(tasks)
    calibration_result = {
        "benchmark": "toolcall_benchmark_v2",
        "split_strategy": "family-heldout OOD blind test",
        "blind_families": sorted(BLIND_FAMILIES),
        "split_counts": {
            "total": n_total,
            "calibration": len(splits["calibration"]),
            "validation": len(splits["validation"]),
            "blind_test": len(splits["blind_test"]),
            "calibration_pct": len(splits["calibration"]) / n_total if n_total else 0.0,
            "validation_pct": len(splits["validation"]) / n_total if n_total else 0.0,
            "blind_test_pct": len(splits["blind_test"]) / n_total if n_total else 0.0,
        },
        "selected_thresholds": calibration_selected,
        "validation_metrics": validation_metrics,
        "limitations": [
            "Calibration uses synthetic benchmark tasks only.",
            "Threshold policy only gates EXECUTE by confidence; richer calibration may improve trade-offs.",
            "No live model behavior is included in this calibration run.",
        ],
    }

    blind_result = {
        "benchmark": "toolcall_benchmark_v2",
        "evaluation_split": "blind_test",
        "split_counts": calibration_result["split_counts"],
        "baselines": blind_metrics,
        "primary_metric": "unsafe_execution_rate",
        "limitations": [
            "Blind split is OOD by scenario family within the same synthetic benchmark generator.",
            "No live LLM calls are included in this blind result artifact.",
        ],
    }
    return calibration_result, blind_result


def main() -> None:
    calibration_result, blind_result = run()
    CALIBRATION_PATH.write_text(json.dumps(calibration_result, indent=2), encoding="utf-8")
    BLIND_PATH.write_text(json.dumps(blind_result, indent=2), encoding="utf-8")
    CALIBRATION_ALIAS.write_text(json.dumps(calibration_result, indent=2), encoding="utf-8")
    BLIND_ALIAS.write_text(json.dumps(blind_result, indent=2), encoding="utf-8")
    print(f"Wrote {CALIBRATION_PATH}")
    print(f"Wrote {BLIND_PATH}")


if __name__ == "__main__":
    main()
