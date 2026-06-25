#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Generate an animated GIF demonstrating REMORA's citation verification pipeline.
Replaces the static asker_case_comparison.png with a cinematic animation.

Output: artifacts/use-cases/remora_demo.gif
"""
from __future__ import annotations
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import FancyBboxPatch
import numpy as np

OUT = Path(__file__).parent.parent / "artifacts" / "use-cases"
OUT.mkdir(parents=True, exist_ok=True)

BG     = "#0F172A"
PANEL  = "#1E293B"
BORDER = "#334155"
WHITE  = "#F8FAFC"
GRAY   = "#64748B"
GREEN  = "#34D399"
RED    = "#F87171"
BLUE   = "#38BDF8"
ORANGE = "#FB923C"
YELLOW = "#FCD34D"
DARK_RED = "#450A0A"

plt.rcParams["font.family"] = "DejaVu Sans"

TOTAL_FRAMES = 120  # ~8 seconds at 15fps


def ease_in_out(t: float) -> float:
    """Smooth easing for animations."""
    return t * t * (3 - 2 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * ease_in_out(np.clip(t, 0, 1))


def make_frame(ax, frame: int) -> None:
    ax.clear()
    ax.set_facecolor(BG)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 10)
    ax.axis("off")

    t_total = frame / TOTAL_FRAMES

    # -- Phase 1 (0-15%): Title + letter appears ----------------------------
    if t_total < 0.15:
        t = t_total / 0.15
        alpha = ease_in_out(t)

        ax.text(7, 9.3, "REMORA + DCE", ha="center", color=BLUE,
                fontsize=20, fontweight="bold", alpha=alpha)
        ax.text(7, 8.75, "Norwegian Legal Citation Verification",
                ha="center", color=WHITE, fontsize=13, alpha=alpha * 0.8)

        ax.add_patch(FancyBboxPatch((0.5, 3.5), 13, 4.8,
            boxstyle="round,pad=0.1",
            facecolor=PANEL, edgecolor=GRAY, lw=1.5,
            alpha=alpha * 0.6))
        ax.text(7, 7.8, "Saksfremlegg - Asker kommune (April 2026)",
                ha="center", color=YELLOW, fontsize=10, fontweight="bold",
                alpha=alpha * 0.7)

        letter_lines = [
            "Vi viser til Høyesteretts dom HR-2015-2386-A der retten fastslo at",
            "offentlige myndigheters utøvelse av eierrådighet ikke i seg selv",
            "utgjør et inngrep i ytringsfriheten etter EMK artikkel 10.",
            "",
            "Videre fremgår det av HR-2014-2288-A og HR-2020-2135-A at kommunen",
            "har adgang til å formalisere okkupasjonen gjennom leiekontrakt.",
        ]
        for i, line in enumerate(letter_lines):
            ax.text(0.8, 7.2 - i * 0.55, line,
                    color=GRAY, fontsize=8.5, alpha=alpha * 0.7)

        ax.text(7, 0.5, "Real case documented by VG, 7 May 2026",
                ha="center", color=GRAY, fontsize=9, alpha=alpha * 0.5,
                style="italic")

    # -- Phase 2 (15-30%): Citations highlight and float up ----------------
    elif t_total < 0.30:
        t = (t_total - 0.15) / 0.15

        # Background letter (faded)
        ax.add_patch(FancyBboxPatch((0.5, 3.5), 13, 4.8,
            boxstyle="round,pad=0.1",
            facecolor=PANEL, edgecolor=BORDER, lw=1.5, alpha=0.4))

        letter_lines = [
            "Vi viser til Høyesteretts dom HR-2015-2386-A der retten fastslo at",
            "offentlige myndigheters utøvelse av eierrådighet ikke i seg selv",
            "",
            "Videre fremgår det av HR-2014-2288-A og HR-2020-2135-A at kommunen",
            "har adgang til å formalisere okkupasjonen gjennom leiekontrakt.",
        ]
        for i, line in enumerate(letter_lines):
            ax.text(0.8, 7.2 - i * 0.55, line, color=GRAY, fontsize=8.5, alpha=0.4)

        ax.text(7, 9.3, "Step 1 - Extracting legal citations",
                ha="center", color=BLUE, fontsize=14, fontweight="bold")

        # Citations emerging from the letter
        citations = ["HR-2015-2386-A", "HR-2014-2288-A", "HR-2020-2135-A"]
        for i, cit in enumerate(citations):
            alpha_cit = ease_in_out(np.clip(t * 3 - i * 0.5, 0, 1))
            y_target  = 6.0 - i * 1.3
            y_start   = 7.0 - i * 0.55
            y_pos     = lerp(y_start, y_target, t)
            x_pos     = lerp(0.8, 1.0 + i * 4.2, t)

            if alpha_cit > 0:
                ax.add_patch(FancyBboxPatch((x_pos, y_pos - 0.3), 3.8, 0.7,
                    boxstyle="round,pad=0.05",
                    facecolor=DARK_RED, edgecolor=YELLOW, lw=2,
                    alpha=alpha_cit))
                ax.text(x_pos + 1.9, y_pos + 0.05, cit,
                        ha="center", color=YELLOW, fontsize=11,
                        fontweight="bold", alpha=alpha_cit)

    # -- Phase 3 (30-55%): Verification pipeline runs ---------------------
    elif t_total < 0.55:
        t = (t_total - 0.30) / 0.25

        ax.text(7, 9.5, "Step 2 - Three-layer verification",
                ha="center", color=BLUE, fontsize=14, fontweight="bold")
        ax.text(7, 9.0, "Each citation checked: DCE database + 3 AI oracles",
                ha="center", color=GRAY, fontsize=10)

        citations = ["HR-2015-2386-A", "HR-2014-2288-A", "HR-2020-2135-A"]
        for ci, cit in enumerate(citations):
            y_base = 6.8 - ci * 2.3
            t_cit  = np.clip(t * 3 - ci * 0.5, 0, 1)

            # Citation box
            ax.add_patch(FancyBboxPatch((0.3, y_base - 0.3), 3.8, 0.7,
                boxstyle="round,pad=0.05",
                facecolor=DARK_RED, edgecolor=YELLOW, lw=2, alpha=0.9))
            ax.text(2.2, y_base + 0.05, cit, ha="center", color=YELLOW,
                    fontsize=10, fontweight="bold")

            # Layer 1: DB check
            if t_cit > 0.1:
                alpha_l1 = ease_in_out(np.clip((t_cit - 0.1) / 0.3, 0, 1))
                ax.add_patch(FancyBboxPatch((4.5, y_base - 0.35), 4.0, 0.8,
                    boxstyle="round,pad=0.05",
                    facecolor=PANEL, edgecolor=RED if t_cit > 0.4 else GRAY,
                    lw=1.5, alpha=alpha_l1))
                ax.text(4.7, y_base + 0.15, "DCE Database",
                        color=GRAY, fontsize=8.5, alpha=alpha_l1)
                if t_cit > 0.4:
                    ax.text(4.7, y_base - 0.12, "NOT FOUND",
                            color=RED, fontsize=10, fontweight="bold",
                            alpha=ease_in_out(np.clip((t_cit - 0.4) / 0.2, 0, 1)))
                ax.annotate("", xy=(4.5, y_base + 0.05),
                            xytext=(4.1, y_base + 0.05),
                            arrowprops=dict(arrowstyle="->", color=YELLOW, lw=1.5,
                                            alpha=alpha_l1))

            # Layer 2: Oracle
            if t_cit > 0.5:
                alpha_l2 = ease_in_out(np.clip((t_cit - 0.5) / 0.3, 0, 1))
                ax.add_patch(FancyBboxPatch((8.8, y_base - 0.35), 4.8, 0.8,
                    boxstyle="round,pad=0.05",
                    facecolor=PANEL, edgecolor=RED if t_cit > 0.8 else GRAY,
                    lw=1.5, alpha=alpha_l2))
                ax.text(9.0, y_base + 0.15, "3 AI Oracles",
                        color=GRAY, fontsize=8.5, alpha=alpha_l2)
                if t_cit > 0.8:
                    ax.text(9.0, y_base - 0.12, "CANNOT VERIFY",
                            color=RED, fontsize=10, fontweight="bold",
                            alpha=ease_in_out(np.clip((t_cit - 0.8) / 0.2, 0, 1)))
                ax.annotate("", xy=(8.8, y_base + 0.05),
                            xytext=(8.5, y_base + 0.05),
                            arrowprops=dict(arrowstyle="->", color=GRAY, lw=1.5,
                                            alpha=alpha_l2))

    # -- Phase 4 (55-75%): ALERT - hallucinations detected -----------------
    elif t_total < 0.75:
        t = (t_total - 0.55) / 0.20
        alpha = ease_in_out(t)

        # Pulsing red border
        pulse = 0.5 + 0.5 * np.sin(t * np.pi * 4)
        ax.add_patch(FancyBboxPatch((0.3, 1.2), 13.4, 7.8,
            boxstyle="round,pad=0.1",
            facecolor=DARK_RED, edgecolor=RED,
            lw=2 + pulse * 2, alpha=min(0.3 * alpha, 0.3)))

        ax.text(7, 8.5, "VERIFICATION COMPLETE", ha="center",
                color=RED, fontsize=16, fontweight="bold", alpha=alpha)

        table_data = [
            ("HR-2015-2386-A", "NOT FOUND", "UNVERIFIABLE", "!! HALLUCINATED"),
            ("HR-2014-2288-A", "NOT FOUND", "UNVERIFIABLE", "!! HALLUCINATED"),
            ("HR-2020-2135-A", "NOT FOUND", "UNVERIFIABLE", "!! HALLUCINATED"),
        ]
        headers = ["Citation", "DCE Database", "Oracle (3 LLMs)", "Verdict"]
        col_x   = [0.8, 4.2, 7.8, 10.5]
        _col_w  = [3.2, 3.4, 2.6, 3.2]  # noqa: F841

        # Header row
        for j, (hdr, x) in enumerate(zip(headers, col_x)):
            ax.text(x, 7.6, hdr, color=BLUE, fontsize=9.5,
                    fontweight="bold", alpha=alpha)

        ax.axhline(7.3, xmin=0.05, xmax=0.97, color=BORDER, lw=1, alpha=alpha)

        for i, row in enumerate(table_data):
            y = 6.6 - i * 1.05
            row_alpha = ease_in_out(np.clip((t - i * 0.15) / 0.3, 0, 1)) * alpha
            colors_row = [YELLOW, RED, RED, RED]
            for j, (cell, x, col) in enumerate(zip(row, col_x, colors_row)):
                ax.text(x, y, cell, color=col, fontsize=9,
                        fontweight="bold" if j == 3 else "normal",
                        alpha=row_alpha)

        ax.axhline(3.5, xmin=0.05, xmax=0.97, color=BORDER, lw=1, alpha=alpha)

        ax.add_patch(FancyBboxPatch((1.0, 1.5), 12, 1.7,
            boxstyle="round,pad=0.1",
            facecolor=DARK_RED, edgecolor=RED, lw=2, alpha=0.7 * alpha))
        ax.text(7, 2.6, "DOCUMENT REJECTED - DO NOT SUBMIT",
                ha="center", color=RED, fontsize=14, fontweight="bold",
                alpha=alpha)
        ax.text(7, 2.0, "These court decisions do not exist in any legal database.",
                ha="center", color=WHITE, fontsize=10, alpha=alpha * 0.9)

    # -- Phase 5 (75-90%): Without vs with comparison ---------------------
    elif t_total < 0.90:
        t = (t_total - 0.75) / 0.15
        alpha = ease_in_out(t)

        ax.text(7, 9.5, "The difference REMORA makes", ha="center",
                color=WHITE, fontsize=14, fontweight="bold", alpha=alpha)

        without_steps = [
            "AI generates 3 fake citations",
            "Document submitted to committee",
            "Vote taken on false premises",
            "Police discover hallucinations",
            "Case collapses - media story",
        ]
        with_steps = [
            "Document loaded into Claude",
            "Citations extracted automatically",
            "DCE: HR-2015-2386-A NOT FOUND",
            "ALERT raised before submission",
            "Document stopped - review begins",
        ]

        ax.add_patch(FancyBboxPatch((0.3, 0.5), 6.3, 8.5,
            boxstyle="round,pad=0.1",
            facecolor=DARK_RED, edgecolor=RED, lw=2, alpha=0.6 * alpha))
        ax.text(3.45, 8.6, "WITHOUT REMORA",
                ha="center", color=RED, fontsize=12, fontweight="bold", alpha=alpha)
        ax.text(3.45, 8.1, "(Asker, May 2026)",
                ha="center", color=GRAY, fontsize=9, alpha=alpha)
        for i, step in enumerate(without_steps):
            step_alpha = ease_in_out(np.clip((t - i * 0.1) / 0.3, 0, 1)) * alpha
            ax.text(0.7, 7.4 - i * 1.1, f"{i+1}. {step}",
                    color=RED if i >= 3 else WHITE, fontsize=9.5, alpha=step_alpha)

        ax.add_patch(FancyBboxPatch((7.4, 0.5), 6.3, 8.5,
            boxstyle="round,pad=0.1",
            facecolor="#052E16", edgecolor=GREEN, lw=2, alpha=0.6 * alpha))
        ax.text(10.55, 8.6, "WITH REMORA + DCE",
                ha="center", color=GREEN, fontsize=12, fontweight="bold", alpha=alpha)
        ax.text(10.55, 8.1, "(prevented outcome)",
                ha="center", color=GRAY, fontsize=9, alpha=alpha)
        for i, step in enumerate(with_steps):
            step_alpha = ease_in_out(np.clip((t - i * 0.1) / 0.3, 0, 1)) * alpha
            ax.text(7.7, 7.4 - i * 1.1, f"{i+1}. {step}",
                    color=GREEN if i >= 2 else WHITE, fontsize=9.5, alpha=step_alpha)

    # -- Phase 6 (90-100%): Final statement --------------------------------
    else:
        t = (t_total - 0.90) / 0.10
        alpha = ease_in_out(t)

        ax.add_patch(FancyBboxPatch((0.5, 2.5), 13, 5.5,
            boxstyle="round,pad=0.2",
            facecolor=PANEL, edgecolor=BLUE, lw=2, alpha=alpha))

        ax.text(7, 7.4, "REMORA + DCE", ha="center", color=BLUE,
                fontsize=22, fontweight="bold", alpha=alpha)
        ax.text(7, 6.8, "Norwegian Legal Citation Verification",
                ha="center", color=WHITE, fontsize=13, alpha=alpha)

        results_text = [
            "Legal principles (aml, GDPR):   6/6 = 100%",
            "Real court citations:            2/2 = 100%",
            "Hallucinated citations (Asker):  3/3 detected via DCE database",
            "Overall (16-item test suite):    56% - parametric REMORA alone insufficient",
        ]
        ax.text(7, 6.1, "Test results - Norwegian law suite (May 2026)",
                ha="center", color=GRAY, fontsize=10, alpha=alpha)
        for i, line in enumerate(results_text):
            col = GREEN if "100%" in line or "detected" in line else (RED if "insufficient" in line else WHITE)
            ax.text(2.0, 5.5 - i * 0.55, line, color=col, fontsize=9.5, alpha=alpha)

        ax.text(7, 3.2,
                "REMORA prefers calibrated uncertainty over confident hallucination.",
                ha="center", color=WHITE, fontsize=11, alpha=alpha, style="italic")
        ax.text(7, 2.7,
                "Source: results/norwegian_law_eval.json  |  "
                "github.com/darklordVirtual/REMORA",
                ha="center", color=GRAY, fontsize=8.5, alpha=alpha * 0.7)


def make_animation():
    fig, ax = plt.subplots(figsize=(12, 8), facecolor=BG)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    def update(frame):
        make_frame(ax, frame)

    anim = animation.FuncAnimation(
        fig, update, frames=TOTAL_FRAMES,
        interval=1000 // 15,  # 15 fps
        repeat=True, repeat_delay=3000,
    )

    # Save as GIF
    gif_path = OUT / "remora_demo.gif"
    writer = animation.PillowWriter(fps=15)
    print(f"Rendering {TOTAL_FRAMES} frames at 15fps...")
    anim.save(str(gif_path), writer=writer, dpi=120)
    plt.close(fig)
    print(f"  Saved: {gif_path} ({gif_path.stat().st_size // 1024} KB)")
    return gif_path


if __name__ == "__main__":
    make_animation()
