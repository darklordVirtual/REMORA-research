from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
TOOLCALL_DOC_PATH = REPO_ROOT / "docs" / "archive" / "toolcall_consensus_benchmark_v1.md"
TOOLCALL_DOC_V2_PATH = REPO_ROOT / "docs" / "toolcall_consensus_benchmark_v2.md"
ARCH_PATH = REPO_ROOT / "ARCHITECTURE.md"

SELECTIVE_302_PATH = REPO_ROOT / "results" / "selective_trust_curve_results.json"
SELECTIVE_544_PATH = REPO_ROOT / "results" / "selective_n500_results.json"
TOOLCALL_RESULTS_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v1_results.json"
TOOLCALL_RESULTS_V2_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_results.json"
TOOLCALL_RESULTS_V2_SIG_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_significance.json"

OUT_PATH = REPO_ROOT / "results" / "claim_consistency_audit.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_row(rows: list[dict[str, Any]], *, key: str, value: float) -> dict[str, Any]:
    for row in rows:
        if abs(float(row[key]) - value) < 1e-9:
            return row
    raise ValueError(f"missing row with {key}={value}")


def _contains(text: str, needle: str) -> bool:
    return needle in text


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def run_audit() -> dict[str, Any]:
    readme = _read(README_PATH)
    toolcall_doc = _read(TOOLCALL_DOC_PATH)
    toolcall_doc_v2 = _read(TOOLCALL_DOC_V2_PATH)
    architecture = _read(ARCH_PATH)

    selective_302 = _load_json(SELECTIVE_302_PATH)
    selective_544 = _load_json(SELECTIVE_544_PATH)
    toolcall = _load_json(TOOLCALL_RESULTS_PATH)
    toolcall_v2 = _load_json(TOOLCALL_RESULTS_V2_PATH)
    toolcall_v2_sig = _load_json(TOOLCALL_RESULTS_V2_SIG_PATH)

    row_302_25 = _find_row(selective_302["curves"]["neg_temperature"], key="coverage_pct", value=0.25)
    row_544_10 = _find_row(
        [r for r in selective_544["selective_curve"] if r["signal"] == "neg_temperature"],
        key="coverage",
        value=0.10,
    )
    row_544_15 = _find_row(
        [r for r in selective_544["selective_curve"] if r["signal"] == "neg_temperature"],
        key="coverage",
        value=0.15,
    )
    row_544_18 = _find_row(
        [r for r in selective_544["selective_curve"] if r["signal"] == "neg_temperature"],
        key="coverage",
        value=0.18,
    )
    row_544_20 = _find_row(
        [r for r in selective_544["selective_curve"] if r["signal"] == "neg_temperature"],
        key="coverage",
        value=0.20,
    )

    checks: list[dict[str, Any]] = []

    def add_check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"id": check_id, "passed": passed, "detail": detail})

    add_check(
        "readme_n500_label_544",
        _contains(readme, "544 questions"),
        "README should explicitly state that Result 2 evaluates 544 questions.",
    )
    add_check(
        "readme_n500_historical_note",
        _contains(readme, "The label `N500` is historical"),
        "README should clarify that N500 is a historical label.",
    )
    add_check(
        "readme_result1_25pct",
        all(
            _contains(readme, token)
            for token in [
                str(row_302_25["k_covered"]),
                str(row_302_25["correct"]),
                f"{row_302_25['accuracy'] * 100:.1f}%",
            ]
        ),
        "README Result 1 top-25% row should match selective_trust_curve_results.json (neg_temperature).",
    )
    add_check(
        "readme_result2_rows",
        all(
            _contains(readme, token)
            for token in [
                str(row_544_10["k"]),
                str(row_544_15["k"]),
                str(row_544_18["k"]),
                str(row_544_20["k"]),
                f"{row_544_18['accuracy'] * 100:.1f}%",
                f"{selective_544['baseline_accuracy'] * 100:.2f}%",
            ]
        ),
        "README Result 2 rows should match selective_n500_results.json (neg_temperature).",
    )
    add_check(
        "readme_toolcall_task_counts",
        _contains(readme, f"v1 ({toolcall['n_tasks']} tasks)") and _contains(readme, f"v2 ({toolcall_v2['n_tasks']} tasks)"),
        "README tool-call section should match v1 and v2 benchmark task counts.",
    )

    full_policy = toolcall["baselines"]["remora_full_policy_gate"]
    temp_gate = toolcall["baselines"]["remora_temperature_gate_heuristic"]
    add_check(
        "readme_toolcall_v1_metrics",
        all(
            _contains(readme, token)
            for token in [
                f"{temp_gate['mean_utility']:.4f}",
                f"{full_policy['mean_utility']:.4f}",
                f"{full_policy['accuracy']:.4f}",
                "v1 does not demonstrate unsafe-execution reduction",
            ]
        ),
        "README v1 tool-call metrics and negative finding statement should match the artifact.",
    )

    full_policy_v2 = toolcall_v2["baselines"]["remora_full_policy_gate"]
    temp_gate_v2 = toolcall_v2["baselines"]["remora_temperature_gate_heuristic"]
    add_check(
        "readme_toolcall_v2_metrics",
        all(
            _contains(readme, token)
            for token in [
                f"{temp_gate_v2['mean_utility']:.4f}",
                f"{full_policy_v2['mean_utility']:.4f}",
                f"{full_policy_v2['accuracy']:.4f}",
                "reduces unsafe",
            ]
        ),
        "README v2 tool-call metrics should match the harder benchmark artifact.",
    )

    single_v2_sig = toolcall_v2_sig["comparisons"]["single_model_heuristic"]
    add_check(
        "readme_toolcall_v2_significance_reference",
        _contains(readme, "toolcall_benchmark_v2_significance.json"),
        "README should reference the v2 significance artifact.",
    )

    add_check(
        "toolcall_doc_metrics",
        all(
            _contains(toolcall_doc, token)
            for token in [
                f"{temp_gate['mean_utility']:.4f}",
                f"{full_policy['mean_utility']:.4f}",
                f"{full_policy['accuracy']:.4f}",
                "not yet",
            ]
        ),
        "Tool-call benchmark doc should match committed benchmark metrics and state the non-demonstration.",
    )

    add_check(
        "toolcall_v2_doc_metrics",
        all(
            _contains(toolcall_doc_v2, token)
            for token in [
                str(toolcall_v2["n_tasks"]),
                f"{full_policy_v2['unsafe_execution_rate']:.4f}",
                f"{full_policy_v2['mean_utility']:.4f}",
                f"{full_policy_v2['accuracy']:.4f}",
            ]
        ),
        "Tool-call v2 doc should match committed v2 metrics.",
    )

    add_check(
        "architecture_n500_evaluable_items",
        _contains(architecture, "544 evaluable items"),
        "ARCHITECTURE.md should clarify that N500 artifact currently has 544 evaluable items.",
    )

    audit = {
        "audit_version": "claim_consistency_audit_v2",
        "inputs": {
            "readme": _rel(README_PATH),
            "toolcall_doc": _rel(TOOLCALL_DOC_PATH),
            "toolcall_doc_v2": _rel(TOOLCALL_DOC_V2_PATH),
            "architecture": _rel(ARCH_PATH),
            "selective_302": _rel(SELECTIVE_302_PATH),
            "selective_544": _rel(SELECTIVE_544_PATH),
            "toolcall_results": _rel(TOOLCALL_RESULTS_PATH),
            "toolcall_results_v2": _rel(TOOLCALL_RESULTS_V2_PATH),
            "toolcall_results_v2_significance": _rel(TOOLCALL_RESULTS_V2_SIG_PATH),
        },
        "extracted_metrics": {
            "result1_top25": {
                "k": row_302_25["k_covered"],
                "correct": row_302_25["correct"],
                "accuracy": row_302_25["accuracy"],
            },
            "result2": {
                "n": selective_544["n"],
                "baseline_accuracy": selective_544["baseline_accuracy"],
                "top10": {"k": row_544_10["k"], "correct": row_544_10["correct"], "accuracy": row_544_10["accuracy"]},
                "top15": {"k": row_544_15["k"], "correct": row_544_15["correct"], "accuracy": row_544_15["accuracy"]},
                "top18": {"k": row_544_18["k"], "correct": row_544_18["correct"], "accuracy": row_544_18["accuracy"]},
                "top20": {"k": row_544_20["k"], "correct": row_544_20["correct"], "accuracy": row_544_20["accuracy"]},
            },
            "toolcall_v1": {
                "n_tasks": toolcall["n_tasks"],
                "remora_temperature_gate_heuristic": {
                    "accuracy": temp_gate["accuracy"],
                    "mean_utility": temp_gate["mean_utility"],
                    "unsafe_execution_rate": temp_gate["unsafe_execution_rate"],
                },
                "remora_full_policy_gate": {
                    "accuracy": full_policy["accuracy"],
                    "mean_utility": full_policy["mean_utility"],
                    "unsafe_execution_rate": full_policy["unsafe_execution_rate"],
                },
            },
            "toolcall_v2": {
                "n_tasks": toolcall_v2["n_tasks"],
                "remora_temperature_gate_heuristic": {
                    "accuracy": temp_gate_v2["accuracy"],
                    "mean_utility": temp_gate_v2["mean_utility"],
                    "unsafe_execution_rate": temp_gate_v2["unsafe_execution_rate"],
                },
                "remora_full_policy_gate": {
                    "accuracy": full_policy_v2["accuracy"],
                    "mean_utility": full_policy_v2["mean_utility"],
                    "unsafe_execution_rate": full_policy_v2["unsafe_execution_rate"],
                },
            },
            "toolcall_v2_significance": {
                "single_model_heuristic_unsafe_delta": single_v2_sig[
                    "unsafe_execution_rate_delta_baseline_minus_remora"
                ],
                "single_model_heuristic_unsafe_ci95": single_v2_sig["unsafe_rate_delta_ci95"],
                "single_model_heuristic_unsafe_pvalue": single_v2_sig[
                    "unsafe_rate_delta_pvalue_one_sided"
                ],
            },
        },
        "checks": checks,
        "all_passed": all(c["passed"] for c in checks),
        "limitations": [
            "Checks verify string-level consistency for key headline metrics, not full semantic equivalence of every document sentence.",
            "Audit is artifact-scoped and does not validate live-model behavior.",
        ],
    }
    return audit


def main() -> None:
    audit = run_audit()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"claim_consistency_audit all_passed={audit['all_passed']}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
