# Author: Stian Skogbrott
# License: Apache-2.0
"""Evaluate PhaseAwareGuardrail on the canonical N=544 benchmark.

Produces results/phase_aware_guardrail_n544_results.json with:
- Empirical operating points (flat phase-based policy, no conformal threshold)
- Conformal operating points at multiple target_risk levels
- Wilson 95% CI for accuracy at each operating point

Empirical operating points use the phase label as a hard routing signal,
accepting all ordered items and all low-tau (tau < max_critical_tau) critical
items.  These are the operating-point figures quoted in the PhaseAwareGuardrail
docstring.

Conformal operating points apply conformal_threshold to calibration data and
report coverage/accuracy on the held-out test split only.

Run whenever the guardrail logic or benchmark changes:

    python experiments/evaluate_phase_aware_guardrail.py

Input:  results/thermodynamic_eval_n500_calibrated_results.json  (N=544)
Output: results/phase_aware_guardrail_n544_results.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from remora.selective.guardrail import PhaseAwareGuardrail, SelectiveAction


_DEFAULT_INPUT = Path("results/thermodynamic_eval_n500_calibrated_results.json")
_DEFAULT_OUTPUT = Path("results/phase_aware_guardrail_n544_results.json")

_CORRECTNESS_KEYS = ("majority_correct", "is_correct", "correct", "answered_correctly")


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _metrics(accepted: list[bool], total: int) -> dict:
    n_acc = len(accepted)
    n_correct = sum(accepted)
    coverage = n_acc / total if total else 0.0
    accuracy = n_correct / n_acc if n_acc else 0.0
    lo, hi = _wilson_ci(n_correct, n_acc)
    return {
        "n_accepted": n_acc,
        "n_total": total,
        "coverage": round(coverage, 4),
        "accuracy": round(accuracy, 4),
        "wilson_ci_95": [round(lo, 4), round(hi, 4)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PhaseAwareGuardrail")
    parser.add_argument("--input", type=Path, default=_DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--max-critical-tau", type=float, default=0.10)
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    items_raw = raw.get("items") or (raw if isinstance(raw, list) else [])
    items = [x for x in items_raw if isinstance(x, dict)]
    if not items:
        raise SystemExit(f"No items found in {args.input}")

    scores = [float(x["trust_score"]) for x in items]
    labels: list[bool] = []
    for x in items:
        y = None
        for k in _CORRECTNESS_KEYS:
            if k in x and x[k] is not None:
                y = x[k]; break
        labels.append(bool(y))
    phases = [x.get("phase", "disordered") for x in items]
    n = len(scores)

    phase_counts = {}
    for p in phases:
        phase_counts[p] = phase_counts.get(p, 0) + 1
    print(f"Loaded {n} items from {args.input}")
    print(f"Phase distribution: {phase_counts}")

    # ------------------------------------------------------------------
    # Empirical operating points (flat policy, full N=544)
    # ------------------------------------------------------------------
    # Policy A: all ordered items
    ord_correct = [y for s, y, p in zip(scores, labels, phases) if p == "ordered"]
    # Policy B: ordered + low-tau critical (tau < max_critical_tau)
    crit_low_correct = [
        y for s, y, p in zip(scores, labels, phases)
        if p == "critical" and s < args.max_critical_tau
    ]
    policy_a = _metrics(ord_correct, n)
    policy_b = _metrics(ord_correct + crit_low_correct, n)

    print(f"\nEmpirical operating points (flat phase policy, N={n}):")
    print(f"  ordered_only ({policy_a['coverage']:.1%}): accuracy={policy_a['accuracy']:.1%}  "
          f"CI={policy_a['wilson_ci_95']}")
    print(f"  +low_tau_critical ({policy_b['coverage']:.1%}): accuracy={policy_b['accuracy']:.1%}  "
          f"CI={policy_b['wilson_ci_95']}")

    # ------------------------------------------------------------------
    # Conformal operating points at multiple target_risk levels
    # ------------------------------------------------------------------
    conformal_results = []
    for tr in [0.05, 0.10, 0.13, 0.15]:
        g = PhaseAwareGuardrail(
            target_risk=tr, cal_fraction=0.6,
            max_critical_tau=args.max_critical_tau, seed=0,
        )
        summary = g.fit(scores, labels, phases)
        accepted_correct = [y for s, y, p in zip(scores, labels, phases)
                            if g.route(s, p).action == SelectiveAction.ACCEPT]
        m = _metrics(accepted_correct, n)
        conformal_results.append({
            "target_risk": tr,
            "ordered_threshold": g._ordered_threshold,
            "critical_inv_threshold": g._critical_inv_threshold,
            "calibration_summary": summary,
            **m,
        })
        print(f"  conformal(risk={tr}): coverage={m['coverage']:.1%}  "
              f"accuracy={m['accuracy']:.1%}  ord_thresh={g._ordered_threshold:.4f}")

    output = {
        "input": args.input.as_posix(),
        "n_items": n,
        "phase_distribution": phase_counts,
        "max_critical_tau": args.max_critical_tau,
        "empirical_operating_points": {
            "note": (
                "Flat phase-based policy: no conformal threshold applied. "
                "All ordered items are accepted (policy_a), "
                "plus all critical items with trust_score < max_critical_tau (policy_b). "
                "These are the operating-point figures in the PhaseAwareGuardrail docstring."
            ),
            "ordered_only": policy_a,
            "ordered_plus_low_tau_critical": policy_b,
        },
        "conformal_operating_points": {
            "note": (
                "Conformal calibration applied (cal_fraction=0.6, seed=0). "
                "Coverage/accuracy on full N; guarantee holds only on holdout. "
                "UNATTAINABLE_THRESHOLD (1.01) means no valid threshold found."
            ),
            "by_target_risk": conformal_results,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
