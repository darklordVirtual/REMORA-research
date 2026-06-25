#!/usr/bin/env python3
"""Chi iteration-utility experiment — Claim 5 empirical supplement.

Measures the utility of thermodynamic susceptibility χ as a signal for
predicting when the C_remora adaptive-routing condition helps or hurts
relative to the majority-vote baseline (B_majority) on the canonical N=302
benchmark.

This is the "C_remora χ utility" experiment referenced as
results/chi_iteration_utility_results.json.

Method
------
For every item in the canonical N=302 benchmark:
  - Retrieve χ from results/thermodynamic_eval_results.json
    (the per-item thermodynamic analysis)
  - Retrieve per-condition correctness from
    results/ablation_v2_canonical_results.json
  - Compute two binary labels:
      helped_by_c  = C_remora correct, B_majority wrong
      hurt_by_c    = C_remora wrong,   B_majority correct
  - Compute AUROC of χ for predicting each label
    (higher χ → more likely to help or hurt)

The AUROC is implemented via the Wilcoxon rank-sum formula so there is no
sklearn dependency.

Results are saved to results/chi_iteration_utility_results.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


# ── AUROC (no sklearn dependency) ────────────────────────────────────────────

def _auroc(scores: list[float], labels: list[int]) -> float:
    """Compute AUROC using the Wilcoxon rank-sum statistic.

    Returns 0.5 when there are no positive or no negative examples.
    """
    pos = [s for s, lb in zip(scores, labels) if lb == 1]
    neg = [s for s, lb in zip(scores, labels) if lb == 0]
    if not pos or not neg:
        return 0.5
    # U statistic: count (pos_score > neg_score) + 0.5*(pos_score == neg_score)
    u = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                u += 1.0
            elif p == n:
                u += 0.5
    return u / (len(pos) * len(neg))


# ── Chi-decile analysis ───────────────────────────────────────────────────────

def _decile_analysis(
    rows: list[dict],
    n_bins: int = 5,
) -> list[dict]:
    """Split rows into n_bins equal-frequency chi bins and summarise each."""
    sorted_rows = sorted(rows, key=lambda r: r["chi"])
    bin_size = len(sorted_rows) // n_bins
    bins = []
    for i in range(n_bins):
        start = i * bin_size
        end = (i + 1) * bin_size if i < n_bins - 1 else len(sorted_rows)
        chunk = sorted_rows[start:end]
        helped = sum(1 for r in chunk if r["helped"])
        hurt = sum(1 for r in chunk if r["hurt"])
        bins.append({
            "bin": i + 1,
            "n": len(chunk),
            "chi_min": round(min(r["chi"] for r in chunk), 6),
            "chi_max": round(max(r["chi"] for r in chunk), 6),
            "chi_mean": round(sum(r["chi"] for r in chunk) / len(chunk), 6),
            "help_rate": round(helped / len(chunk), 4) if chunk else 0.0,
            "hurt_rate": round(hurt / len(chunk), 4) if chunk else 0.0,
            "n_helped": helped,
            "n_hurt": hurt,
        })
    return bins


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute chi iteration-utility AUCs for C_remora vs majority"
    )
    parser.add_argument(
        "--thermo",
        default=str(ROOT / "results" / "thermodynamic_eval_results.json"),
        help="Path to thermodynamic_eval_results.json",
    )
    parser.add_argument(
        "--ablation",
        default=str(ROOT / "results" / "ablation_v2_canonical_results.json"),
        help="Path to ablation_v2_canonical_results.json",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "results" / "chi_iteration_utility_results.json"),
        help="Output path for chi_iteration_utility_results.json",
    )
    parser.add_argument("--n-bins", type=int, default=5)
    args = parser.parse_args()

    # Load artifacts
    thermo_data = json.loads(Path(args.thermo).read_text(encoding="utf-8"))
    abl_data = json.loads(Path(args.ablation).read_text(encoding="utf-8"))

    # Build chi index keyed by item_id
    chi_index: dict[str, dict] = {
        it["item_id"]: it
        for it in thermo_data["items"]
    }

    # Build condition indices
    b_index: dict[str, bool] = {
        it["item_id"]: bool(it["correct"])
        for it in abl_data["conditions"]["B_majority"]["items"]
    }
    c_index: dict[str, bool] = {
        it["item_id"]: bool(it["correct"])
        for it in abl_data["conditions"]["C_remora"]["items"]
    }

    # Build per-item records
    rows: list[dict] = []
    for item_id, thermo_item in chi_index.items():
        b_correct = b_index.get(item_id, False)
        c_correct = c_index.get(item_id, False)
        helped = c_correct and not b_correct   # C_remora correct, majority wrong
        hurt = not c_correct and b_correct     # majority correct, C_remora wrong
        rows.append({
            "item_id": item_id,
            "chi": thermo_item["susceptibility"],
            "phase": thermo_item["phase"],
            "temperature": thermo_item["temperature"],
            "trust_score": thermo_item["trust_score"],
            "b_correct": b_correct,
            "c_correct": c_correct,
            "helped": helped,
            "hurt": hurt,
        })

    n_total = len(rows)
    n_helped = sum(1 for r in rows if r["helped"])
    n_hurt = sum(1 for r in rows if r["hurt"])
    b_accuracy = sum(1 for r in rows if r["b_correct"]) / n_total
    c_accuracy = sum(1 for r in rows if r["c_correct"]) / n_total

    # AUROC
    chi_scores = [r["chi"] for r in rows]
    help_labels = [int(r["helped"]) for r in rows]
    hurt_labels = [int(r["hurt"]) for r in rows]

    auc_help = _auroc(chi_scores, help_labels)
    auc_hurt = _auroc(chi_scores, hurt_labels)

    # Per-phase breakdown
    phases = sorted({r["phase"] for r in rows})
    per_phase: dict[str, dict] = {}
    for ph in phases:
        ph_rows = [r for r in rows if r["phase"] == ph]
        ph_helped = sum(1 for r in ph_rows if r["helped"])
        ph_hurt = sum(1 for r in ph_rows if r["hurt"])
        per_phase[ph] = {
            "n": len(ph_rows),
            "n_helped": ph_helped,
            "n_hurt": ph_hurt,
            "help_rate": round(ph_helped / len(ph_rows), 4) if ph_rows else 0.0,
            "hurt_rate": round(ph_hurt / len(ph_rows), 4) if ph_rows else 0.0,
        }

    # Chi-decile analysis
    chi_bins = _decile_analysis(rows, n_bins=args.n_bins)

    # Spearman rho(chi, helped) and rho(chi, hurt)
    def _spearman(x: list[float], y: list[float]) -> float:
        """Spearman rank correlation."""
        n = len(x)
        if n < 2:
            return 0.0

        def _ranks(vals: list[float]) -> list[float]:
            sorted_vals = sorted(range(n), key=lambda i: vals[i])
            ranks = [0.0] * n
            i = 0
            while i < n:
                j = i
                while j < n and vals[sorted_vals[j]] == vals[sorted_vals[i]]:
                    j += 1
                mean_rank = (i + j - 1) / 2.0
                for k in range(i, j):
                    ranks[sorted_vals[k]] = mean_rank
                i = j
            return ranks

        rx = _ranks(x)
        ry = _ranks(y)
        mean_rx = sum(rx) / n
        mean_ry = sum(ry) / n
        cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
        std_rx = (sum((r - mean_rx) ** 2 for r in rx) ** 0.5)
        std_ry = (sum((r - mean_ry) ** 2 for r in ry) ** 0.5)
        if std_rx == 0 or std_ry == 0:
            return 0.0
        return cov / (std_rx * std_ry)

    rho_help = _spearman(chi_scores, [float(v) for v in help_labels])
    rho_hurt = _spearman(chi_scores, [float(v) for v in hurt_labels])

    # Interpretation
    if abs(auc_help - 0.5) < 0.05 and abs(auc_hurt - 0.5) < 0.05:
        interpretation = (
            "Chi has negligible AUROC for both help and hurt signals "
            "(both near 0.5 baseline). Chi is not a reliable predictor "
            "of C_remora iteration utility on N=302."
        )
    elif auc_hurt > 0.55:
        interpretation = (
            "Chi has modest AUROC for predicting C_remora hurt-cases, "
            "suggesting high-chi items are marginally more likely to be "
            "hurt by adaptive iteration."
        )
    else:
        interpretation = (
            "Chi shows partial utility as an iteration signal on one or both "
            "labels; further replication is needed."
        )

    result = {
        "meta": {
            "experiment": "chi_iteration_utility",
            "condition_compared": "C_remora vs B_majority",
            "n_items": n_total,
            "thermo_artifact": args.thermo,
            "ablation_artifact": args.ablation,
        },
        "summary": {
            "n_items": n_total,
            "n_helped": n_helped,
            "n_hurt": n_hurt,
            "b_majority_accuracy": round(b_accuracy, 4),
            "c_remora_accuracy": round(c_accuracy, 4),
            "auc_help": round(auc_help, 4),
            "auc_hurt": round(auc_hurt, 4),
            "rho_chi_help": round(rho_help, 4),
            "rho_chi_hurt": round(rho_hurt, 4),
            "interpretation": interpretation,
        },
        "per_phase": per_phase,
        "chi_bins": chi_bins,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"  n_items={n_total}, n_helped={n_helped}, n_hurt={n_hurt}")
    print(f"  B_majority accuracy={b_accuracy:.4f}, C_remora accuracy={c_accuracy:.4f}")
    print(f"  auc_help={auc_help:.4f}, auc_hurt={auc_hurt:.4f}")
    print(f"  rho(chi, help)={rho_help:.4f}, rho(chi, hurt)={rho_hurt:.4f}")
    print(f"  Interpretation: {interpretation}")


if __name__ == "__main__":
    main()
