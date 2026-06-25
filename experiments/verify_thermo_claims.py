#!/usr/bin/env python3
"""Verification pack for thermodynamic claims.

This script checks the claims that are actually supportable from the current
code + committed artifacts and reports which claims remain partial or negative.
It exits non-zero only when a *supported* claim regresses or a required
artifact is missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_json(relative_path: str) -> dict:
    path = ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Missing required artifact: {relative_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, label: str, detail: str, failures: list[str]) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}: {detail}")
    if not condition:
        failures.append(label)


def note(label: str, detail: str) -> None:
    print(f"[NOTE] {label}: {detail}")


def load_json_optional(relative_path: str) -> dict | None:
    path = ROOT / relative_path
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    failures: list[str] = []

    thermo = load_json("results/thermodynamic_eval_results.json")
    transition = load_json("results/phase_transition_study_results.json")
    chi_utility = load_json_optional("results/chi_iteration_utility_results.json")
    chi_live = load_json("results/chi_perturbation_study_results.json")
    routing = load_json("results/phase_aware_routing_results.json")
    ablation = load_json("results/ablation_v2_canonical_results.json")
    router_eval = load_json_optional("results/thermodynamic_router_eval_results.json")
    router_eval_n500_evidence = load_json_optional("results/thermodynamic_router_eval_n500_evidence_results.json")

    phase_counts = thermo["summary"]["phase_counts"]
    phase_summary = thermo["summary"]["phase_summary"]

    print("\n== Supported claims ==")
    check(
        phase_counts.get("ordered", 0) >= 5 and phase_counts.get("critical", 0) >= 5 and phase_counts.get("disordered", 0) >= 5,
        "phase_split_non_degenerate",
        f"counts={phase_counts}",
        failures,
    )
    check(
        phase_summary["ordered"]["mean_trust_score"] > phase_summary["critical"]["mean_trust_score"] > phase_summary["disordered"]["mean_trust_score"],
        "trust_ordering",
        (
            f"ordered={phase_summary['ordered']['mean_trust_score']:.4f}, "
            f"critical={phase_summary['critical']['mean_trust_score']:.4f}, "
            f"disordered={phase_summary['disordered']['mean_trust_score']:.4f}"
        ),
        failures,
    )
    check(
        transition["summary"]["eta_range"] >= 0.50,
        "transition_like_structure",
        f"eta_range={transition['summary']['eta_range']:.4f}",
        failures,
    )
    check(
        ablation["conditions"]["B_majority"]["accuracy"] > ablation["conditions"]["A_single"]["accuracy"],
        "multi_oracle_beats_single",
        (
            f"A_single={ablation['conditions']['A_single']['accuracy']:.4f}, "
            f"B_majority={ablation['conditions']['B_majority']['accuracy']:.4f}"
        ),
        failures,
    )
    check(
        routing["summary"]["e1_accuracy_on_covered"] > routing["summary"]["baseline_accuracy"],
        "phase_abstention_improves_answered_accuracy",
        (
            f"baseline={routing['summary']['baseline_accuracy']:.4f}, "
            f"phase_abstain={routing['summary']['e1_accuracy_on_covered']:.4f}"
        ),
        failures,
    )

    print("\n== Partial / deconfirmed claims ==")
    note(
        "susceptibility_live_fragility_law",
        (
            f"NOT SUPPORTED: spearman_rho={chi_live['summary']['spearman_rho_chi_fragility']:+.4f}, "
            f"ordered_frag={chi_live['summary']['phase_summary']['ordered']['mean_fragility']:.4f}, "
            f"disordered_frag={chi_live['summary']['phase_summary']['disordered']['mean_fragility']:.4f}"
        ),
    )
    note(
        "full_coverage_routing_superiority",
        (
            f"NOT SUPPORTED: oracle_optimal_phase_route={routing['summary']['e4_oracle_optimal_accuracy']:.4f}, "
            f"baseline={routing['summary']['baseline_accuracy']:.4f}"
        ),
    )
    note(
        "hallucination_bound_theorem",
        (
            "CANDIDATE STATUS (under revision): The v1 bound expression is numerically "
            "consistent on N=302 (B(3,0.264,0.236)=0.039 > P_all_wrong=0.018), but is "
            "tracked as a candidate bound — not a proven theorem — due to two unresolved "
            "issues: (1) pair-independence across chaining blocks is assumed, not proved; "
            "(2) rho_bar is measured as response-agreement, not error-correlation "
            "(see remora/correlation_error.py for the distinction). "
            "Revised candidate bound: remora/proofs/false_consensus_bound_v2.py"
        ),
    )
    if chi_utility is None:
        note(
            "susceptibility_offline_harm_signal",
            "PENDING: results/chi_iteration_utility_results.json is not present in this worktree.",
        )
    else:
        note(
            "susceptibility_offline_harm_signal",
            (
                f"PARTIAL: auc_help={chi_utility['summary']['auc_help']:.4f}, "
                f"auc_hurt={chi_utility['summary']['auc_hurt']:.4f}"
            ),
        )
    if router_eval is None:
        note(
            "thermodynamic_guardrail_policy_eval",
            "PENDING: run experiments/thermodynamic_router_eval.py to measure selective accuracy and majority-error interception under the enforced guardrail.",
        )
    else:
        summary = router_eval["summary"]
        note(
            "thermodynamic_guardrail_policy_eval",
            (
                f"guardrail_coverage={summary['guardrail_coverage']:.4f}, "
                f"answered_accuracy={summary['guardrail_accuracy_on_answered']:.4f}, "
                f"majority_error_intercept_rate={summary['majority_error_intercept_rate']:.4f}, "
                f"delta_vs_majority_same_coverage={summary['guardrail_vs_majority_same_coverage_delta']:+.4f}"
            ),
        )
    if router_eval_n500_evidence is None:
        note(
            "thermodynamic_evidence_backfill_eval",
            "PENDING: run the N500 evidence-backed thermodynamic router evaluation to measure full-coverage performance.",
        )
    else:
        summary = router_eval_n500_evidence["summary"]
        evidence = router_eval_n500_evidence["evidence_backfill"]
        note(
            "thermodynamic_evidence_backfill_eval",
            (
                f"majority_accuracy={summary['majority_accuracy']:.4f}, "
                f"evidence_accuracy={evidence['accuracy']:.4f}, "
                f"coverage={evidence['coverage']:.4f}, "
                f"extra_evidence_calls={evidence['extra_evidence_calls']}"
            ),
        )

    print("\n== Sprint 1–3 module integrity ==")
    # Verify correlation_error module is importable and the core contract holds
    try:
        sys.path.insert(0, str(ROOT))
        from remora.correlation_error import (
            response_agreement_rate,
            binary_error_correlation,
            error_indicators,
        )
        preds_bool = [True, True, False, False]
        labels_bool = [True, True, False, False]  # perfect predictions
        errors = error_indicators(preds_bool, labels_bool)
        rho_err = binary_error_correlation(errors, errors)
        ra = response_agreement_rate(preds_bool, preds_bool)
        check(
            ra == 1.0 and rho_err == 0.0,
            "response_error_separation_contract",
            f"response_agreement={ra:.3f} (should be 1.0), error_correlation={rho_err:.3f} (should be 0.0 — perfect preds have no errors to correlate)",
            failures,
        )
    except ImportError as exc:
        check(False, "response_error_separation_import", str(exc), failures)

    # Verify calibration package is importable and Brier score contract holds
    try:
        from remora.calibration import brier_score
        bs_perfect = brier_score([1.0, 0.0], [True, False])
        bs_worst = brier_score([0.0, 1.0], [True, False])
        check(
            bs_perfect == 0.0 and bs_worst == 1.0,
            "calibration_brier_score_contract",
            f"perfect_bs={bs_perfect:.3f} (should be 0.0), worst_bs={bs_worst:.3f} (should be 1.0)",
            failures,
        )
    except ImportError as exc:
        check(False, "calibration_package_import", str(exc), failures)

    # Verify selective package is importable and SelectiveRouter basic contract holds
    try:
        from remora.selective import SelectiveRouter, SelectiveAction
        scores = [0.9, 0.8, 0.7, 0.3, 0.2, 0.1]
        labels_sel = [True, True, True, False, False, False]
        router = SelectiveRouter(target_risk=0.15)
        router.fit(scores, labels_sel)
        decision = router.route(0.9)
        check(
            decision.action in (SelectiveAction.ACCEPT, SelectiveAction.VERIFY),
            "selective_router_high_score_action",
            f"route(0.9).action={decision.action.value} (expected ACCEPT or VERIFY)",
            failures,
        )
        low_decision = router.route(0.05)
        check(
            low_decision.action in (SelectiveAction.ABSTAIN, SelectiveAction.ESCALATE),
            "selective_router_low_score_abstains",
            f"route(0.05).action={low_decision.action.value} (expected ABSTAIN or ESCALATE)",
            failures,
        )
    except ImportError as exc:
        check(False, "selective_package_import", str(exc), failures)

    # Verify false_consensus_bound_v2 is importable and returns a valid bound
    try:
        from remora.proofs.false_consensus_bound_v2 import candidate_bound, BoundInputs
        inputs = BoundInputs(epsilon=0.264, rho_error=0.236, n_oracles=3)
        result = candidate_bound(inputs, assume_pair_independence=False)
        check(
            0.0 < result <= 1.0,
            "false_consensus_bound_v2_in_unit_interval",
            f"candidate_bound(n=3, eps=0.264, rho=0.236)={result:.4f}",
            failures,
        )
    except ImportError as exc:
        check(False, "false_consensus_bound_v2_import", str(exc), failures)

    # Report calibration artifact if present
    calibration_report = load_json_optional("results/trust_calibration_report.json")
    if calibration_report is None:
        note(
            "trust_calibration_report",
            "PENDING: run experiments/nested_trust_calibration.py to generate first calibration artifact.",
        )
    else:
        temperature = calibration_report.get("model", {}).get("temperature", None)
        holdout_ece_post = (
            calibration_report.get("holdout", {}).get("post", {}).get("ece", None)
        )
        boundary_warning = ""
        if temperature is not None and temperature >= 4.0:
            boundary_warning = " [WARNING: temperature at search ceiling — calibration range too narrow; extend t_max or inspect bimodal trust scores]"
        note(
            "trust_calibration_report",
            (
                f"temperature={temperature}, holdout_ece_post={holdout_ece_post}"
                f"{boundary_warning}"
            ),
        )

    if failures:
        print(f"\nVerification failed: {len(failures)} supported claim(s) regressed -> {', '.join(failures)}")
        return 1

    print("\nVerification passed: all currently supported thermodynamic claims remain intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
