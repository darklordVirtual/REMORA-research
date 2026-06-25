# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate benchmark figures embedded in README.md.

Outputs four PNG files to docs/figures/:
  toolcall_v1_comparison.png   - v1 accuracy + utility (unsafe rate is 0 for all)
  toolcall_v2_unsafe.png       - v2 unsafe execution rate (key safety result)
  toolcall_v2_accuracy.png     - v2 accuracy comparison
  toolcall_v2_utility.png      - v2 mean utility (includes negative values)
  toolcall_v2_combined.png     - v2 all three metrics side by side

Run from the repo root:
  python scripts/generate_readme_figures.py
"""
from __future__ import annotations

import os

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "figures")
os.makedirs(OUT_DIR, exist_ok=True)

# -- Colour palette ------------------------------------------------------------
BASELINE_COLOR = "#9EAFC2"      # muted blue-grey for baselines
REMORA_TEMP_COLOR = "#5B9BD5"   # medium blue for temperature gate
REMORA_FULL_COLOR = "#1A5276"   # dark navy for full policy gate (hero)
TEXT_COLOR = "#1C2833"
GRID_COLOR = "#E8ECF0"
BACKGROUND = "#FAFBFC"

DPI = 150
FONT_FAMILY = "DejaVu Sans"

SHORT_LABELS = [
    "Single\nModel",
    "Majority\nVote",
    "Self-\nConsistency",
    "Verifier",
    "REMORA\nTemp Gate",
    "REMORA\nFull Policy",
]

BAR_COLORS = [
    BASELINE_COLOR,
    BASELINE_COLOR,
    BASELINE_COLOR,
    BASELINE_COLOR,
    REMORA_TEMP_COLOR,
    REMORA_FULL_COLOR,
]

# -- v1 data -------------------------------------------------------------------
V1_ACCURACY = [0.6190, 0.8571, 0.8571, 0.6905, 0.9524, 0.7619]
V1_UTILITY  = [0.5167, 0.6286, 0.6286, 0.5452, 0.6762, 0.5690]

# -- v2 data -------------------------------------------------------------------
V2_UNSAFE   = [0.20, 0.10, 0.10, 0.20, 0.10, 0.00]
V2_UTILITY  = [-0.25, 0.00, 0.00, -0.25, 0.27, 0.62]
V2_ACCURACY = [0.20, 0.30, 0.30, 0.20, 0.70, 0.90]

X = np.arange(len(SHORT_LABELS))
BAR_WIDTH = 0.6


def _style_ax(ax: plt.Axes, title: str, ylabel: str, ylim: tuple) -> None:
    ax.set_title(title, fontsize=13, fontweight="bold", color=TEXT_COLOR, pad=10)
    ax.set_ylabel(ylabel, fontsize=10, color=TEXT_COLOR)
    ax.set_ylim(*ylim)
    ax.set_xticks(X)
    ax.set_xticklabels(SHORT_LABELS, fontsize=9, color=TEXT_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.set_facecolor(BACKGROUND)
    ax.tick_params(axis="y", colors=TEXT_COLOR, labelsize=9)
    ax.tick_params(axis="x", colors=TEXT_COLOR, length=0)


def _add_value_labels(ax: plt.Axes, bars, fmt: str = "{:.0%}", offset_frac: float = 0.015, ylim_range: float = 1.0) -> None:
    offset = ylim_range * offset_frac
    for bar in bars:
        h = bar.get_height()
        va = "bottom" if h >= 0 else "top"
        y = h + (offset if h >= 0 else -offset)
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            y,
            fmt.format(h),
            ha="center",
            va=va,
            fontsize=8,
            color=TEXT_COLOR,
            fontweight="bold" if bar.get_facecolor()[:3] == tuple(int(REMORA_FULL_COLOR.lstrip("#")[i:i+2], 16)/255 for i in (0, 2, 4)) else "normal",
        )


def _legend(ax: plt.Axes) -> None:
    patches = [
        mpatches.Patch(color=BASELINE_COLOR, label="Baseline heuristics"),
        mpatches.Patch(color=REMORA_TEMP_COLOR, label="REMORA temperature gate"),
        mpatches.Patch(color=REMORA_FULL_COLOR, label="REMORA full policy gate"),
    ]
    ax.legend(handles=patches, fontsize=8, loc="upper left",
              framealpha=0.9, edgecolor=GRID_COLOR)


# -- Figure 1: v1 accuracy + utility ------------------------------------------
def make_v1_comparison() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), facecolor=BACKGROUND)
    fig.suptitle("Tool-Call Benchmark v1 (252 tasks) - All baselines safe at zero unsafe rate",
                 fontsize=11, color=TEXT_COLOR, y=1.01)

    for ax, values, title, ylabel in [
        (axes[0], V1_ACCURACY, "Accuracy", "Accuracy"),
        (axes[1], V1_UTILITY,  "Mean Utility", "Mean utility"),
    ]:
        bars = ax.bar(X, values, width=BAR_WIDTH, color=BAR_COLORS, zorder=3, linewidth=0)
        _style_ax(ax, title, ylabel, ylim=(0.0, 1.15))
        _add_value_labels(ax, bars, fmt="{:.1%}", ylim_range=1.15)

    _legend(axes[0])
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "toolcall_v1_comparison.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    print(f"Saved {path}")


# -- Figure 2: v2 unsafe execution rate ---------------------------------------
def make_v2_unsafe() -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=BACKGROUND)
    bars = ax.bar(X, V2_UNSAFE, width=BAR_WIDTH, color=BAR_COLORS, zorder=3, linewidth=0)
    _style_ax(ax, "Tool-Call Benchmark v2 - Unsafe Execution Rate (lower is better)",
              "Unsafe execution rate", ylim=(0.0, 0.28))

    for bar, val in zip(bars, V2_UNSAFE):
        label = "0% ✓" if val == 0.0 else f"{val:.0%}"
        color = "#117A65" if val == 0.0 else "#922B21"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            val + 0.006,
            label,
            ha="center", va="bottom", fontsize=9,
            color=color, fontweight="bold",
        )

    # Annotate the improvement arrow
    ax.annotate(
        "-10 pp\nvs majority vote\np < 0.0001",
        xy=(X[1], V2_UNSAFE[1]), xytext=(X[5] - 0.3, 0.18),
        arrowprops=dict(arrowstyle="-|>", color=TEXT_COLOR, lw=1.2),
        fontsize=8, color=TEXT_COLOR, ha="center",
    )

    _legend(ax)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "toolcall_v2_unsafe.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    print(f"Saved {path}")


# -- Figure 3: v2 accuracy -----------------------------------------------------
def make_v2_accuracy() -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=BACKGROUND)
    bars = ax.bar(X, V2_ACCURACY, width=BAR_WIDTH, color=BAR_COLORS, zorder=3, linewidth=0)
    _style_ax(ax, "Tool-Call Benchmark v2 - Accuracy (higher is better)",
              "Accuracy", ylim=(0.0, 1.1))
    _add_value_labels(ax, bars, fmt="{:.0%}", ylim_range=1.1)
    _legend(ax)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "toolcall_v2_accuracy.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    print(f"Saved {path}")


# -- Figure 4: v2 utility (handles negatives) ---------------------------------
def make_v2_utility() -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=BACKGROUND)
    bars = ax.bar(X, V2_UTILITY, width=BAR_WIDTH, color=BAR_COLORS, zorder=3, linewidth=0)
    ax.axhline(0, color=TEXT_COLOR, linewidth=0.8, zorder=4)
    _style_ax(ax, "Tool-Call Benchmark v2 - Mean Utility (higher is better)",
              "Mean utility", ylim=(-0.40, 0.80))
    _add_value_labels(ax, bars, fmt="{:+.2f}", offset_frac=0.02, ylim_range=1.2)
    _legend(ax)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "toolcall_v2_utility.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    print(f"Saved {path}")


# -- Figure 5: v2 combined (3-panel) ------------------------------------------
def make_v2_combined() -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), facecolor=BACKGROUND)
    fig.suptitle("Tool-Call Benchmark v2 (700 adversarial tasks)",
                 fontsize=13, fontweight="bold", color=TEXT_COLOR, y=1.02)

    panels = [
        (axes[0], V2_UNSAFE,   "Unsafe Execution Rate\n(lower is better)",   "Rate", (0.0, 0.28),  "{:.0%}"),
        (axes[1], V2_ACCURACY, "Accuracy\n(higher is better)",                "Accuracy", (0.0, 1.1), "{:.0%}"),
        (axes[2], V2_UTILITY,  "Mean Utility\n(higher is better)",            "Mean utility", (-0.40, 0.80), "{:+.2f}"),
    ]

    for ax, values, title, ylabel, ylim, fmt in panels:
        bars = ax.bar(X, values, width=BAR_WIDTH, color=BAR_COLORS, zorder=3, linewidth=0)
        _style_ax(ax, title, ylabel, ylim)
        if ax is axes[2]:
            ax.axhline(0, color=TEXT_COLOR, linewidth=0.8, zorder=4)
        _add_value_labels(ax, bars, fmt=fmt, ylim_range=ylim[1] - ylim[0])

    # Annotate unsafe rate panel
    ax0 = axes[0]
    ax0.text(X[5], 0.003, "0% ✓", ha="center", va="bottom",
             fontsize=9, color="#117A65", fontweight="bold")

    _legend(axes[0])
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "toolcall_v2_combined.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    print(f"Saved {path}")


# -- Figure 6: Selective trust - N302 and N500 side by side -------------------
def make_selective_trust_comparison() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), facecolor=BACKGROUND)
    fig.suptitle("Selective Acceptance: Accuracy vs Coverage",
                 fontsize=13, fontweight="bold", color=TEXT_COLOR, y=1.02)

    # N=302 data
    n302_labels = ["Top 20%", "Top 25%\n(optimal)", "Top 30%"]
    n302_acc    = [0.933, 0.947, 0.923]
    n302_base   = 0.828

    # N500 data
    n500_labels = ["Top 10%", "Top 15%", "Top 18%\n(optimal)", "Top 20%"]
    n500_acc    = [0.815, 0.866, 0.888, 0.862]
    n500_base   = 0.4118

    for ax, labels, accs, baseline, title, note in [
        (axes[0], n302_labels, n302_acc, n302_base,
         "N=302  (majority baseline: 82.8%)",
         "p = 0.0018, bootstrap confirmed"),
        (axes[1], n500_labels, n500_acc, n500_base,
         "N500 - 544 items  (majority baseline: 41.18%)",
         "+47.6 pp at top 18%"),
    ]:
        x = np.arange(len(labels))
        colors = [REMORA_FULL_COLOR if "optimal" in lbl else REMORA_TEMP_COLOR for lbl in labels]
        bars = ax.bar(x, accs, width=0.5, color=colors, zorder=3, linewidth=0)
        ax.axhline(baseline, color="#E74C3C", linewidth=1.5, linestyle="--", zorder=4,
                   label=f"Majority baseline ({baseline:.2%})")
        ax.set_title(title, fontsize=11, fontweight="bold", color=TEXT_COLOR, pad=8)
        ax.set_ylabel("Accuracy", fontsize=10, color=TEXT_COLOR)
        ax.set_ylim(0, 1.08)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9, color=TEXT_COLOR)
        ax.yaxis.grid(True, color=GRID_COLOR, linewidth=1.0, zorder=0)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(GRID_COLOR)
        ax.spines["bottom"].set_color(GRID_COLOR)
        ax.set_facecolor(BACKGROUND)
        ax.tick_params(axis="y", colors=TEXT_COLOR, labelsize=9)
        ax.tick_params(axis="x", colors=TEXT_COLOR, length=0)
        for bar, val in zip(bars, accs):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 0.01,
                    f"{val:.1%}", ha="center", va="bottom", fontsize=9, color=TEXT_COLOR, fontweight="bold")
        ax.legend(fontsize=8, loc="lower right", framealpha=0.9, edgecolor=GRID_COLOR)
        ax.text(0.98, 0.05, note, transform=ax.transAxes,
                fontsize=7.5, color="#555", ha="right", va="bottom", style="italic")

    patches = [
        mpatches.Patch(color=REMORA_FULL_COLOR, label="Optimal threshold"),
        mpatches.Patch(color=REMORA_TEMP_COLOR, label="Other thresholds"),
    ]
    axes[0].legend(handles=patches + [
        plt.Line2D([0], [0], color="#E74C3C", linewidth=1.5, linestyle="--", label="Majority baseline (82.8%)")
    ], fontsize=8, loc="lower right", framealpha=0.9, edgecolor=GRID_COLOR)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, "selective_trust_comparison.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    print(f"Saved {path}")


# -- Figure 7: Phase accuracy --------------------------------------------------
def make_phase_accuracy() -> None:
    phases = ["Ordered\n(strong agreement)", "Critical\n(partial agreement)", "Disordered\n(low agreement)"]
    counts = [99, 32, 413]
    accs   = [0.869, 0.625, 0.286]
    colors = ["#1A5276", "#5B9BD5", "#9EAFC2"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), facecolor=BACKGROUND)
    fig.suptitle("Thermodynamic Phase Classification - N500 (544 items)",
                 fontsize=12, fontweight="bold", color=TEXT_COLOR, y=1.02)

    # Left: accuracy by phase
    ax = axes[0]
    bars = ax.bar(range(3), accs, width=0.5, color=colors, zorder=3, linewidth=0)
    ax.set_title("Accuracy by Phase", fontsize=11, fontweight="bold", color=TEXT_COLOR)
    ax.set_ylabel("Accuracy", fontsize=10, color=TEXT_COLOR)
    ax.set_ylim(0, 1.05)
    ax.set_xticks(range(3))
    ax.set_xticklabels(phases, fontsize=9, color=TEXT_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.set_facecolor(BACKGROUND)
    ax.tick_params(colors=TEXT_COLOR, length=0)
    for bar, val in zip(bars, accs):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.01,
                f"{val:.1%}", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR, fontweight="bold")

    # Right: distribution of questions by phase
    ax2 = axes[1]
    wedges, texts, autotexts = ax2.pie(
        counts, labels=phases, colors=colors,
        autopct=lambda p: f"{p:.1f}%\n({int(round(p/100*sum(counts)))})",
        startangle=140, pctdistance=0.7,
        wedgeprops=dict(linewidth=1.5, edgecolor="white"),
    )
    for t in texts:
        t.set_fontsize(9)
        t.set_color(TEXT_COLOR)
    for at in autotexts:
        at.set_fontsize(8.5)
        at.set_color("white")
        at.set_fontweight("bold")
    ax2.set_title("Question Distribution by Phase", fontsize=11, fontweight="bold", color=TEXT_COLOR)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, "phase_accuracy.png")
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    print(f"Saved {path}")


if __name__ == "__main__":
    make_v1_comparison()
    make_v2_unsafe()
    make_v2_accuracy()
    make_v2_utility()
    make_v2_combined()
    make_selective_trust_comparison()
    make_phase_accuracy()
    print("All figures saved to docs/figures/")
