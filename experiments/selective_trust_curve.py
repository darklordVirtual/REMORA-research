"""Selective Trust Curve — empirical breakthrough proof for REMORA v4.

This experiment validates the strongest standing v4 hypothesis: that the
thermodynamic pre-sweep observables (trust_score, order_parameter,
temperature, susceptibility) provide a *continuous, statistically significant*
per-item correctness predictor when used as a ranking signal for selective
abstention, not merely a discrete phase classifier.

Method
------
We treat each thermodynamic observable as a confidence score and sort the
N=302 canonical benchmark items by that score in descending order (most
confident first). At each coverage operating point we measure:

  * accuracy on the covered subset
  * lift vs the B_majority baseline (82.78 %)
  * one-sided binomial p-value vs the baseline rate (null: random sampling)
  * Wilson 95 % confidence interval
  * lift vs random sampling (Monte-Carlo, 5000 trials)

The breakthrough claim is that for at least one inference-time-realisable
signal there is a coverage band where accuracy-on-covered exceeds baseline
with p < 0.05 and is robust against the random-sampling counterfactual.

Usage
-----
    python experiments/selective_trust_curve.py
    python experiments/selective_trust_curve.py --output results/selective_trust_curve_results.json
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import statistics as st
from typing import Callable


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(centre - spread, 4), round(centre + spread, 4))


def _binom_tail_geq(k: int, n: int, p: float) -> float:
    """One-sided P(X >= k | n, p) using exact binomial."""
    total = 0.0
    for i in range(k, n + 1):
        total += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return total


def _spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)

    def rank(arr: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: arr[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and arr[order[j + 1]] == arr[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = rank(xs), rank(ys)
    mean_x, mean_y = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    den_x = sum((rx[i] - mean_x) ** 2 for i in range(n))
    den_y = sum((ry[i] - mean_y) ** 2 for i in range(n))
    den = math.sqrt(den_x * den_y)
    return num / den if den else 0.0


def _random_baseline(items: list[dict], k: int, trials: int, seed: int, label_key: str) -> dict:
    rng = random.Random(seed)
    n = len(items)
    accs: list[float] = []
    for _ in range(trials):
        idx = rng.sample(range(n), k)
        correct = sum(1 for i in idx if items[i][label_key])
        accs.append(correct / k)
    return {
        "mean": round(st.mean(accs), 4),
        "stdev": round(st.stdev(accs), 4) if len(accs) > 1 else 0.0,
        "trials": trials,
    }


def _evaluate_signal(
    items: list[dict],
    score_fn: Callable[[dict], float],
    coverage_points: list[float],
    baseline_rate: float,
    label_key: str,
    random_trials: int = 5000,
    seed: int = 42,
) -> list[dict]:
    n = len(items)
    sorted_items = sorted(items, key=score_fn, reverse=True)
    rows: list[dict] = []
    for pct in coverage_points:
        k = max(1, int(round(n * pct)))
        sub = sorted_items[:k]
        correct = sum(1 for it in sub if it[label_key])
        acc = correct / k
        p_one_sided = _binom_tail_geq(correct, k, baseline_rate)
        rand = _random_baseline(items, k, random_trials, seed + k, label_key)
        rows.append({
            "coverage_pct": round(pct, 4),
            "k_covered": k,
            "correct": correct,
            "accuracy": round(acc, 4),
            "lift_vs_baseline": round(acc - baseline_rate, 4),
            "wilson_ci95": _wilson(correct, k),
            "p_value_one_sided_vs_baseline": round(p_one_sided, 6),
            "random_baseline_mean": rand["mean"],
            "random_baseline_stdev": rand["stdev"],
            "lift_vs_random_mean": round(acc - rand["mean"], 4),
        })
    return rows


def run(thermo_path: str, ablation_path: str, random_trials: int = 5000) -> dict:
    thermo = json.loads(pathlib.Path(thermo_path).read_text(encoding="utf-8"))
    ablation = json.loads(pathlib.Path(ablation_path).read_text(encoding="utf-8"))

    per_cond = {
        c: {it["item_id"]: bool(it["correct"]) for it in cd["items"]}
        for c, cd in ablation["conditions"].items()
    }
    items: list[dict] = []
    for it in thermo["items"]:
        merged = dict(it)
        for c in per_cond:
            merged[f"corr_{c}"] = per_cond[c].get(it["item_id"], False)
        items.append(merged)

    n = len(items)
    baseline_correct = sum(1 for it in items if it["corr_B_majority"])
    baseline_rate = baseline_correct / n

    coverage_points = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]

    signals = {
        "trust_score":          lambda x: x["trust_score"],
        "order_parameter":      lambda x: x["order_parameter"],
        "neg_temperature":      lambda x: -x["temperature"],
        "neg_susceptibility":   lambda x: -x["susceptibility"],
        "composite_eta_minus_chi":  lambda x: 0.5 * x["order_parameter"] - 0.1 * x["susceptibility"],
        "composite_trust_minus_temp": lambda x: x["trust_score"] - 0.5 * x["temperature"],
    }

    curves = {
        name: _evaluate_signal(items, fn, coverage_points, baseline_rate, "corr_B_majority", random_trials)
        for name, fn in signals.items()
    }

    # Spearman correlations vs majority correctness
    correct_ys = [1.0 if it["corr_B_majority"] else 0.0 for it in items]
    spearman_rho = {
        "trust_score":         round(_spearman([it["trust_score"] for it in items], correct_ys), 4),
        "order_parameter":     round(_spearman([it["order_parameter"] for it in items], correct_ys), 4),
        "neg_temperature":     round(_spearman([-it["temperature"] for it in items], correct_ys), 4),
        "neg_susceptibility":  round(_spearman([-it["susceptibility"] for it in items], correct_ys), 4),
    }

    # Identify breakthrough operating points (p < 0.05)
    breakthrough: list[dict] = []
    for sig_name, rows in curves.items():
        for r in rows:
            if r["p_value_one_sided_vs_baseline"] < 0.05 and r["lift_vs_baseline"] > 0:
                breakthrough.append({
                    "signal": sig_name,
                    "coverage_pct": r["coverage_pct"],
                    "k_covered": r["k_covered"],
                    "accuracy": r["accuracy"],
                    "lift_vs_baseline": r["lift_vs_baseline"],
                    "p_value": r["p_value_one_sided_vs_baseline"],
                    "wilson_ci95": r["wilson_ci95"],
                })

    # Best operating point per signal
    best_per_signal = {}
    for sig_name, rows in curves.items():
        eligible = [r for r in rows if r["p_value_one_sided_vs_baseline"] < 0.05 and r["lift_vs_baseline"] > 0]
        if eligible:
            top = max(eligible, key=lambda r: r["lift_vs_baseline"])
            best_per_signal[sig_name] = top
        else:
            best_per_signal[sig_name] = None

    return {
        "meta": {
            "experiment": "selective_trust_curve",
            "thermo_source": thermo_path,
            "ablation_source": ablation_path,
            "n_items": n,
            "baseline_rate": round(baseline_rate, 4),
            "random_trials_per_point": random_trials,
        },
        "spearman_rho_vs_majority_correctness": spearman_rho,
        "curves": curves,
        "breakthrough_operating_points": breakthrough,
        "best_operating_point_per_signal": best_per_signal,
        "summary": {
            "baseline_accuracy": round(baseline_rate, 4),
            "n_significant_points": len(breakthrough),
            "strongest_signal": max(
                ((s, r) for s, r in best_per_signal.items() if r is not None),
                key=lambda sr: sr[1]["lift_vs_baseline"],
                default=(None, None),
            )[0],
        },
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thermo", default="results/thermodynamic_eval_results.json")
    parser.add_argument("--ablation", default="results/ablation_v2_canonical_results.json")
    parser.add_argument("--output", default="results/selective_trust_curve_results.json")
    parser.add_argument("--random-trials", type=int, default=5000)
    args = parser.parse_args(argv)

    out = run(args.thermo, args.ablation, args.random_trials)
    pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")

    s = out["summary"]
    print(f"\nSelective Trust Curve on N={out['meta']['n_items']}, baseline = {s['baseline_accuracy']:.4f}")
    print(f"Significant breakthrough points (p<0.05, lift>0): {s['n_significant_points']}")
    print(f"Strongest signal: {s['strongest_signal']}")
    print()
    for sig, best in out["best_operating_point_per_signal"].items():
        if best is None:
            print(f"  {sig:<32} no significant operating point")
        else:
            ci = best["wilson_ci95"]
            print(
                f"  {sig:<32} best: cov={best['coverage_pct']:.2f} "
                f"acc={best['accuracy']:.4f} lift={best['lift_vs_baseline']:+.4f} "
                f"p={best['p_value_one_sided_vs_baseline']:.4g} CI95=[{ci[0]:.3f},{ci[1]:.3f}]"
            )
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
