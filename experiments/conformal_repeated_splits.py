"""Repeated-splits conformal risk evaluation.

Loads results/thermodynamic_eval_results.json, runs ConformalPhaseGuardrail
over multiple random seeds, reports aggregate statistics.

Output: results/conformal_repeated_splits.json
"""
from __future__ import annotations

import json
import pathlib


_REPO_ROOT = pathlib.Path(__file__).parent.parent
_EVAL_PATH = _REPO_ROOT / "results" / "thermodynamic_eval_results.json"
_OUT_PATH = _REPO_ROOT / "results" / "conformal_repeated_splits.json"


def _load_data() -> tuple[list[float], list[bool]]:
    with open(_EVAL_PATH) as fh:
        data = json.load(fh)
    items = data["items"]
    scores = [float(item["trust_score"]) for item in items]
    labels = [bool(item["majority_correct"]) for item in items]
    return scores, labels


def run() -> list[dict]:
    from remora.selective.guardrail import ConformalPhaseGuardrail

    scores, labels = _load_data()
    target_risks = [0.05, 0.10, 0.15]
    seeds = list(range(20))

    results_by_target: list[dict] = []

    for target_risk in target_risks:
        seed_records: list[dict] = []
        for seed in seeds:
            guardrail = ConformalPhaseGuardrail(target_risk=target_risk, seed=seed)
            report = guardrail.fit(scores, labels)
            seed_records.append(
                {
                    "seed": seed,
                    "threshold": report.threshold,
                    "holdout_risk": report.holdout_risk,
                    "holdout_coverage": report.holdout_coverage,
                    "holdout_accepted": report.holdout_accepted,
                    "target_risk_met_by_point_estimate": report.target_risk_met_by_point_estimate,
                    "target_risk_met_by_upper_bound": report.target_risk_met_by_upper_bound,
                    "holdout_risk_upper_95": report.holdout_risk_upper_95,
                }
            )

        valid_risks = [r["holdout_risk"] for r in seed_records if r["holdout_risk"] is not None]
        valid_coverages = [r["holdout_coverage"] for r in seed_records]
        valid_accepted = [r["holdout_accepted"] for r in seed_records]

        mean_holdout_risk = sum(valid_risks) / len(valid_risks) if valid_risks else None
        max_holdout_risk = max(valid_risks) if valid_risks else None
        mean_coverage = sum(valid_coverages) / len(valid_coverages)
        min_coverage = min(valid_coverages)
        mean_accepted = sum(valid_accepted) / len(valid_accepted)

        failures_by_point_estimate = sum(
            1
            for r in seed_records
            if r["target_risk_met_by_point_estimate"] is False
        )
        failures_by_upper_bound = sum(
            1
            for r in seed_records
            if r["target_risk_met_by_upper_bound"] is False
        )

        results_by_target.append(
            {
                "target_risk": target_risk,
                "n_seeds": len(seeds),
                "mean_holdout_risk": mean_holdout_risk,
                "max_holdout_risk": max_holdout_risk,
                "mean_coverage": mean_coverage,
                "min_coverage": min_coverage,
                "mean_accepted": mean_accepted,
                "failures_by_point_estimate": failures_by_point_estimate,
                "failures_by_upper_bound": failures_by_upper_bound,
                "notes": (
                    "benchmark-locked; exchangeability assumed between cal and test draws"
                ),
            }
        )

    with open(_OUT_PATH, "w") as fh:
        json.dump(results_by_target, fh, indent=2)

    return results_by_target


def _print_summary(results: list[dict]) -> None:
    print("\n=== Conformal Repeated Splits Summary ===")
    for entry in results:
        print(
            f"  target_risk={entry['target_risk']:.2f} | "
            f"mean_risk={entry['mean_holdout_risk']:.4f} | "
            f"max_risk={entry['max_holdout_risk']:.4f} | "
            f"mean_cov={entry['mean_coverage']:.3f} | "
            f"fail_pt={entry['failures_by_point_estimate']}/{entry['n_seeds']} | "
            f"fail_ucb={entry['failures_by_upper_bound']}/{entry['n_seeds']}"
        )
    print(f"\nOutput written to: {_OUT_PATH}")


if __name__ == "__main__":
    results = run()
    _print_summary(results)
