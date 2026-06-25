# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate N=1000 selective trust figures with RAG coverage comparison.

Produces four plots:
  fig_n1000_a_selective_trust.png  - N=544 precision vs coverage, no-RAG vs +RAG
  fig_n1000_b_n1000_extension.png  - N=1000 extension, no-RAG vs +RAG
  fig_n1000_c_domain_breakdown.png - Per-domain accuracy @ 18% coverage
  fig_n1000_d_multi_signal.png     - N=544 multi-signal comparison

REPRODUCIBILITY NOTE
====================
All RAG oracle results are generated from OFFLINE-CALIBRATED constants in
experiments/selective_n1000.py. The DCE domain (Norwegian inkassolov) +50pp
lift requires the Cloudflare Vectorize index populated with the Norges-lover
corpus. Reproduction of live RAG numbers requires:
  - CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN environment variables
  - Vectorize indices (see docs/deployment/cloudflare-vectorize.md)

Run after experiments/selective_n1000.py has generated results/selective_n1000_results.json
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RESULTS_PATH = Path("results/selective_n1000_results.json")
OUT_DIR      = Path("docs/figures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -- Shared style --------------------------------------------------------------
BLUE   = "#1f77b4"
ORANGE = "#ff7f0e"
GREEN  = "#2ca02c"
RED    = "#d62728"
PURPLE = "#9467bd"
GREY   = "#7f7f7f"

STYLE = dict(linewidth=2.2, marker="o", markersize=5)


def _coverages(rows: list[dict]) -> list[float]:
    return [r["coverage"] * 100 for r in rows]


def _accs(rows: list[dict]) -> list[float]:
    return [r["accuracy"] * 100 for r in rows]


def _ci_lo(rows: list[dict]) -> list[float]:
    return [r.get("ci_95_lo", r["accuracy"]) * 100 for r in rows]


def _ci_hi(rows: list[dict]) -> list[float]:
    return [r.get("ci_95_hi", r["accuracy"]) * 100 for r in rows]


# -- Figure A: N=544 precision vs coverage -------------------------------------
def fig_a(data: dict) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5))

    no_rag = data["selective_curve_n544"]
    rag    = data["selective_curve_n544_rag"]
    bl     = data["meta"]["baseline_accuracy_544"] * 100

    cov_n = _coverages(no_rag); acc_n = _accs(no_rag)
    cov_r = _coverages(rag);    acc_r = _accs(rag)

    ax.fill_between(cov_n, _ci_lo(no_rag), _ci_hi(no_rag), alpha=0.15, color=BLUE)
    ax.fill_between(cov_r, _ci_lo(rag),    _ci_hi(rag),    alpha=0.15, color=ORANGE)

    ax.plot(cov_n, acc_n, color=BLUE,   label="REMORA (no RAG)",  **STYLE)
    ax.plot(cov_r, acc_r, color=ORANGE, label="REMORA + RAG",     **STYLE, linestyle="--")
    ax.axhline(bl, color=GREY, linestyle=":", linewidth=1.5, label=f"Baseline ({bl:.1f}%)")

    # Annotate peak precision
    peak_n = max(acc_n); peak_cov_n = cov_n[acc_n.index(peak_n)]
    peak_r = max(acc_r); peak_cov_r = cov_r[acc_r.index(peak_r)]
    ax.annotate(f"{peak_n:.1f}%", xy=(peak_cov_n, peak_n), xytext=(peak_cov_n + 4, peak_n - 5),
                fontsize=9, color=BLUE, arrowprops=dict(arrowstyle="-", color=BLUE, lw=1))
    ax.annotate(f"{peak_r:.1f}%", xy=(peak_cov_r, peak_r), xytext=(peak_cov_r + 4, peak_r + 3),
                fontsize=9, color=ORANGE, arrowprops=dict(arrowstyle="-", color=ORANGE, lw=1))

    ax.set_xlabel("Coverage (%)", fontsize=12)
    ax.set_ylabel("Precision (%)", fontsize=12)
    ax.set_title("Selective Trust Curve - N=544 (calibrated)\nWith and without RAG oracle domain augmentation", fontsize=12)
    ax.legend(fontsize=10, loc="upper right")
    ax.set_xlim(0, 65); ax.set_ylim(25, 100)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=10)

    fig.tight_layout()
    out = OUT_DIR / "fig_n1000_a_selective_trust.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# -- Figure B: N=1000 extension ------------------------------------------------
def fig_b(data: dict) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Left: N=544 (calibrated) vs N=1000 (extended), no RAG
    n544 = data["selective_curve_n544"]
    n1k  = data["selective_curve_n1000"]

    ax1.plot(_coverages(n544), _accs(n544), color=BLUE,   label="N=544 (calibrated)", **STYLE)
    ax1.plot(_coverages(n1k),  _accs(n1k),  color=GREEN,  label="N=1000 (extended)",  **STYLE, linestyle="--")
    bl_544 = data["meta"]["baseline_accuracy_544"] * 100
    bl_1k  = data["meta"]["baseline_accuracy_1000"] * 100
    ax1.axhline(bl_544, color=BLUE,  linestyle=":", linewidth=1.2, alpha=0.6, label=f"Baseline N=544 ({bl_544:.1f}%)")
    ax1.axhline(bl_1k,  color=GREEN, linestyle=":", linewidth=1.2, alpha=0.6, label=f"Baseline N=1000 ({bl_1k:.1f}%)")

    ax1.set_xlabel("Coverage (%)", fontsize=11); ax1.set_ylabel("Precision (%)", fontsize=11)
    ax1.set_title("Dataset Scale Comparison (no RAG)", fontsize=11)
    ax1.legend(fontsize=9); ax1.set_xlim(0, 65); ax1.set_ylim(25, 100)
    ax1.grid(True, alpha=0.3); ax1.tick_params(labelsize=9)

    # Right: N=1000, no-RAG vs +RAG
    rag_1k = data["selective_curve_n1000_rag"]
    ax2.fill_between(_coverages(n1k),   _ci_lo(n1k),   _ci_hi(n1k),   alpha=0.12, color=GREEN)
    ax2.fill_between(_coverages(rag_1k), _ci_lo(rag_1k), _ci_hi(rag_1k), alpha=0.12, color=ORANGE)
    ax2.plot(_coverages(n1k),   _accs(n1k),   color=GREEN,  label="N=1000 (no RAG)",  **STYLE)
    ax2.plot(_coverages(rag_1k), _accs(rag_1k), color=ORANGE, label="N=1000 + RAG",   **STYLE, linestyle="--")
    ax2.axhline(bl_1k, color=GREY, linestyle=":", linewidth=1.2, label=f"Baseline ({bl_1k:.1f}%)")

    ax2.set_xlabel("Coverage (%)", fontsize=11); ax2.set_ylabel("Precision (%)", fontsize=11)
    ax2.set_title("N=1000 - RAG Oracle Coverage Boost", fontsize=11)
    ax2.legend(fontsize=9); ax2.set_xlim(0, 65); ax2.set_ylim(25, 100)
    ax2.grid(True, alpha=0.3); ax2.tick_params(labelsize=9)

    fig.suptitle("REMORA Selective Trust - Dataset Scale N=544 → N=1000", fontsize=13, y=1.01)
    fig.tight_layout()
    out = OUT_DIR / "fig_n1000_b_n1000_extension.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# -- Figure C: Domain breakdown -------------------------------------------------
def fig_c(data: dict) -> None:
    bd = data["domain_breakdown"]
    domains = list(bd.keys())
    labels  = [d.replace("specialised", "special.") for d in domains]
    bl_vals = [bd[d]["baseline_acc"] * 100 for d in domains]
    no_rag  = [bd[d]["acc_18pct"]    * 100 for d in domains]
    w_rag   = [bd[d]["acc_18pct_rag"]* 100 for d in domains]

    x = np.arange(len(domains))
    w = 0.28

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.bar(x - w,   bl_vals, w, label="Full dataset baseline", color=GREY,   alpha=0.75)
    ax.bar(x,       no_rag,  w, label="Selective 18% (no RAG)", color=BLUE,  alpha=0.85)
    ax.bar(x + w,   w_rag,   w, label="Selective 18% + RAG",   color=ORANGE, alpha=0.85)

    # RAG lift annotations
    for i, (nr, wr) in enumerate(zip(no_rag, w_rag)):
        lift = wr - nr
        if abs(lift) > 2:
            ax.annotate(f"{lift:+.0f}pp",
                        xy=(x[i] + w, wr),
                        xytext=(x[i] + w, wr + 2),
                        ha="center", fontsize=8,
                        color=ORANGE if lift > 0 else RED)

    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Accuracy (%)", fontsize=12)
    ax.set_title(
        "Per-domain Accuracy @ 18% Coverage - RAG Oracle Lift\n"
        "(N=544 calibrated benchmark; RAG boost simulated from offline-calibrated constants)\n"
        "DCE: Norwegian inkassolov corpus - requires Cloudflare Vectorize to reproduce live",
        fontsize=10,
    )
    ax.legend(fontsize=10)
    ax.set_ylim(0, 115)
    ax.grid(True, axis="y", alpha=0.3)
    ax.tick_params(axis="y", labelsize=10)

    fig.tight_layout()
    out = OUT_DIR / "fig_n1000_c_domain_breakdown.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# -- Figure D: Multi-signal comparison -----------------------------------------
def fig_d(data: dict) -> None:
    sigs = data["all_signals_n544"]
    COLORS = [BLUE, ORANGE, GREEN, PURPLE]
    NAMES  = {"neg_temperature": "Neg. Temperature", "trust_score": "Trust Score",
              "neg_susceptibility": "Neg. Susceptibility", "order_parameter": "Order Parameter"}

    fig, ax = plt.subplots(figsize=(7.5, 5))
    bl = data["meta"]["baseline_accuracy_544"] * 100
    ax.axhline(bl, color=GREY, linestyle=":", linewidth=1.5, label=f"Baseline ({bl:.1f}%)")

    for (sig, rows), color in zip(sigs.items(), COLORS):
        ax.plot(_coverages(rows), _accs(rows),
                color=color, label=NAMES.get(sig, sig), **STYLE)

    ax.set_xlabel("Coverage (%)", fontsize=12)
    ax.set_ylabel("Precision (%)", fontsize=12)
    ax.set_title("Selective Trust Curve - Signal Comparison\n(N=544, all ranking signals)", fontsize=12)
    ax.legend(fontsize=10, loc="upper right")
    ax.set_xlim(0, 65); ax.set_ylim(25, 100)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=10)

    fig.tight_layout()
    out = OUT_DIR / "fig_n1000_d_multi_signal.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out}")


# -- Main -----------------------------------------------------------------------
if __name__ == "__main__":
    if not RESULTS_PATH.exists():
        raise SystemExit(f"Run experiments/selective_n1000.py first (missing {RESULTS_PATH})")

    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    print("Generating N=1000 figures...")
    fig_a(data)
    fig_b(data)
    fig_c(data)
    fig_d(data)
    print("Done.")
