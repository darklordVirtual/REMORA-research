"""Bootstrap validation of the selective trust curve result.

The selective_trust_curve experiment showed a +11.96 pp lift at 25 % coverage
when sorting items by -temperature (p = 0.0018 on N=302).  This script asks
the follow-up question: *is that finding stable, or could it be a lucky split
of the specific 302 items we happen to have?*

Method
------
We run B bootstrap iterations.  In each iteration:

1. Draw N items with replacement from the canonical N=302 pool.
2. For the selected sort signals, sort the bootstrap sample and evaluate
   accuracy-on-covered at each coverage operating point.
3. Record lift over the bootstrap-sample baseline.

Summary statistics across B iterations:
- mean lift, standard deviation
- fraction of iterations where lift > 0 (positive-signal rate)
- 2.5th / 97.5th percentile (bootstrap 95 % CI on lift)

A result is considered *bootstrapping-validated* when:
  * mean lift > 0 across all iterations
  * bootstrap 95 % CI lower bound > 0 at the headline operating point
  * positive-signal rate >= 0.80

This provides a non-parametric estimate of whether the observed signal
survives resampling noise.

Usage
-----
    python experiments/bootstrap_trust_curve.py
    python experiments/bootstrap_trust_curve.py --n-boot 2000 --output results/bootstrap_trust_curve_results.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import statistics as st
from typing import Callable


def _accuracy(sample: list[dict], score_fn: Callable[[dict], float], pct: float, label_key: str) -> float:
    k = max(1, int(round(len(sample) * pct)))
    top = sorted(sample, key=score_fn, reverse=True)[:k]
    return sum(1 for it in top if it[label_key]) / k


def _load(thermo_path: str, ablation_path: str) -> list[dict]:
    thermo = json.loads(pathlib.Path(thermo_path).read_text(encoding="utf-8"))
    ablation = json.loads(pathlib.Path(ablation_path).read_text(encoding="utf-8"))
    per_cond = {
        c: {it["item_id"]: bool(it["correct"]) for it in cd["items"]}
        for c, cd in ablation["conditions"].items()
    }
    items: list[dict] = []
    for it in thermo["items"]:
        m = dict(it)
        for c in per_cond:
            m[f"corr_{c}"] = per_cond[c].get(it["item_id"], False)
        items.append(m)
    return items


def run(
    thermo_path: str,
    ablation_path: str,
    n_boot: int = 2000,
    coverage_points: list[float] | None = None,
    seed: int = 42,
) -> dict:
    if coverage_points is None:
        coverage_points = [0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

    items = _load(thermo_path, ablation_path)
    n = len(items)
    label_key = "corr_B_majority"
    baseline_full = sum(1 for it in items if it[label_key]) / n

    signals: dict[str, Callable[[dict], float]] = {
        "neg_temperature": lambda x: -x["temperature"],
        "trust_score":     lambda x: x["trust_score"],
    }

    rng = random.Random(seed)
    results: dict[str, dict] = {}

    for sig_name, score_fn in signals.items():
        per_cov: dict[float, list[float]] = {pct: [] for pct in coverage_points}
        for _ in range(n_boot):
            boot = [items[rng.randint(0, n - 1)] for _ in range(n)]
            base = sum(1 for it in boot if it[label_key]) / n
            for pct in coverage_points:
                acc = _accuracy(boot, score_fn, pct, label_key)
                per_cov[pct].append(acc - base)

        cov_results = {}
        for pct in coverage_points:
            lifts = per_cov[pct]
            mean_lift = st.mean(lifts)
            sd_lift = st.stdev(lifts) if len(lifts) > 1 else 0.0
            sorted_lifts = sorted(lifts)
            lo = sorted_lifts[int(0.025 * n_boot)]
            hi = sorted_lifts[int(0.975 * n_boot)]
            pos_rate = sum(1 for v in lifts if v > 0) / n_boot
            validated = (mean_lift > 0) and (lo > 0) and (pos_rate >= 0.80)
            cov_results[str(pct)] = {
                "coverage_pct": pct,
                "mean_lift": round(mean_lift, 4),
                "sd_lift": round(sd_lift, 4),
                "bootstrap_ci95_lo": round(lo, 4),
                "bootstrap_ci95_hi": round(hi, 4),
                "positive_signal_rate": round(pos_rate, 4),
                "bootstrap_validated": validated,
            }
        results[sig_name] = cov_results

    # headline check on best operating point
    headline = results["neg_temperature"][str(0.25)]

    return {
        "meta": {
            "experiment": "bootstrap_trust_curve",
            "thermo_source": thermo_path,
            "ablation_source": ablation_path,
            "n_items": n,
            "n_bootstrap": n_boot,
            "baseline_full_accuracy": round(baseline_full, 4),
        },
        "signals": results,
        "headline_neg_temperature_25pct": headline,
        "summary": {
            "headline_mean_lift": headline["mean_lift"],
            "headline_ci95_lo": headline["bootstrap_ci95_lo"],
            "headline_positive_rate": headline["positive_signal_rate"],
            "bootstrap_validated": headline["bootstrap_validated"],
        },
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thermo", default="results/thermodynamic_eval_results.json")
    parser.add_argument("--ablation", default="results/ablation_v2_canonical_results.json")
    parser.add_argument("--output", default="results/bootstrap_trust_curve_results.json")
    parser.add_argument("--n-boot", type=int, default=2000)
    args = parser.parse_args(argv)

    out = run(args.thermo, args.ablation, args.n_boot)
    pathlib.Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")

    s = out["summary"]
    print(f"\nBootstrap trust curve validation  N={out['meta']['n_items']} items, B={args.n_boot} iterations")
    print(f"Baseline full accuracy: {out['meta']['baseline_full_accuracy']:.4f}")
    print()
    for sig, cov_results in out["signals"].items():
        print(f"  Signal: {sig}")
        print(f"    {'cov':>5}  {'mean_lift':>10}  {'CI95_lo':>8}  {'CI95_hi':>8}  {'pos_rate':>9}  {'validated':>10}")
        for cov_str, r in cov_results.items():
            print(
                f"    {r['coverage_pct']*100:>4.0f}%  "
                f"{r['mean_lift']:>+10.4f}  "
                f"{r['bootstrap_ci95_lo']:>+8.4f}  "
                f"{r['bootstrap_ci95_hi']:>+8.4f}  "
                f"{r['positive_signal_rate']:>9.3f}  "
                f"{'YES' if r['bootstrap_validated'] else 'no':>10}"
            )
        print()

    print(f"Headline (neg_temperature @ 25%): mean_lift={s['headline_mean_lift']:+.4f}")
    print(f"  bootstrap 95% CI lower bound: {s['headline_ci95_lo']:+.4f}")
    print(f"  positive-signal rate:          {s['headline_positive_rate']:.3f}")
    print(f"  BOOTSTRAP VALIDATED: {s['bootstrap_validated']}")
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
