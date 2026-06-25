"""Tool-Call Benchmark v3 — Evaluator.

Evaluates REMORA as a *selective autonomy and policy-routing layer* for
tool-using agents across four benchmark layers:

  capability  — correct function selection and schema validation
  workflow    — multi-step sequences and API contracts
  safety      — domain-based risk routing and human escalation
  injection   — indirect prompt injection and taint propagation

Primary claim (sober):
  REMORA is evaluated as a selective autonomy and policy-routing layer for
  tool-using agents. The benchmark measures not only whether the correct tool
  was selected, but whether tool execution was safe, policy-compliant,
  auditable and appropriately escalated under uncertainty or adversarial
  pressure.

Limitations (methodologically explicit):
  - Deterministic simulator benchmark; no live LLM or API calls.
  - All data is synthetic / template-derived (labelled "BFCL-inspired" etc.).
  - Injection detection uses regex heuristics, not semantic understanding.
  - Taint detection uses substring matching, not data-flow analysis.
  - Results are benchmark-specific and do not imply performance on real workloads.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.toolcall.baselines_v3 import all_v3_baselines
from remora.toolcall.benchmark_v3 import load_v3_tasks
from remora.toolcall.scoring_v3 import aggregate_v3_metrics, score_v3_outcome

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v3_results.json"
SUMMARY_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v3_summary.md"


def _cross_baseline_comparison(
    all_results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Compute delta metrics relative to REMORA and best baseline."""
    remora_key = "remora_full_policy_gate_v3"
    remora_unsafe = all_results[remora_key]["overall"]["unsafe_execution_rate"]
    remora_pda = all_results[remora_key]["overall"]["policy_decision_accuracy"]
    best_utility = max(
        m["overall"]["mean_utility"] for m in all_results.values()
    )

    comparison: dict[str, dict[str, Any]] = {}
    for name, result in all_results.items():
        ov = result["overall"]
        comparison[name] = {
            "unsafe_execution_rate": ov["unsafe_execution_rate"],
            "policy_decision_accuracy": ov["policy_decision_accuracy"],
            "false_block_rate": ov["false_block_rate"],
            "injection_resistance_rate": ov.get("injection_resistance_rate"),
            "human_escalation_precision": ov.get("human_escalation_precision"),
            "mean_utility": ov["mean_utility"],
            "unsafe_rate_delta_vs_remora": (
                ov["unsafe_execution_rate"] - remora_unsafe
            ),
            "pda_delta_vs_remora": ov["policy_decision_accuracy"] - remora_pda,
            "utility_delta_vs_best": ov["mean_utility"] - best_utility,
        }
    return comparison


def run() -> dict[str, Any]:
    """Run the full v3 evaluation and return the results dict."""
    # Load (or build) benchmark tasks
    tasks_by_layer = load_v3_tasks()
    all_tasks = [t for layer_tasks in tasks_by_layer.values() for t in layer_tasks]
    n_total = len(all_tasks)

    baselines = all_v3_baselines()
    all_results: dict[str, dict[str, Any]] = {}

    for baseline in baselines:
        # Per-layer results
        layer_results: dict[str, Any] = {}
        all_outcomes = []

        for layer, layer_tasks in tasks_by_layer.items():
            outcomes = [score_v3_outcome(t, baseline.decide(t)) for t in layer_tasks]
            all_outcomes.extend(outcomes)
            layer_results[layer] = aggregate_v3_metrics(layer_tasks, outcomes)

        # Overall metrics across all layers
        overall = aggregate_v3_metrics(all_tasks, all_outcomes)

        # Failure analysis: which tasks were incorrectly handled?
        failures = [
            {
                "task_id": o.task_id,
                "layer": o.layer,
                "expected": t.expected_policy_decision,
                "got": o.result.decision,
                "unsafe": o.unsafe_execution,
                "forbidden_executed": o.forbidden_tool_executed,
                "taint_violation": o.argument_taint_violation,
                "injection_not_resisted": (
                    t.attack_type is not None and not o.injection_resisted
                ),
            }
            for t, o in zip(all_tasks, all_outcomes)
            if not o.policy_decision_correct
        ]

        all_results[baseline.name] = {
            "overall": overall,
            "per_layer": layer_results,
            "n_failures": len(failures),
            "failure_sample": failures[:20],
        }

    comparison = _cross_baseline_comparison(all_results)

    return {
        "benchmark": "toolcall_benchmark_v3",
        "n_total_tasks": n_total,
        "n_tasks_by_layer": {
            layer: len(tasks) for layer, tasks in tasks_by_layer.items()
        },
        "baselines": all_results,
        "cross_baseline_comparison": comparison,
        "primary_metrics": [
            "policy_decision_accuracy",
            "unsafe_execution_rate",
            "injection_resistance_rate",
            "human_escalation_precision",
            "false_block_rate",
        ],
        "primary_claim": (
            "REMORA is evaluated as a selective autonomy and policy-routing layer "
            "for tool-using agents. The benchmark measures not only whether the "
            "correct tool was selected, but whether tool execution was safe, "
            "policy-compliant, auditable and appropriately escalated under "
            "uncertainty or adversarial pressure."
        ),
        "limitations": [
            "Deterministic simulator benchmark — no live LLM or API calls",
            "All tasks are synthetic / template-derived (labelled as such)",
            "Injection detection uses regex heuristics, not semantic NLP",
            "Taint detection uses substring matching, not data-flow analysis",
            "Schema validation is simulated via the schema_valid_call flag",
            "Results are benchmark-specific; real-workload performance may differ",
        ],
    }


def _format_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.1f}%"


def _write_summary(result: dict[str, Any]) -> str:
    """Generate a markdown summary report."""
    cmp = result["cross_baseline_comparison"]
    layers = sorted(result["n_tasks_by_layer"].keys())
    layer_counts = ", ".join(f"{layer}: {result['n_tasks_by_layer'][layer]}" for layer in layers)

    lines = [
        "# Tool-Call Benchmark v3 — Results Summary",
        "",
        "> **Primary claim:** " + result["primary_claim"],
        "",
        f"**Total tasks:** {result['n_total_tasks']} ({layer_counts})",
        "",
        "---",
        "",
        "## Overall Results (all 4 layers combined)",
        "",
        "| Strategy | Policy Acc | Unsafe Exec | False Block | Inj. Resistance | Human Esc. Prec | Utility |",
        "|----------|-----------|-------------|-------------|-----------------|-----------------|---------|",
    ]

    baseline_order = [
        "naive_tool_caller",
        "majority_vote_caller",
        "schema_only_validator",
        "static_policy_gate",
        "remora_full_policy_gate_v3",
    ]
    display_names = {
        "naive_tool_caller": "Naive tool caller",
        "majority_vote_caller": "Majority-vote caller",
        "schema_only_validator": "Schema-only validator",
        "static_policy_gate": "Static policy gate",
        "remora_full_policy_gate_v3": "**REMORA full policy gate v3**",
    }

    for name in baseline_order:
        if name not in cmp:
            continue
        m = cmp[name]
        lines.append(
            f"| {display_names[name]} "
            f"| {_format_pct(m['policy_decision_accuracy'])} "
            f"| {_format_pct(m['unsafe_execution_rate'])} "
            f"| {_format_pct(m['false_block_rate'])} "
            f"| {_format_pct(m.get('injection_resistance_rate'))} "
            f"| {_format_pct(m.get('human_escalation_precision'))} "
            f"| {m['mean_utility']:.3f} |"
        )

    lines += ["", "---", "", "## Per-Layer Results", ""]

    for layer in layers:
        lines.append(f"### Layer: {layer.capitalize()}")
        lines += [
            "",
            "| Strategy | Policy Acc | Unsafe Exec | Inj. Resistance | Utility |",
            "|----------|-----------|-------------|-----------------|---------|",
        ]
        for name in baseline_order:
            if name not in result["baselines"]:
                continue
            lm = result["baselines"][name]["per_layer"].get(layer, {})
            lines.append(
                f"| {display_names[name]} "
                f"| {_format_pct(lm.get('policy_decision_accuracy'))} "
                f"| {_format_pct(lm.get('unsafe_execution_rate'))} "
                f"| {_format_pct(lm.get('injection_resistance_rate'))} "
                f"| {lm.get('mean_utility', 0.0):.3f} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## Failure Mode Taxonomy",
        "",
        "| Failure type | Definition |",
        "|-------------|------------|",
        "| Capability failure | Agent selected wrong tool; policy layer could not compensate |",
        "| Policy failure | Policy gate made wrong EXECUTE/BLOCK/ESCALATE/VERIFY decision |",
        "| Unsafe execution | Tool executed when BLOCK or ESCALATE was expected |",
        "| Correct escalation | Task correctly routed to human review |",
        "| False positive (block) | Safe, correct call was blocked |",
        "| Adversarial bypass | Injection attack reached execution without detection |",
        "",
        "---",
        "",
        "## Methodological Notes",
        "",
    ]
    for lim in result["limitations"]:
        lines.append(f"- {lim}")

    lines += [
        "",
        "---",
        "",
        "*Generated by `experiments/evaluate_toolcall_benchmark_v3.py` — "
        "deterministic simulator, no live API calls.*",
    ]

    return "\n".join(lines)


def main() -> None:
    result = run()

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    summary = _write_summary(result)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        fh.write(summary)

    print(f"Results: {RESULT_PATH}")
    print(f"Summary: {SUMMARY_PATH}")

    # Print a compact console overview
    cmp = result["cross_baseline_comparison"]
    print(f"\n{'Strategy':<35} {'Policy Acc':>10} {'Unsafe%':>8} {'Inj Resist':>11}")
    print("-" * 68)
    for name in [
        "naive_tool_caller",
        "majority_vote_caller",
        "schema_only_validator",
        "static_policy_gate",
        "remora_full_policy_gate_v3",
    ]:
        if name not in cmp:
            continue
        m = cmp[name]
        inj = m.get("injection_resistance_rate")
        print(
            f"{name:<35} "
            f"{_format_pct(m['policy_decision_accuracy']):>10} "
            f"{_format_pct(m['unsafe_execution_rate']):>8} "
            f"{_format_pct(inj):>11}"
        )


if __name__ == "__main__":
    main()
