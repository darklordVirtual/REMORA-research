"""Phase structure stability via bootstrap + chi re-analysis.

This experiment answers two questions:

1. STABILITY: Is the ordered/critical/disordered classification stable
   under bootstrap resampling, or does the phase split change radically
   across resamples?  We measure the bootstrap variance of the phase
   fractions and trust-score distributions per phase.

2. CHI RE-ANALYSIS: The previous chi perturbation study showed
   Spearman rho(chi, fragility) = -0.0102 globally.  This was because
   the study was run on all items regardless of phase.  The thermodynamic
   hypothesis is that chi is most predictive WITHIN the critical phase,
   where the system is near the transition point.  We re-test this by
   stratifying by phase before measuring predictive power.

Outputs
-------
  results/phase_stability_results.json

Usage
-----
    python experiments/phase_stability.py
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import statistics as st
from collections import Counter


def _spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")

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
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    den_x = sum((rx[i] - mean_x) ** 2 for i in range(n))
    den_y = sum((ry[i] - mean_y) ** 2 for i in range(n))
    den = math.sqrt(den_x * den_y)
    return num / den if den else float("nan")


def run(thermo_path: str, ablation_path: str, n_boot: int = 1000, seed: int = 42) -> dict:
    thermo = json.loads(pathlib.Path(thermo_path).read_text(encoding="utf-8"))
    ablation = json.loads(pathlib.Path(ablation_path).read_text(encoding="utf-8"))
    per_maj = {it["item_id"]: bool(it["correct"]) for it in ablation["conditions"]["B_majority"]["items"]}

    items: list[dict] = []
    for it in thermo["items"]:
        m = dict(it)
        m["majority_correct"] = per_maj.get(it["item_id"], True)
        items.append(m)
    n = len(items)

    # ── PART 1: Phase fraction stability ────────────────────────────────────
    rng = random.Random(seed)
    phase_boot: dict[str, list[float]] = {"ordered": [], "critical": [], "disordered": []}
    for _ in range(n_boot):
        boot = [items[rng.randint(0, n - 1)] for _ in range(n)]
        counts = Counter(it["phase"] for it in boot)
        for ph in phase_boot:
            phase_boot[ph].append(counts.get(ph, 0) / n)

    phase_stability: dict = {}
    for ph, fracs in phase_boot.items():
        mean = st.mean(fracs)
        sd = st.stdev(fracs)
        sorted_f = sorted(fracs)
        lo = sorted_f[int(0.025 * n_boot)]
        hi = sorted_f[int(0.975 * n_boot)]
        cv = sd / mean if mean else float("inf")
        phase_stability[ph] = {
            "observed_fraction": round(sum(1 for it in items if it["phase"] == ph) / n, 4),
            "bootstrap_mean": round(mean, 4),
            "bootstrap_sd": round(sd, 4),
            "bootstrap_ci95": [round(lo, 4), round(hi, 4)],
            "cv": round(cv, 4),
            "stable": cv < 0.25,
        }

    # ── PART 2: Per-phase Spearman rho(chi, majority_error) ─────────────────
    # Global rho was -0.0102 (uninfomative).  Does stratifying help?
    # We test chi vs correctness and chi vs trust_score per phase.
    phases = ["ordered", "critical", "disordered"]
    per_phase_analysis: dict = {}
    for ph in phases:
        ph_items = [it for it in items if it["phase"] == ph]
        if len(ph_items) < 5:
            per_phase_analysis[ph] = {"n": len(ph_items), "skipped": "too few items"}
            continue
        chi_vals = [it["susceptibility"] for it in ph_items]
        # predictors: chi -> majority error (1 = wrong)
        error_vals = [0.0 if it["majority_correct"] else 1.0 for it in ph_items]
        trust_vals = [it["trust_score"] for it in ph_items]
        eta_vals   = [it["order_parameter"] for it in ph_items]

        rho_chi_error = _spearman(chi_vals, error_vals)
        rho_chi_trust = _spearman(chi_vals, trust_vals)
        rho_eta_error = _spearman(eta_vals, error_vals)
        rho_temp_error = _spearman([-it["temperature"] for it in ph_items], [-e for e in error_vals])

        per_phase_analysis[ph] = {
            "n": len(ph_items),
            "majority_error_rate": round(sum(error_vals) / len(ph_items), 4),
            "mean_chi": round(st.mean(chi_vals), 4),
            "rho_chi_vs_majority_error": round(rho_chi_error, 4) if not math.isnan(rho_chi_error) else None,
            "rho_chi_vs_trust_score":    round(rho_chi_trust, 4) if not math.isnan(rho_chi_trust) else None,
            "rho_eta_vs_majority_error": round(rho_eta_error, 4) if not math.isnan(rho_eta_error) else None,
            "rho_neg_temp_vs_neg_error": round(rho_temp_error, 4) if not math.isnan(rho_temp_error) else None,
            "notes": (
                "chi is expected to be most predictive in critical phase near transition"
            ),
        }

    # Global comparison
    chi_vals_all = [it["susceptibility"] for it in items]
    error_vals_all = [0.0 if it["majority_correct"] else 1.0 for it in items]
    rho_global = _spearman(chi_vals_all, error_vals_all)

    # ── PART 3: Bootstrap CI on per-phase trust lift ─────────────────────────
    # At 25% coverage, how stable is the lift per phase?
    rng2 = random.Random(seed + 1)
    per_phase_lift_boot: dict[str, list[float]] = {ph: [] for ph in phases}
    pct = 0.25
    for _ in range(n_boot):
        boot = [items[rng2.randint(0, n - 1)] for _ in range(n)]
        _base = sum(1 for it in boot if it["majority_correct"]) / n  # noqa: F841
        k = max(1, int(round(n * pct)))
        # LOW temperature = trusted; ascending T sort picks most-trusted items
        top = sorted(boot, key=lambda x: x["temperature"])[:k]
        _acc = sum(1 for it in top if it["majority_correct"]) / k  # noqa: F841
        # phase of top items
        phase_counts = Counter(it["phase"] for it in top)
        for ph in phases:
            per_phase_lift_boot[ph].append(phase_counts.get(ph, 0) / k)

    per_phase_coverage_in_top25: dict = {}
    for ph in phases:
        fracs = per_phase_lift_boot[ph]
        per_phase_coverage_in_top25[ph] = {
            "mean_fraction_in_top25": round(st.mean(fracs), 4),
            "sd": round(st.stdev(fracs), 4),
        }

    return {
        "meta": {
            "experiment": "phase_stability",
            "n_items": n,
            "n_bootstrap": n_boot,
            "thermo_source": thermo_path,
            "ablation_source": ablation_path,
        },
        "phase_fraction_stability": phase_stability,
        "per_phase_chi_analysis": per_phase_analysis,
        "global_rho_chi_vs_error": round(rho_global, 4) if not math.isnan(rho_global) else None,
        "phase_composition_of_top25pct_selection": per_phase_coverage_in_top25,
        "summary": {
            "all_phases_stable": all(v["stable"] for v in phase_stability.values()),
            "critical_phase_rho_chi": per_phase_analysis.get("critical", {}).get("rho_chi_vs_majority_error"),
            "global_rho_chi": round(rho_global, 4) if not math.isnan(rho_global) else None,
        },
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thermo", default="results/thermodynamic_eval_results.json")
    parser.add_argument("--ablation", default="results/ablation_v2_canonical_results.json")
    parser.add_argument("--output", default="results/phase_stability_results.json")
    parser.add_argument("--n-boot", type=int, default=1000)
    args = parser.parse_args(argv)

    out = run(args.thermo, args.ablation, args.n_boot)
    pathlib.Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\nPhase stability (N={out['meta']['n_items']}, B={args.n_boot})")
    print(f"{'Phase':<12} {'obs_frac':>9} {'boot_mean':>10} {'CV':>7} {'CI95':>18} {'stable':>8}")
    for ph, v in out["phase_fraction_stability"].items():
        ci = v["bootstrap_ci95"]
        print(
            f"  {ph:<10} {v['observed_fraction']:>9.4f} {v['bootstrap_mean']:>10.4f} "
            f"{v['cv']:>7.4f} [{ci[0]:.3f},{ci[1]:.3f}] {'YES' if v['stable'] else 'NO':>8}"
        )

    print("\nPer-phase Spearman rho(chi, majority_error):")
    for ph, a in out["per_phase_chi_analysis"].items():
        if "skipped" in a:
            print(f"  {ph}: SKIPPED (n={a['n']})")
        else:
            rho = a["rho_chi_vs_majority_error"]
            print(f"  {ph:<12} n={a['n']:>3}  rho={rho:+.4f}  (global={out['global_rho_chi_vs_error']:+.4f})")

    print("\nPhase composition of top 25% temperature-sorted selection:")
    for ph, v in out["phase_composition_of_top25pct_selection"].items():
        print(f"  {ph:<12} mean fraction = {v['mean_fraction_in_top25']:.4f}  sd={v['sd']:.4f}")

    print(f"\nAll phases stable:      {out['summary']['all_phases_stable']}")
    print(f"Critical chi rho:       {out['summary']['critical_phase_rho_chi']}")
    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
