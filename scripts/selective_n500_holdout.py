# Author: Stian Skogbrott
# License: Apache-2.0
"""Held-out evaluation for N500 selective-trust claim.

Performs a stratified 80/20 split on the 544-item N500 calibrated benchmark,
selects the temperature threshold tau* on the 80% training set (maximising
selective accuracy), then evaluates on the 20% holdout with tau* LOCKED.

This produces an out-of-sample estimate of the selective-trust claim reported
in §10 of the REMORA paper, validating that the result is not an artefact of
in-sample threshold selection.

Usage
-----
    python scripts/selective_n500_holdout.py

Output
------
    results/selective_n500_holdout_results.json
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path

DATA_PATH = Path("results/thermodynamic_eval_n500_calibrated_results.json")
OUT_PATH = Path("results/selective_n500_holdout_results.json")

RANDOM_SEED = 42
HOLDOUT_FRACTION = 0.20
SIGNAL = "neg_temperature"  # primary signal identified in in-sample analysis
COVERAGE_TARGET = 0.18      # in-sample optimal coverage (locked from §10 analysis)
MIN_ACCEPTED = 5            # minimum holdout items to report a meaningful result


# ---------------------------------------------------------------------------
# Statistical helpers (mirrors experiments/selective_n500.py)
# ---------------------------------------------------------------------------

def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _p_value_one_sided(k: int, n: int, p0: float) -> float:
    """One-sided binomial p-value (H1: accuracy > p0) via normal approximation."""
    if n == 0:
        return 1.0
    p_hat = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return 0.0 if p_hat > p0 else 1.0
    z = (p_hat - p0) / se
    return 0.5 * math.erfc(z / math.sqrt(2))


# ---------------------------------------------------------------------------
# Stratified split
# ---------------------------------------------------------------------------

def stratified_split(
    items: list[dict],
    holdout_fraction: float,
    seed: int,
) -> tuple[list[dict], list[dict]]:
    """Return (train, holdout) split stratified by `benchmark` field."""
    rng = random.Random(seed)
    by_source: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        src = item.get("benchmark", "unknown")
        by_source[src].append(item)

    train, holdout = [], []
    for src, group in sorted(by_source.items()):
        shuffled = list(group)
        rng.shuffle(shuffled)
        n_hold = max(1, round(len(shuffled) * holdout_fraction))
        holdout.extend(shuffled[:n_hold])
        train.extend(shuffled[n_hold:])

    return train, holdout


# ---------------------------------------------------------------------------
# Threshold selection on training set
# ---------------------------------------------------------------------------

def select_threshold(
    train: list[dict],
    coverage_target: float = COVERAGE_TARGET,
) -> tuple[float, dict]:
    """Select temperature threshold tau* from training set at a fixed coverage target.

    tau* is the temperature of the (coverage_target * n_train)-th lowest item.
    This is the canonical locked-threshold approach: coverage is fixed at the
    in-sample optimum (18%), so no coverage is re-selected on holdout data.
    """
    n_train = len(train)
    baseline_correct = sum(1 for it in train if it["majority_correct"])
    baseline_acc = baseline_correct / n_train if n_train else 0.0

    sorted_train = sorted(train, key=lambda it: it["temperature"])
    k_train = max(1, round(n_train * coverage_target))
    top_k = sorted_train[:k_train]
    tau_star = top_k[-1]["temperature"]

    correct_train = sum(1 for it in top_k if it["majority_correct"])
    acc_train = correct_train / k_train
    ci_lo, ci_hi = _wilson(correct_train, k_train)
    p_val = _p_value_one_sided(correct_train, k_train, baseline_acc)

    train_stats = {
        "tau_star": round(tau_star, 6),
        "coverage_target": coverage_target,
        "k_train": k_train,
        "n_train": n_train,
        "correct_train": correct_train,
        "accuracy_train": round(acc_train, 6),
        "coverage_train": round(k_train / n_train, 4),
        "baseline_accuracy_train": round(baseline_acc, 6),
        "lift_pp_train": round((acc_train - baseline_acc) * 100, 4),
        "wilson_ci_train": [round(ci_lo, 4), round(ci_hi, 4)],
        "p_one_sided_train": round(p_val, 8),
    }
    return tau_star, train_stats


# ---------------------------------------------------------------------------
# Holdout evaluation with locked tau*
# ---------------------------------------------------------------------------

def evaluate_holdout(
    holdout: list[dict],
    tau_star: float,
    baseline_acc: float,
) -> dict:
    """Accept holdout items where temperature <= tau* (LOCKED from training set)."""
    accepted = [it for it in holdout if it["temperature"] <= tau_star]
    n_hold = len(holdout)
    n_accepted = len(accepted)
    correct = sum(1 for it in accepted if it["majority_correct"])

    if n_accepted < MIN_ACCEPTED:
        return {
            "warning": (
                f"Only {n_accepted} holdout items accepted at tau*={tau_star:.6f}; "
                "result is unreliable - report with caution."
            ),
            "n_holdout": n_hold,
            "n_accepted": n_accepted,
        }

    acc = correct / n_accepted
    holdout_coverage = n_accepted / n_hold
    ci_lo, ci_hi = _wilson(correct, n_accepted)
    p_val = _p_value_one_sided(correct, n_accepted, baseline_acc)

    # Phase composition of accepted holdout items
    phase_counts: dict[str, int] = {}
    for it in accepted:
        ph = it["phase"]
        phase_counts[ph] = phase_counts.get(ph, 0) + 1

    return {
        "tau_star": round(tau_star, 6),
        "n_holdout": n_hold,
        "n_accepted": n_accepted,
        "correct": correct,
        "accuracy_holdout": round(acc, 6),
        "coverage_holdout": round(holdout_coverage, 4),
        "baseline_accuracy_holdout": round(baseline_acc, 6),
        "lift_pp_holdout": round((acc - baseline_acc) * 100, 4),
        "wilson_ci_holdout": [round(ci_lo, 4), round(ci_hi, 4)],
        "p_one_sided_holdout": round(p_val, 8),
        "ci_above_baseline": ci_lo > baseline_acc,
        "phase_composition": phase_counts,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    data_path: Path = DATA_PATH,
    out_path: Path = OUT_PATH,
    seed: int = RANDOM_SEED,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> dict:
    raw = json.loads(data_path.read_text())
    items: list[dict] = raw if isinstance(raw, list) else raw.get("items", raw.get("results", []))

    n_total = len(items)
    n_correct_total = sum(1 for it in items if it["majority_correct"])
    baseline_acc_total = n_correct_total / n_total

    # Source breakdown
    by_source: dict[str, int] = defaultdict(int)
    for it in items:
        by_source[it.get("benchmark", "unknown")] += 1

    # Stratified split
    train, holdout = stratified_split(items, holdout_fraction, seed=seed)

    n_hold_correct = sum(1 for it in holdout if it["majority_correct"])
    baseline_acc_holdout = n_hold_correct / len(holdout) if holdout else 0.0

    # Select tau* on training set
    tau_star, train_stats = select_threshold(train)

    # Evaluate on holdout with locked tau*
    holdout_stats = evaluate_holdout(holdout, tau_star, baseline_acc_holdout)

    # Summary string
    if "accuracy_holdout" in holdout_stats:
        acc_h = holdout_stats["accuracy_holdout"]
        cov_h = holdout_stats["coverage_holdout"]
        n_acc = holdout_stats["n_accepted"]
        lift = holdout_stats["lift_pp_holdout"]
        ci_lo, ci_hi = holdout_stats["wilson_ci_holdout"]
        p_val = holdout_stats["p_one_sided_holdout"]
        summary = (
            f"Held-out: {acc_h*100:.2f}% accuracy at {cov_h*100:.1f}% coverage "
            f"(n_accepted={n_acc}, lift +{lift:.2f} pp over "
            f"{baseline_acc_holdout*100:.2f}% holdout baseline, "
            f"Wilson CI [{ci_lo:.3f}, {ci_hi:.3f}], p={p_val:.2e})"
        )
    else:
        summary = holdout_stats.get("warning", "Evaluation failed - see holdout_stats for details.")

    result = {
        "meta": {
            "script": "scripts/selective_n500_holdout.py",
            "data_source": str(data_path),
            "random_seed": seed,
            "holdout_fraction": holdout_fraction,
            "signal": SIGNAL,
            "note": (
                "tau* = 18th-percentile temperature on 80% training split (coverage locked at 0.18, "
                "the in-sample optimum); evaluated on 20% holdout with tau* LOCKED "
                "(no re-optimisation on holdout)."
            ),
        },
        "full_dataset": {
            "n": n_total,
            "baseline_accuracy": round(baseline_acc_total, 6),
            "source_counts": dict(by_source),
        },
        "split": {
            "n_train": len(train),
            "n_holdout": len(holdout),
        },
        "training_threshold_selection": train_stats,
        "holdout_evaluation": holdout_stats,
        "summary": summary,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(summary)
    print(f"\ntau* = {tau_star:.6f}  (selected on {len(train)}-item training set)")
    print(f"Train selective accuracy: {train_stats['accuracy_train']*100:.2f}% "
          f"at {train_stats['coverage_train']*100:.1f}% coverage")
    return result


if __name__ == "__main__":
    run()
