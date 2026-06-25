"""Phase-aware routing experiment.

Tests whether thermodynamic phase classification provides a useful routing
signal by comparing three abstention/routing policies against the B_majority
baseline on the canonical N=302 benchmark.

Policies
--------
E1_phase_abstain
    Ordered and critical items are answered with B_majority; disordered items
    are abstained (no answer returned).  The claim: discarding items the
    thermodynamic classifier labels as "hopeless" raises accuracy on the
    answered subset and reduces false-trust rate.

E2_eta_abstain  (comparison baseline)
    Abstain on the 206 lowest-η items (same coverage as E1), use B_majority
    for the rest.  This tests whether the thermodynamic phase boundary adds
    value over a simple order-parameter threshold.

E3_trust_abstain  (comparison baseline)
    Abstain on the 206 lowest-trust-score items (same coverage), use
    B_majority for the rest.  Trust-score already encodes phase, so E1 and
    E3 are expected to be close; a tie means the phase abstention is
    well-calibrated.

E4_optimal_phase_route
    Route every item to the condition that had the highest per-phase accuracy
    (oracle-optimal look-up, not realisable at inference time).  This sets the
    upper bound for any phase-aware routing policy.

Results are written to results/phase_aware_routing_results.json.

Usage
-----
    python experiments/phase_aware_routing.py
    python experiments/phase_aware_routing.py --output path/to/out.json
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from typing import Dict, List


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _ci95(correct: int, n: int) -> tuple[float, float]:
    """Wilson score 95 % confidence interval."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = correct / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(centre - spread, 4), round(centre + spread, 4))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run(thermo_path: str, ablation_path: str) -> dict:
    thermo = _load(thermo_path)
    ablation = _load(ablation_path)

    items: List[dict] = thermo["items"]
    n_total = len(items)

    # per-condition lookup: item_id -> correct (bool)
    per_cond: Dict[str, Dict[str, bool]] = {
        cond: {it["item_id"]: bool(it["correct"]) for it in cdata["items"]}
        for cond, cdata in ablation["conditions"].items()
    }
    conditions = list(per_cond.keys())

    # ── per-phase accuracy for every condition ──────────────────────────────
    phase_stats: Dict[str, Dict[str, dict]] = {}
    for it in items:
        phase = it["phase"]
        iid = it["item_id"]
        if phase not in phase_stats:
            phase_stats[phase] = {c: {"n": 0, "correct": 0} for c in conditions}
        for c in conditions:
            phase_stats[phase][c]["n"] += 1
            phase_stats[phase][c]["correct"] += int(per_cond[c][iid])

    per_phase_summary = {}
    for phase, cdata in phase_stats.items():
        row = {"n": cdata[conditions[0]]["n"]}
        for c in conditions:
            n = cdata[c]["n"]
            k = cdata[c]["correct"]
            row[c] = {"accuracy": round(k / n, 4), "correct": k}
        per_phase_summary[phase] = row

    # ── B_majority baseline ─────────────────────────────────────────────────
    maj_correct = sum(int(per_cond["B_majority"][it["item_id"]]) for it in items)
    baseline = {
        "policy": "B_majority_no_abstain",
        "covered": n_total,
        "abstained": 0,
        "coverage_rate": 1.0,
        "correct_on_covered": maj_correct,
        "accuracy_on_covered": round(maj_correct / n_total, 4),
        "overall_accuracy": round(maj_correct / n_total, 4),
        "false_trust_rate_on_covered": round(1 - maj_correct / n_total, 4),
        "ci_95_on_covered": _ci95(maj_correct, n_total),
    }

    # ── E1: phase-abstain ───────────────────────────────────────────────────
    e1_covered, e1_correct = 0, 0
    for it in items:
        if it["phase"] != "disordered":
            e1_covered += 1
            e1_correct += int(per_cond["B_majority"][it["item_id"]])
    e1 = {
        "policy": "E1_phase_abstain",
        "description": (
            "Answer ordered+critical with B_majority; abstain on disordered. "
            "Thermodynamic phase is the sole routing signal."
        ),
        "covered": e1_covered,
        "abstained": n_total - e1_covered,
        "coverage_rate": round(e1_covered / n_total, 4),
        "correct_on_covered": e1_correct,
        "accuracy_on_covered": round(e1_correct / e1_covered, 4) if e1_covered else 0,
        "overall_accuracy": round(e1_correct / n_total, 4),
        "false_trust_rate_on_covered": round(1 - e1_correct / e1_covered, 4) if e1_covered else 1,
        "ci_95_on_covered": _ci95(e1_correct, e1_covered),
    }

    # ── E2: η-threshold abstain (same coverage as E1) ───────────────────────
    n_abstain = n_total - e1_covered
    eta_sorted = sorted(items, key=lambda x: x["order_parameter"])
    abstain_eta = {it["item_id"] for it in eta_sorted[:n_abstain]}
    e2_covered, e2_correct = 0, 0
    for it in items:
        if it["item_id"] not in abstain_eta:
            e2_covered += 1
            e2_correct += int(per_cond["B_majority"][it["item_id"]])
    e2 = {
        "policy": "E2_eta_threshold_abstain",
        "description": (
            f"Abstain on the {n_abstain} lowest-η items (same coverage as E1); "
            "answer the rest with B_majority. Simple order-parameter threshold."
        ),
        "covered": e2_covered,
        "abstained": n_total - e2_covered,
        "coverage_rate": round(e2_covered / n_total, 4),
        "correct_on_covered": e2_correct,
        "accuracy_on_covered": round(e2_correct / e2_covered, 4) if e2_covered else 0,
        "overall_accuracy": round(e2_correct / n_total, 4),
        "false_trust_rate_on_covered": round(1 - e2_correct / e2_covered, 4) if e2_covered else 1,
        "ci_95_on_covered": _ci95(e2_correct, e2_covered),
    }

    # ── E3: trust-score-threshold abstain (same coverage) ───────────────────
    trust_sorted = sorted(items, key=lambda x: x["trust_score"])
    abstain_trust = {it["item_id"] for it in trust_sorted[:n_abstain]}
    e3_covered, e3_correct = 0, 0
    for it in items:
        if it["item_id"] not in abstain_trust:
            e3_covered += 1
            e3_correct += int(per_cond["B_majority"][it["item_id"]])
    e3 = {
        "policy": "E3_trust_score_abstain",
        "description": (
            f"Abstain on the {n_abstain} lowest-trust-score items (same coverage "
            "as E1); answer the rest with B_majority. Trust-score encodes phase."
        ),
        "covered": e3_covered,
        "abstained": n_total - e3_covered,
        "coverage_rate": round(e3_covered / n_total, 4),
        "correct_on_covered": e3_correct,
        "accuracy_on_covered": round(e3_correct / e3_covered, 4) if e3_covered else 0,
        "overall_accuracy": round(e3_correct / n_total, 4),
        "false_trust_rate_on_covered": round(1 - e3_correct / e3_covered, 4) if e3_covered else 1,
        "ci_95_on_covered": _ci95(e3_correct, e3_covered),
    }

    # ── E4: oracle-optimal per-phase route (upper bound) ────────────────────
    # Pick the condition with highest per-phase accuracy; not realisable at
    # inference time — this sets the theoretical ceiling.
    best_by_phase = {}
    for phase, cdata in phase_stats.items():
        best_c = max(conditions, key=lambda c: cdata[c]["correct"] / cdata[c]["n"])
        best_by_phase[phase] = best_c

    e4_covered, e4_correct = 0, 0
    for it in items:
        phase = it["phase"]
        cond = best_by_phase[phase]
        e4_covered += 1
        e4_correct += int(per_cond[cond][it["item_id"]])
    e4 = {
        "policy": "E4_oracle_optimal_phase_route",
        "description": (
            "Route each item to the condition with highest per-phase accuracy. "
            "Oracle-optimal: not realisable at inference time. Upper bound only."
        ),
        "phase_assignments": best_by_phase,
        "covered": e4_covered,
        "abstained": 0,
        "coverage_rate": 1.0,
        "correct_on_covered": e4_correct,
        "accuracy_on_covered": round(e4_correct / e4_covered, 4),
        "overall_accuracy": round(e4_correct / n_total, 4),
        "false_trust_rate_on_covered": round(1 - e4_correct / e4_covered, 4),
        "ci_95_on_covered": _ci95(e4_correct, e4_covered),
    }

    # ── summary comparisons ─────────────────────────────────────────────────
    phase_abstain_acc = e1["accuracy_on_covered"]
    eta_abstain_acc = e2["accuracy_on_covered"]
    baseline_acc = baseline["accuracy_on_covered"]

    summary = {
        "n_items": n_total,
        "baseline_accuracy": baseline_acc,
        "baseline_false_trust_rate": baseline["false_trust_rate_on_covered"],
        # E1 improvements vs baseline
        "e1_accuracy_on_covered": phase_abstain_acc,
        "e1_false_trust_rate": e1["false_trust_rate_on_covered"],
        "e1_coverage_rate": e1["coverage_rate"],
        "e1_lift_over_baseline": round(phase_abstain_acc - baseline_acc, 4),
        "e1_false_trust_reduction": round(
            baseline["false_trust_rate_on_covered"] - e1["false_trust_rate_on_covered"], 4
        ),
        # E1 vs E2 (phase vs η-threshold at same coverage)
        "e1_lift_over_eta_threshold": round(phase_abstain_acc - eta_abstain_acc, 4),
        # upper bound
        "e4_oracle_optimal_accuracy": e4["accuracy_on_covered"],
    }

    return {
        "meta": {
            "experiment": "phase_aware_routing",
            "thermo_source": thermo_path,
            "ablation_source": ablation_path,
            "n_items": n_total,
        },
        "per_phase_condition_accuracy": per_phase_summary,
        "policies": {
            "baseline": baseline,
            "E1_phase_abstain": e1,
            "E2_eta_threshold_abstain": e2,
            "E3_trust_score_abstain": e3,
            "E4_oracle_optimal_phase_route": e4,
        },
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--thermo", default="results/thermodynamic_eval_results.json",
        help="Path to thermodynamic eval results.",
    )
    parser.add_argument(
        "--ablation", default="results/ablation_v2_results.json",
        help="Path to ablation_v2 results.",
    )
    parser.add_argument(
        "--output", default="results/phase_aware_routing_results.json",
        help="Output path for results JSON.",
    )
    args = parser.parse_args(argv)

    results = run(args.thermo, args.ablation)

    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    s = results["summary"]
    print(f"\nPhase-aware routing on N={s['n_items']} canonical benchmark")
    print(f"{'Policy':<38} {'acc_on_covered':>14} {'false_trust':>12} {'coverage':>9}")
    print("-" * 78)
    for key, pol in results["policies"].items():
        print(
            f"  {pol['policy']:<36} "
            f"{pol['accuracy_on_covered']:>14.4f} "
            f"{pol['false_trust_rate_on_covered']:>12.4f} "
            f"{pol['coverage_rate']:>9.4f}"
        )
    print()
    print(f"E1 lift over baseline:          {s['e1_lift_over_baseline']:+.4f} acc_on_covered")
    print(f"E1 false-trust reduction:       {s['e1_false_trust_reduction']:+.4f}")
    print(f"E1 lift over η-threshold:       {s['e1_lift_over_eta_threshold']:+.4f}")
    print(f"Oracle-optimal ceiling (E4):    {s['e4_oracle_optimal_accuracy']:.4f}")
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
