# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""Empirical calibration of thermodynamic phase and trust thresholds.

This script fits a small calibration profile against an existing phase-study
artifact. The search keeps the thermodynamic model structure intact and only
rescales effective temperature plus phase/trust thresholds so that observed
accuracy aligns better with ordered/critical/disordered slices.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from remora.thermodynamics import (
    ThermodynamicCalibration,
    calibration_to_dict,
    classify_phase,
    trust_score,
)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def accuracy(rows: list[dict], key: str) -> float:
    return sum(1 for row in rows if row.get(key)) / len(rows) if rows else 0.0


def evaluate(rows: list[dict], calibration: ThermodynamicCalibration) -> tuple[float, dict]:
    grouped = {"ordered": [], "critical": [], "disordered": []}
    scored_rows = []
    for row in rows:
        phase = classify_phase(
            temperature=float(row["raw_temperature"]),
            t_critical=float(row["critical_temperature"]),
            eta=float(row["order_parameter"]),
            calibration=calibration,
        )
        tau = trust_score(
            eta=float(row["order_parameter"]),
            chi=float(row["susceptibility"]),
            halluc_bound=float(row["hallucination_bound"]),
            phase=phase,
            calibration=calibration,
        )
        scored = {**row, "calibrated_phase": phase, "calibrated_trust": tau}
        grouped[phase].append(scored)
        scored_rows.append(scored)

    n_total = len(rows)
    fractions = {phase: len(group) / n_total if n_total else 0.0 for phase, group in grouped.items()}
    ordered_acc = accuracy(grouped["ordered"], "d2_correct")
    critical_acc = accuracy(grouped["critical"], "d2_correct")
    disordered_acc = accuracy(grouped["disordered"], "d2_correct")
    ordered_trust = mean([row["calibrated_trust"] for row in grouped["ordered"]])
    critical_trust = mean([row["calibrated_trust"] for row in grouped["critical"]])
    disordered_trust = mean([row["calibrated_trust"] for row in grouped["disordered"]])

    score = 0.0
    score += 3.0 * (ordered_acc - disordered_acc)
    score += 2.0 * (ordered_trust - disordered_trust)
    score += 0.75 if ordered_acc > critical_acc > disordered_acc else -0.75
    score += 0.75 if ordered_trust > critical_trust > disordered_trust else -0.75
    score -= abs(fractions["critical"] - 0.20)
    for phase in grouped:
        if fractions[phase] < 0.05:
            score -= 1.5

    summary = {
        "score": round(score, 6),
        "phase_counts": {phase: len(group) for phase, group in grouped.items()},
        "phase_fractions": {phase: round(value, 4) for phase, value in fractions.items()},
        "ordered_accuracy": round(ordered_acc, 4),
        "critical_accuracy": round(critical_acc, 4),
        "disordered_accuracy": round(disordered_acc, 4),
        "ordered_trust": round(ordered_trust, 4),
        "critical_trust": round(critical_trust, 4),
        "disordered_trust": round(disordered_trust, 4),
        "items": scored_rows,
    }
    return score, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate thermodynamic thresholds from a phase-study artifact")
    parser.add_argument("--phase-study", required=True, help="Phase-study JSON artifact")
    parser.add_argument("--output", default="results/thermodynamic_calibration_n500.json", help="Calibration output JSON")
    parser.add_argument("--top-k", type=int, default=5, help="Number of top candidates to retain in the report")
    args = parser.parse_args()

    payload = json.loads(Path(args.phase_study).read_text(encoding="utf-8"))
    rows = payload["items"]

    temperature_scales = [0.5, 0.75, 1.0, 1.25, 1.5]
    temperature_offsets = [-0.05, 0.0, 0.05]
    critical_tolerances = [0.10, 0.15, 0.20, 0.25]
    ordered_min_etas = [0.50, 0.55, 0.60, 0.65]
    critical_weights = [0.35, 0.50, 0.65]
    disordered_weights = [0.03, 0.05, 0.10]
    chi_scales = [6.0, 10.0, 14.0]

    candidates = []
    for values in itertools.product(
        temperature_scales,
        temperature_offsets,
        critical_tolerances,
        ordered_min_etas,
        critical_weights,
        disordered_weights,
        chi_scales,
    ):
        calibration = ThermodynamicCalibration(
            temperature_scale=values[0],
            temperature_offset=values[1],
            critical_tolerance=values[2],
            ordered_min_eta=values[3],
            ordered_phase_weight=1.0,
            critical_phase_weight=values[4],
            disordered_phase_weight=values[5],
            chi_scale=values[6],
        )
        score, summary = evaluate(rows, calibration)
        candidates.append({
            "calibration": calibration,
            "summary": summary,
            "score": score,
        })

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    best = candidates[0]
    top = candidates[: max(1, args.top_k)]

    out = {
        "meta": {
            "source_phase_study": args.phase_study,
            "n_items": len(rows),
            "searched_candidates": len(candidates),
        },
        "calibration": calibration_to_dict(best["calibration"]),
        "summary": {k: v for k, v in best["summary"].items() if k != "items"},
        "top_candidates": [
            {
                "rank": index + 1,
                "score": round(candidate["score"], 6),
                "calibration": calibration_to_dict(candidate["calibration"]),
                "summary": {k: v for k, v in candidate["summary"].items() if k != "items"},
            }
            for index, candidate in enumerate(top)
        ],
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = out["summary"]
    print("\nBest thermodynamic calibration")
    print(f"  score={summary['score']:.4f}")
    print(
        "  phase counts="
        f"ordered={summary['phase_counts']['ordered']} "
        f"critical={summary['phase_counts']['critical']} "
        f"disordered={summary['phase_counts']['disordered']}"
    )
    print(
        "  D2 accuracy="
        f"ordered={summary['ordered_accuracy']:.1%} "
        f"critical={summary['critical_accuracy']:.1%} "
        f"disordered={summary['disordered_accuracy']:.1%}"
    )
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
