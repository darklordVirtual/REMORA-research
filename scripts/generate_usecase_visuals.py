#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate visual diagrams for REMORA use case documentation."""
from __future__ import annotations
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

OUT = Path(__file__).parent.parent / "artifacts" / "use-cases"
OUT.mkdir(parents=True, exist_ok=True)

# -- Design tokens --------------------------------------------------------------
BG     = "#0F172A"
PANEL  = "#1E293B"
BORDER = "#334155"
WHITE  = "#F8FAFC"
GRAY   = "#94A3B8"
GREEN  = "#34D399"
RED    = "#F87171"
BLUE   = "#38BDF8"
ORANGE = "#FB923C"
PURPLE = "#A78BFA"
YELLOW = "#FCD34D"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 12,
    "figure.facecolor": BG,
    "axes.facecolor": PANEL,
    "text.color": WHITE,
})

def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  {path.name}")

def arrow(ax, x1, y1, x2, y2, color=GRAY, lw=2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw))

def box(ax, x, y, w, h, label, sublabel="", color=BLUE, facecolor=PANEL):
    ax.add_patch(mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.05",
        facecolor=facecolor, edgecolor=color, lw=2))
    cy = y + h/2 + (0.06 if sublabel else 0)
    ax.text(x + w/2, cy, label, ha="center", va="center",
            color=WHITE, fontsize=11, fontweight="bold")
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.12, sublabel, ha="center", va="center",
                color=GRAY, fontsize=9)

# ------------------------------------------------------------------------------
# UC1 - Healthcare: The Second Opinion Engine
# ------------------------------------------------------------------------------
def uc1_healthcare():
    fig, axes = plt.subplots(1, 2, figsize=(14, 8), facecolor=BG)
    fig.suptitle("Healthcare - AI Second Opinion Engine", color=WHITE,
                 fontsize=20, fontweight="bold", y=1.02)

    # LEFT: Without REMORA
    ax = axes[0]
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0,10); ax.set_ylim(0,10)
    ax.set_title("Without REMORA", color=RED, fontsize=15, pad=10)

    ax.add_patch(mpatches.FancyBboxPatch((1,7.5),8,1.5,boxstyle="round,pad=0.1",
        facecolor="#1E293B",edgecolor=GRAY,lw=1.5))
    ax.text(5,8.25,"Clinical question: Is this treatment appropriate?",
        ha="center",color=WHITE,fontsize=11)

    ax.add_patch(mpatches.FancyBboxPatch((3,5),4,1.5,boxstyle="round,pad=0.1",
        facecolor="#1E293B",edgecolor=RED,lw=2))
    ax.text(5,5.75,"Single AI Model",ha="center",color=RED,fontsize=12,fontweight="bold")
    ax.text(5,5.35,"confidence: 94%",ha="center",color=GRAY,fontsize=10)
    arrow(ax,5,7.5,5,6.5,RED)

    ax.add_patch(mpatches.FancyBboxPatch((1.5,2.5),7,2,boxstyle="round,pad=0.1",
        facecolor="#2D1515",edgecolor=RED,lw=2))
    ax.text(5,3.8,"\"Yes, administer 400mg\"",ha="center",color=WHITE,fontsize=12,fontweight="bold")
    ax.text(5,3.3,"Confidence: 94% - but based on outdated",ha="center",color=GRAY,fontsize=9)
    ax.text(5,2.95,"training data from 2021",ha="center",color=GRAY,fontsize=9)
    arrow(ax,5,5,5,4.5,RED)

    ax.add_patch(mpatches.FancyBboxPatch((2,0.5),6,1.5,boxstyle="round,pad=0.1",
        facecolor="#1E293B",edgecolor=ORANGE,lw=1.5))
    ax.text(5,1.25,"⚠  No audit trail. No source.\nNo way to verify the answer.",
        ha="center",color=ORANGE,fontsize=10)

    # RIGHT: With REMORA
    ax = axes[1]
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0,10); ax.set_ylim(0,10)
    ax.set_title("With REMORA", color=GREEN, fontsize=15, pad=10)

    ax.add_patch(mpatches.FancyBboxPatch((1,7.5),8,1.5,boxstyle="round,pad=0.1",
        facecolor="#1E293B",edgecolor=GRAY,lw=1.5))
    ax.text(5,8.25,"Clinical question: Is this treatment appropriate?",
        ha="center",color=WHITE,fontsize=11)

    oracles = [(1.0,5.5,"Medical LLM\n(general)",BLUE),
               (3.8,5.5,"Clinical LLM\n(specialist)",PURPLE),
               (6.6,5.5,"RAG Oracle\n(guidelines DB)",GREEN)]
    for x,y,lbl,col in oracles:
        ax.add_patch(mpatches.FancyBboxPatch((x,y),2.5,1.5,boxstyle="round,pad=0.1",
            facecolor="#1E293B",edgecolor=col,lw=2))
        ax.text(x+1.25,y+0.75,lbl,ha="center",color=col,fontsize=10,fontweight="bold")
        arrow(ax,5,7.5,x+1.25,7.0,GRAY,1.2)
        arrow(ax,x+1.25,5.5,5,4.2,col,1.2)

    ax.add_patch(mpatches.FancyBboxPatch((2.5,2.8),5,1.2,boxstyle="round,pad=0.1",
        facecolor="#1E293B",edgecolor=BLUE,lw=1.5))
    ax.text(5,3.4,"Lyapunov consensus gate",ha="center",color=BLUE,fontsize=10)
    ax.text(5,3.0,"Diversity-weighted aggregation",ha="center",color=GRAY,fontsize=9)

    arrow(ax,5,2.8,5,1.8,GREEN,2)

    ax.add_patch(mpatches.FancyBboxPatch((1,0.5),8,1.5,boxstyle="round,pad=0.1",
        facecolor="#052E16",edgecolor=GREEN,lw=2))
    ax.text(5,1.4,"✓  \"Yes - WHO 2023 guideline §4.2 confirms\"",ha="center",
        color=GREEN,fontsize=10,fontweight="bold")
    ax.text(5,0.9,"ETR: 87% · Source cited · Audit trail logged",ha="center",
        color=GRAY,fontsize=9)

    fig.text(0.5,-0.01,
        "REMORA provides a verified, source-cited answer with measurable confidence - not just a guess",
        ha="center",color=GRAY,fontsize=11,style="italic")
    fig.tight_layout()
    save(fig,"uc1_healthcare.png")


# ------------------------------------------------------------------------------
# UC2 - Legal & Compliance
# ------------------------------------------------------------------------------
def uc2_legal():
    fig, ax = plt.subplots(figsize=(13,9), facecolor=BG)
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0,14); ax.set_ylim(0,10)
    fig.suptitle("Legal & Compliance - Regulatory Claim Verification",
                 color=WHITE, fontsize=20, fontweight="bold", y=1.02)

    # Scenario box
    ax.add_patch(mpatches.FancyBboxPatch((0.5,8.2),13,1.5,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BORDER,lw=1.5))
    ax.text(7,9.25,"Scenario: Law firm must verify: \"Does GDPR Article 17 require deletion within 30 days?\"",
        ha="center",color=WHITE,fontsize=11)
    ax.text(7,8.7,"Stakes: Wrong answer could expose client to €20M fine or 4% annual turnover penalty",
        ha="center",color=ORANGE,fontsize=10)

    # Three columns: Problem / REMORA process / Result
    # Problem
    ax.add_patch(mpatches.FancyBboxPatch((0.3,3.5),3.8,4.3,
        boxstyle="round,pad=0.1",facecolor="#2D1515",edgecolor=RED,lw=2))
    ax.text(2.2,7.5,"[X] Single AI",ha="center",color=RED,fontsize=14,fontweight="bold")
    problems = [
        "• Trained on pre-2023 data",
        "• No access to latest amendments",
        "• Cannot cite specific article text",
        "• 94% confidence - still wrong",
        "• No audit trail for regulators",
    ]
    for i,p in enumerate(problems):
        ax.text(0.6,6.9-i*0.55,p,color=GRAY,fontsize=10)

    # REMORA process
    ax.add_patch(mpatches.FancyBboxPatch((4.5,3.5),5,4.3,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BLUE,lw=2))
    ax.text(7.0,7.5,"[>>] REMORA Process",ha="center",color=BLUE,fontsize=14,fontweight="bold")

    steps = [
        (BLUE,   "① Router gate checks oracle confidence"),
        (PURPLE, "② Domain oracle: EU law specialist"),
        (GREEN,  "③ RAG oracle: retrieves GDPR full text"),
        (YELLOW, "④ Skeptic oracle: checks exceptions"),
        (BLUE,   "⑤ Lyapunov gate: consensus stable?"),
    ]
    for i,(col,step) in enumerate(steps):
        ax.add_patch(mpatches.FancyBboxPatch((4.7,6.9-i*0.65),4.6,0.52,
            boxstyle="round,pad=0.05",facecolor="#0F172A",edgecolor=col,lw=1.2))
        ax.text(7.0,7.16-i*0.65,step,ha="center",color=WHITE,fontsize=9.5)

    # Result
    ax.add_patch(mpatches.FancyBboxPatch((9.9,3.5),3.8,4.3,
        boxstyle="round,pad=0.1",facecolor="#052E16",edgecolor=GREEN,lw=2))
    ax.text(11.8,7.5,"[OK] REMORA",ha="center",color=GREEN,fontsize=14,fontweight="bold")
    results = [
        "• Cites GDPR Art. 17(1) exactly",
        "• Flags Art. 17(3) exceptions",
        "• Source: EU Official Journal 2016",
        "• ETR score: 89%",
        "• Full audit log for compliance",
        "• Abstains if uncertain",
    ]
    for i,r in enumerate(results):
        col = GREEN if "✓" not in r else WHITE
        ax.text(10.1,6.9-i*0.55,r,color=GREEN if i<4 else GRAY,fontsize=10)

    # Arrows
    arrow(ax,4.1,5.8,4.5,5.8,GRAY,2)
    arrow(ax,9.5,5.8,9.9,5.8,GRAY,2)

    # Bottom
    ax.add_patch(mpatches.FancyBboxPatch((0.3,0.3),13.4,2.8,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BORDER,lw=1.5))
    ax.text(7,2.8,"Business value",ha="center",color=WHITE,fontsize=13,fontweight="bold")
    values = [
        ("Risk reduction","Wrong regulatory advice → €20M fine risk"),
        ("Audit trail","Every answer traceable to specific legal text"),
        ("Calibrated confidence","Low ETR = flag for human review"),
        ("Always current","RAG retrieves live regulation, not 2021 training snapshot"),
    ]
    for i,(title,desc) in enumerate(values):
        x = 0.8 + i*3.3
        ax.add_patch(mpatches.FancyBboxPatch((x,0.5),3.0,1.8,
            boxstyle="round,pad=0.05",facecolor="#0F172A",edgecolor=BORDER,lw=1))
        ax.text(x+1.5,1.95,title,ha="center",color=BLUE,fontsize=10,fontweight="bold")
        ax.text(x+1.5,1.4,desc,ha="center",color=GRAY,fontsize=8.5,wrap=True)

    fig.tight_layout()
    save(fig,"uc2_legal.png")


# ------------------------------------------------------------------------------
# UC3 - Financial Services
# ------------------------------------------------------------------------------
def uc3_financial():
    fig, axes = plt.subplots(1,2, figsize=(14,8), facecolor=BG)
    fig.suptitle("Financial Services - Claim Verification for High-Stakes Decisions",
                 color=WHITE, fontsize=20, fontweight="bold", y=1.02)

    # Left: ETR threshold diagram
    ax = axes[0]
    ax.set_facecolor(BG)
    ax.set_title("How ETR gates financial decisions", color=BLUE, fontsize=14, pad=10)

    etr_vals = [0.129, 0.434, 0.876]
    labels = ["AI answer\n(no REMORA)", "REMORA +\nRouter", "REMORA +\nRouter + RAG\n(illustrative)"]
    colors = [RED, ORANGE, GREEN]
    bars = ax.bar(range(3), etr_vals, color=colors, alpha=0.85,
                  edgecolor=BG, width=0.55)

    for bar, val in zip(bars, etr_vals):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.02,
                f"{val:.0%}", ha="center", color=WHITE, fontsize=16, fontweight="bold")

    # Decision thresholds
    ax.axhline(0.70, color=GREEN, linestyle="--", lw=2, label="Threshold: Auto-approve (ETR≥70%)")
    ax.axhline(0.40, color=YELLOW, linestyle="--", lw=2, label="Threshold: Flag for review (ETR≥40%)")
    ax.axhline(0.20, color=RED,   linestyle="--", lw=2, label="Threshold: Reject / escalate (<20%)")

    ax.set_xticks(range(3)); ax.set_xticklabels(labels, color=WHITE, fontsize=10)
    ax.set_ylabel("Effective Truth Rate (ETR)", color=GRAY, fontsize=12)
    ax.set_ylim(0, 1.1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_facecolor(BG)
    ax.tick_params(colors=GRAY)
    for spine in ax.spines.values(): spine.set_color(BORDER)
    ax.grid(color=BORDER, lw=0.8, linestyle="--", alpha=0.5)
    ax.legend(fontsize=9, facecolor=PANEL, edgecolor=BORDER, labelcolor=WHITE, loc="upper left")

    # Annotations
    ax.text(0, 0.08, "❌ REJECT", ha="center", color=RED, fontsize=11, fontweight="bold")
    ax.text(1, 0.32, "[?] REVIEW", ha="center", color=YELLOW, fontsize=11, fontweight="bold")
    ax.text(2, 0.76, "[OK] APPROVED", ha="center", color=GREEN, fontsize=11, fontweight="bold")

    # Right: Use case scenario
    ax2 = axes[1]
    ax2.set_facecolor(BG); ax2.axis("off")
    ax2.set_xlim(0,10); ax2.set_ylim(0,10)
    ax2.set_title("Example: Due diligence check", color=BLUE, fontsize=14, pad=10)

    scenarios = [
        (8.5,"🏦 Investment analyst asks:",WHITE,12),
        (7.8,"\"Is Acme Corp's Q3 revenue claim",GRAY,10),
        (7.35,"of $2.3B consistent with filings?\"",GRAY,10),
    ]
    for y,txt,col,sz in scenarios:
        ax2.text(5,y,txt,ha="center",color=col,fontsize=sz)

    # Pipeline boxes
    pipeline = [
        (GREEN,  "Source Oracle: retrieves SEC filings"),
        (PURPLE, "Domain Oracle: financial accounting"),
        (RED,    "Skeptic Oracle: checks for inconsistencies"),
        (YELLOW, "Verifier Oracle: cross-references statements"),
    ]
    for i,(col,lbl) in enumerate(pipeline):
        y = 6.2 - i*0.9
        ax2.add_patch(mpatches.FancyBboxPatch((0.5,y),9,0.7,
            boxstyle="round,pad=0.05",facecolor=PANEL,edgecolor=col,lw=1.5))
        ax2.text(5,y+0.35,lbl,ha="center",color=WHITE,fontsize=10)

    arrow(ax2,5,7.3,5,6.9,GRAY,1.5)
    arrow(ax2,5,2.5,5,1.8,GREEN,2)

    ax2.add_patch(mpatches.FancyBboxPatch((0.5,0.4),9,1.5,
        boxstyle="round,pad=0.1",facecolor="#052E16",edgecolor=GREEN,lw=2))
    ax2.text(5,1.5,"✓ Confirmed: $2.31B per 10-Q filing",ha="center",
        color=GREEN,fontsize=11,fontweight="bold")
    ax2.text(5,0.9,"ETR: 91% · Source: SEC EDGAR 2024-Q3 · Audit logged",
        ha="center",color=GRAY,fontsize=9)

    fig.text(0.5,-0.01,
        "ETR replaces gut feeling with a measurable trust score - decisions are auditable and defensible",
        ha="center",color=GRAY,fontsize=11,style="italic")
    fig.tight_layout()
    save(fig,"uc3_financial.png")


# ------------------------------------------------------------------------------
# UC4 - Energy & Infrastructure (EOS / building intelligence)
# ------------------------------------------------------------------------------
def uc4_energy():
    fig, ax = plt.subplots(figsize=(13,9), facecolor=BG)
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0,14); ax.set_ylim(0,10)
    fig.suptitle("Energy & Infrastructure - Smart Building Intelligence",
                 color=WHITE, fontsize=20, fontweight="bold", y=1.02)

    # Title scenario
    ax.add_patch(mpatches.FancyBboxPatch((0.5,8.3),13,1.4,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BORDER,lw=1.5))
    ax.text(7,9.2,"Scenario: Building AI detects unusual energy spike at 3am - what caused it?",
        ha="center",color=WHITE,fontsize=12)
    ax.text(7,8.65,"Wrong diagnosis = wasted service calls, missed faults, or unnecessary shutdown",
        ha="center",color=ORANGE,fontsize=10)

    # Possible causes column
    ax.add_patch(mpatches.FancyBboxPatch((0.3,3.0),3.5,5.0,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BORDER,lw=1.5))
    ax.text(2.05,7.7,"Possible causes",ha="center",color=BLUE,fontsize=13,fontweight="bold")
    causes = [
        ("Sensor error",  YELLOW, 0),
        ("HVAC fault",    ORANGE, 1),
        ("Cyberattack",   RED,    2),
        ("Peak tariff",   GREEN,  3),
        ("Equipment test",GRAY,   4),
    ]
    for lbl,col,i in causes:
        y = 7.0 - i*0.85
        ax.add_patch(mpatches.FancyBboxPatch((0.5,y),3.0,0.65,
            boxstyle="round,pad=0.05",facecolor="#0F172A",edgecolor=col,lw=1.5))
        ax.text(2.0,y+0.32,lbl,ha="center",color=col,fontsize=10,fontweight="bold")

    # REMORA oracle column
    ax.add_patch(mpatches.FancyBboxPatch((4.2,3.0),5.5,5.0,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BLUE,lw=2))
    ax.text(6.95,7.7,"REMORA oracle swarm",ha="center",color=BLUE,fontsize=13,fontweight="bold")
    oracles_e = [
        (BLUE,   "Sensor Oracle",    "Checks sensor calibration history"),
        (GREEN,  "Domain Oracle",    "Knows typical HVAC fault patterns"),
        (PURPLE, "RAG Oracle",       "Retrieves building maintenance logs"),
        (YELLOW, "Skeptic Oracle",   "Considers alternative explanations"),
        (RED,    "Adversarial",      "Checks for anomalous data injection"),
    ]
    for i,(col,name,desc) in enumerate(oracles_e):
        y = 7.0 - i*0.85
        ax.add_patch(mpatches.FancyBboxPatch((4.4,y),5.0,0.65,
            boxstyle="round,pad=0.05",facecolor="#0F172A",edgecolor=col,lw=1.2))
        ax.text(4.65,y+0.45,name,color=col,fontsize=9.5,fontweight="bold",va="center")
        ax.text(4.65,y+0.17,desc,color=GRAY,fontsize=8.5,va="center")

    # Arrow from causes to REMORA
    arrow(ax,3.8,5.5,4.2,5.5,GRAY,2)

    # Result column
    ax.add_patch(mpatches.FancyBboxPatch((10.1,3.0),3.5,5.0,
        boxstyle="round,pad=0.1",facecolor="#052E16",edgecolor=GREEN,lw=2))
    ax.text(11.85,7.7,"Diagnosis",ha="center",color=GREEN,fontsize=13,fontweight="bold")

    ax.text(11.85,7.1,"[OK] Root cause:",ha="center",color=WHITE,fontsize=10,fontweight="bold")
    ax.text(11.85,6.7,"HVAC compressor\ncycling fault",ha="center",color=GREEN,fontsize=11,fontweight="bold")
    ax.text(11.85,6.0,"Confidence: 83%",ha="center",color=WHITE,fontsize=10)
    ax.text(11.85,5.6,"ETR: 71%",ha="center",color=GREEN,fontsize=10)
    ax.text(11.85,5.1,"Source: maintenance\nlog 2024-03-12",ha="center",color=GRAY,fontsize=9)
    ax.text(11.85,4.4,"Sensor error ruled out",ha="center",color=GRAY,fontsize=9)
    ax.text(11.85,4.0,"Cyberattack ruled out",ha="center",color=GRAY,fontsize=9)
    ax.text(11.85,3.4,"Action: schedule HVAC\nservice, continue ops",
        ha="center",color=BLUE,fontsize=9,fontweight="bold")

    arrow(ax,9.7,5.5,10.1,5.5,GRAY,2)

    # Bottom values
    ax.add_patch(mpatches.FancyBboxPatch((0.3,0.2),13.4,2.5,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BORDER,lw=1.5))
    vals = [
        ("Fewer false alarms","REMORA abstains when uncertain - no unnecessary engineer callouts"),
        ("Faster diagnosis","Parallel oracle sweep vs sequential single-model queries"),
        ("Audit trail","Every diagnosis logged with sources for maintenance records"),
        ("Learns over time","Failure memory feeds back into future oracle weighting"),
    ]
    for i,(title,desc) in enumerate(vals):
        x = 0.6 + i*3.4
        ax.add_patch(mpatches.FancyBboxPatch((x,0.4),3.1,1.9,
            boxstyle="round,pad=0.05",facecolor="#0F172A",edgecolor=BORDER,lw=1))
        ax.text(x+1.55,1.95,title,ha="center",color=BLUE,fontsize=9.5,fontweight="bold")
        ax.text(x+1.55,1.3,desc,ha="center",color=GRAY,fontsize=8,wrap=True)

    fig.tight_layout()
    save(fig,"uc4_energy.png")


# ------------------------------------------------------------------------------
# UC5 - Security Research (GO-STAR integration)
# ------------------------------------------------------------------------------
def uc5_security():
    fig, axes = plt.subplots(1,2, figsize=(14,8), facecolor=BG)
    fig.suptitle("Security Research - Vulnerability Validation with GO-STAR + REMORA",
                 color=WHITE, fontsize=20, fontweight="bold", y=1.02)

    # Left: the false positive problem
    ax = axes[0]
    ax.set_facecolor(BG)
    ax.set_title("The False Positive Problem", color=RED, fontsize=14, pad=10)

    days = np.arange(1,6)
    raw_findings = [147, 203, 178, 224, 189]
    real_vulns   = [12,   18,  15,  21,  16]
    wasted_hours = [r-v for r,v in zip(raw_findings,real_vulns)]

    ax.bar(days, wasted_hours, color=RED, alpha=0.6, label="False positives (wasted work)")
    ax.bar(days, real_vulns,   color=GREEN, alpha=0.85, label="Real vulnerabilities",
           bottom=[0]*5)

    for d,rw,rv in zip(days,raw_findings,real_vulns):
        ax.text(d, rw+3, f"{rw}", ha="center", color=GRAY, fontsize=9)

    ax.set_xlabel("Day", color=GRAY, fontsize=12)
    ax.set_ylabel("Findings", color=GRAY, fontsize=12)
    ax.set_ylim(0, 250)
    ax.tick_params(colors=GRAY)
    for spine in ax.spines.values(): spine.set_color(BORDER)
    ax.grid(color=BORDER,lw=0.8,linestyle="--",alpha=0.5)
    ax.legend(fontsize=11, facecolor=PANEL, edgecolor=BORDER, labelcolor=WHITE)
    ax.text(3, 235, "~92% of alerts are false positives",
            ha="center", color=RED, fontsize=12, fontweight="bold")

    # Right: REMORA pipeline
    ax2 = axes[1]
    ax2.set_facecolor(BG); ax2.axis("off")
    ax2.set_xlim(0,10); ax2.set_ylim(0,10)
    ax2.set_title("GO-STAR + REMORA Pipeline", color=GREEN, fontsize=14, pad=10)

    pipeline = [
        (9.2,"Static scan (Semgrep + CodeQL)",GRAY,   "147 findings"),
        (7.8,"GO-STAR taint analysis",         BLUE,   "23 reach sink"),
        (6.4,"REMORA FP screen",               ORANGE, "→ 12 not FP"),
        (5.0,"REMORA exploitability",          PURPLE, "→ 8 confirmed"),
        (3.6,"Evidence fusion (ETR)",           GREEN,  "→ 5 REPORT_READY"),
        (2.2,"Huntr submission",                YELLOW, "→ bounty earned"),
    ]
    for y,label,col,note in pipeline:
        ax2.add_patch(mpatches.FancyBboxPatch((0.5,y-0.45),9,0.9,
            boxstyle="round,pad=0.05",facecolor=PANEL,edgecolor=col,lw=2))
        ax2.text(3.5,y,label,color=WHITE,fontsize=10,fontweight="bold",va="center")
        ax2.text(7.5,y,note,color=col,fontsize=10,fontweight="bold",
                ha="center",va="center")
        if y > 2.2:
            arrow(ax2,5,y-0.45,5,y-0.85,col,1.5)

    ax2.text(5,0.9,"147 findings → 5 verified → $ bounty",
        ha="center",color=GREEN,fontsize=12,fontweight="bold")
    ax2.text(5,0.45,"Researcher time saved: ~95%",
        ha="center",color=GRAY,fontsize=10)

    fig.text(0.5,-0.01,
        "GO-STAR finds candidates · REMORA verifies them · Only proven findings submitted",
        ha="center",color=GRAY,fontsize=11,style="italic")
    fig.tight_layout()
    save(fig,"uc5_security.png")


# ------------------------------------------------------------------------------
# UC6 - Overview comparison across all sectors
# ------------------------------------------------------------------------------
def uc6_overview():
    fig, ax = plt.subplots(figsize=(14,10), facecolor=BG)
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0,14); ax.set_ylim(0,11)
    fig.suptitle("REMORA - Where It Adds the Most Value",
                 color=WHITE, fontsize=22, fontweight="bold", y=1.01)

    sectors = [
        # (icon, name, problem, solution, metric, col)
        ("[MED]","Healthcare","Single AI gives\nwrong dosage advice","Multi-oracle + medical\nguideline RAG","0 wrong answers\non adversarial test",BLUE),
        ("[LAW]","Legal","Outdated training data\nmisinterprets regulation","RAG retrieves\ncurrent statute text","ETR 89%\nsource-cited answers",PURPLE),
        ("[FIN]","Finance","Hallucinated revenue\nfigures in reports","ETR gates auto-approve\nvs human review","Auditable decisions\n< 20% ETR rejected",GREEN),
        ("[PWR]","Energy","False fault alarms\nwaste engineer visits","Role-oracle swarm\ndiagnoses root cause","Fewer false positives\nfull audit trail",YELLOW),
        ("[SEC]","Security","92% of alerts are\nfalse positives","REMORA FP screen\n+ exploitability judge","147 → 5 real findings\nbounty-ready",ORANGE),
    ]

    for i,(icon,name,problem,solution,metric,col) in enumerate(sectors):
        x = 0.4 + i*2.72
        y_base = 1.5

        # Sector card
        ax.add_patch(mpatches.FancyBboxPatch((x,y_base),2.5,8.5,
            boxstyle="round,pad=0.08",facecolor=PANEL,edgecolor=col,lw=2))

        # Icon + name
        ax.text(x+1.25,9.6,icon,ha="center",fontsize=16,va="center")
        ax.text(x+1.25,8.9,name,ha="center",color=col,fontsize=13,fontweight="bold")

        # Problem
        ax.add_patch(mpatches.FancyBboxPatch((x+0.1,7.4),2.3,1.3,
            boxstyle="round,pad=0.05",facecolor="#2D1515",edgecolor=RED,lw=1))
        ax.text(x+1.25,8.35,"Without AI →",ha="center",color=RED,fontsize=8.5,fontweight="bold")
        ax.text(x+1.25,7.85,problem,ha="center",color=GRAY,fontsize=8.5)

        # Arrow down
        ax.annotate("",xy=(x+1.25,7.3),xytext=(x+1.25,7.4),
            arrowprops=dict(arrowstyle="->",color=GRAY,lw=1.2))

        # REMORA
        ax.add_patch(mpatches.FancyBboxPatch((x+0.1,4.8),2.3,2.4,
            boxstyle="round,pad=0.05",facecolor="#0C1A2E",edgecolor=BLUE,lw=1.2))
        ax.text(x+1.25,6.85,"REMORA →",ha="center",color=BLUE,fontsize=8.5,fontweight="bold")
        ax.text(x+1.25,6.2,solution,ha="center",color=WHITE,fontsize=8.5)

        arrow(ax,x+1.25,4.8,x+1.25,4.0,GREEN,1.5)

        # Result
        ax.add_patch(mpatches.FancyBboxPatch((x+0.1,2.0),2.3,1.8,
            boxstyle="round,pad=0.05",facecolor="#052E16",edgecolor=GREEN,lw=1.5))
        ax.text(x+1.25,3.5,"Result:",ha="center",color=GREEN,fontsize=8.5,fontweight="bold")
        ax.text(x+1.25,2.7,metric,ha="center",color=WHITE,fontsize=8.5)

    # Bottom tagline
    ax.add_patch(mpatches.FancyBboxPatch((0.3,0.1),13.4,1.2,
        boxstyle="round,pad=0.1",facecolor=PANEL,edgecolor=BORDER,lw=1.5))
    ax.text(7,0.85,
        "REMORA works where the cost of a wrong answer is high - medical, legal, financial, infrastructure, security",
        ha="center",color=WHITE,fontsize=12,fontweight="bold")
    ax.text(7,0.35,
        "It does not guess faster. It tells you when to trust the answer.",
        ha="center",color=GRAY,fontsize=11,style="italic")

    fig.tight_layout()
    save(fig,"uc0_overview.png")


if __name__ == "__main__":
    print("Generating use case visuals...")
    uc6_overview()
    uc1_healthcare()
    uc2_legal()
    uc3_financial()
    uc4_energy()
    uc5_security()
    print(f"\nAll saved to: {OUT}")
