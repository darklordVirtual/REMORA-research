#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Generate the Asker kommune AI hallucination case visual.
Real case documented in VG 7. mai 2026 and Aftenposten April 2025.
"""
from __future__ import annotations
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT = Path(__file__).parent.parent / "artifacts" / "use-cases"
OUT.mkdir(parents=True, exist_ok=True)

BG     = "#0F172A"
PANEL  = "#1E293B"
BORDER = "#334155"
WHITE  = "#F8FAFC"
GRAY   = "#94A3B8"
GREEN  = "#34D399"
RED    = "#F87171"
BLUE   = "#38BDF8"
ORANGE = "#FB923C"
YELLOW = "#FCD34D"
PURPLE = "#A78BFA"

def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  {path.name}")

def arrow(ax, x1, y1, x2, y2, color=GRAY, lw=2, style="->"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw))


# -- Visual 1: The Asker Case - What Happened ---------------------------------
def asker_what_happened():
    fig, ax = plt.subplots(figsize=(14, 10), facecolor=BG)
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0, 14); ax.set_ylim(0, 11)

    fig.suptitle("Asker kommune - AI-hallusinasjon i formell saksbehandling\n"
                 "Dokumentert i VG 7. mai 2026", color=WHITE, fontsize=18,
                 fontweight="bold", y=1.01)

    # Timeline steps - left column (what happened without REMORA)
    steps = [
        (9.5, RED,    "STEG 1",  "Kommunedirektoren bruker AI",
         "\"La oss bruke AI til å finne\nrelevante HR-dommer\""),
        (7.8, ORANGE, "STEG 2",  "AI hallusinerer tre dommer",
         "HR-2015-2386-A    [FINNES IKKE]\nHR-2014-2288-A    [FINNES IKKE]\nHR-2020-2135-A    [FINNES IKKE]"),
        (6.0, ORANGE, "STEG 3",  "Dommene siteres i saksfremlegg",
         "Presentert som juridisk grunnlag\nfor vedtak i Formannskapet 21. april 2026"),
        (4.2, RED,    "STEG 4",  "Politiet sjekker kildene",
         "Politiadvokat: \"Disse dommene\nexisterer ikke. AI-hallusinasjoner.\""),
        (2.4, RED,    "STEG 5",  "Politiet nekter assistanse",
         "Saksbehandlingen er uforsvarlig.\nVedtaket må gjøres om."),
        (0.7, RED,    "KONSEKVENS", "Kommunen mister juridisk grunnlag",
         "VG avslorer 7. mai 2026.\nKommunen innrommer feilen."),
    ]

    for y, col, label, title, desc in steps:
        ax.add_patch(mpatches.FancyBboxPatch((0.3, y-0.55), 6.2, 1.1,
            boxstyle="round,pad=0.08", facecolor=PANEL, edgecolor=col, lw=2))
        ax.text(0.55, y+0.28, label, color=col, fontsize=9, fontweight="bold")
        ax.text(0.55, y+0.02, title, color=WHITE, fontsize=11, fontweight="bold")
        ax.text(0.55, y-0.33, desc, color=GRAY, fontsize=9)
        if y > 0.7:
            arrow(ax, 3.4, y-0.55, 3.4, y-0.7, RED, 1.5)

    ax.text(3.4, 10.7, "UTEN REMORA", ha="center", color=RED,
            fontsize=14, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#2D1515", edgecolor=RED))

    # Right column - with REMORA
    steps_r = [
        (9.5, BLUE,  "STEG 1",  "Dokument lastes opp til Claude",
         "\"Analyser dette saksfremlegget\""),
        (7.8, PURPLE,"STEG 2",  "REMORA ekstraherer sitater",
         "Finner: HR-2015-2386-A\nFinner: HR-2014-2288-A\nFinner: HR-2020-2135-A"),
        (6.0, GREEN, "STEG 3",  "DCE D1-database sjekkes",
         "IKKE FUNNET i juridisk database\nfor noen av de tre dommene"),
        (4.2, GREEN, "STEG 4",  "Multi-oracle verifisering",
         "3 uavhengige AI-orakler:\nIngen kan bekrefte at dommene eksisterer"),
        (2.4, GREEN, "STEG 5",  "Eksplisitt advarsel",
         "[!!] SANNSYNLIG HALLUSINERT\nDisse dommene eksisterer ikke"),
        (0.7, GREEN, "RESULTAT", "Saksbehandler varsles FoR innsending",
         "Vedtaket stoppes. Juridisk\nrådgivning hentes inn."),
    ]

    for y, col, label, title, desc in steps_r:
        ax.add_patch(mpatches.FancyBboxPatch((7.5, y-0.55), 6.2, 1.1,
            boxstyle="round,pad=0.08", facecolor=PANEL, edgecolor=col, lw=2))
        ax.text(7.75, y+0.28, label, color=col, fontsize=9, fontweight="bold")
        ax.text(7.75, y+0.02, title, color=WHITE, fontsize=11, fontweight="bold")
        ax.text(7.75, y-0.33, desc, color=GRAY, fontsize=9)
        if y > 0.7:
            arrow(ax, 10.6, y-0.55, 10.6, y-0.7, GREEN, 1.5)

    ax.text(10.6, 10.7, "MED REMORA + DCE", ha="center", color=GREEN,
            fontsize=14, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#052E16", edgecolor=GREEN))

    # VS divider
    ax.add_patch(mpatches.FancyBboxPatch((6.8, 4.5), 0.4, 2.0,
        boxstyle="round,pad=0.1", facecolor=PANEL, edgecolor=BORDER, lw=1))
    ax.text(7.0, 5.5, "VS", ha="center", color=GRAY, fontsize=12, fontweight="bold")

    fig.tight_layout()
    save(fig, "asker_case_comparison.png")


# -- Visual 2: REMORA output for the Asker letter -----------------------------
def asker_remora_output():
    fig, ax = plt.subplots(figsize=(12, 9), facecolor=BG)
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0, 12); ax.set_ylim(0, 10)

    fig.suptitle("REMORA + DCE Sitatverifisering\nAsker saksfremlegg - Hurummarka-saken",
                 color=WHITE, fontsize=18, fontweight="bold", y=1.02)

    # Input
    ax.add_patch(mpatches.FancyBboxPatch((0.3, 8.2), 11.4, 1.5,
        boxstyle="round,pad=0.1", facecolor=PANEL, edgecolor=BORDER, lw=1.5))
    ax.text(6, 9.3, "Saksfremlegg lastet opp: handtering_av_aksjonister_i_avgrunnsdalen.pdf",
        ha="center", color=WHITE, fontsize=11, fontweight="bold")
    ax.text(6, 8.75, "Inneholder: EMK Art. 10 analyse, tre Høyesterettsdommer, leiekontrakt-strategi",
        ha="center", color=GRAY, fontsize=10)

    arrow(ax, 6, 8.2, 6, 7.5, BLUE, 2)

    # Three citations
    citations = [
        ("HR-2015-2386-A", 1.0),
        ("HR-2014-2288-A", 4.7),
        ("HR-2020-2135-A", 8.4),
    ]

    for cit, x in citations:
        ax.add_patch(mpatches.FancyBboxPatch((x, 6.3), 3.0, 1.0,
            boxstyle="round,pad=0.08", facecolor=PANEL, edgecolor=ORANGE, lw=2))
        ax.text(x+1.5, 6.8, cit, ha="center", color=ORANGE,
                fontsize=12, fontweight="bold")
        ax.text(x+1.5, 6.45, "Sitat funnet", ha="center", color=GRAY, fontsize=9)
        arrow(ax, x+1.5, 6.3, x+1.5, 5.7, ORANGE, 1.5)

    ax.text(6, 7.35, "Steg 1: Ekstraherer juridiske referanser", ha="center",
            color=BLUE, fontsize=10)

    # Verification results for each
    results = [
        ("DCE D1:\nIKKE FUNNET", "Oracle:\nCANNOT VERIFY\n0% konsensus", RED, 1.0),
        ("DCE D1:\nIKKE FUNNET", "Oracle:\nCANNOT VERIFY\n0% konsensus", RED, 4.7),
        ("DCE D1:\nIKKE FUNNET", "Oracle:\nCANNOT VERIFY\n0% konsensus", RED, 8.4),
    ]

    for db_txt, oracle_txt, col, x in results:
        # DB check
        ax.add_patch(mpatches.FancyBboxPatch((x, 4.5), 1.4, 1.0,
            boxstyle="round,pad=0.05", facecolor="#2D1515", edgecolor=RED, lw=1.5))
        ax.text(x+0.7, 5.05, db_txt, ha="center", color=RED, fontsize=8.5)
        # Oracle check
        ax.add_patch(mpatches.FancyBboxPatch((x+1.5, 4.5), 1.4, 1.0,
            boxstyle="round,pad=0.05", facecolor="#2D1515", edgecolor=ORANGE, lw=1.5))
        ax.text(x+2.2, 5.05, oracle_txt, ha="center", color=ORANGE, fontsize=8.5)

    ax.text(6, 6.1, "Steg 2+3: DCE databaseoppslag + Multi-oracle sjekk", ha="center",
            color=BLUE, fontsize=10)

    arrow(ax, 6, 4.5, 6, 3.8, RED, 2)

    # Final verdict
    ax.add_patch(mpatches.FancyBboxPatch((0.5, 2.2), 11.0, 1.4,
        boxstyle="round,pad=0.1", facecolor="#2D1515", edgecolor=RED, lw=3))
    ax.text(6, 3.2, "[!!] ADVARSEL: SANNSYNLIG AI-HALLUSINASJON",
        ha="center", color=RED, fontsize=15, fontweight="bold")
    ax.text(6, 2.65, "HR-2015-2386-A · HR-2014-2288-A · HR-2020-2135-A - EKSISTERER IKKE",
        ha="center", color=WHITE, fontsize=11)
    ax.text(6, 2.3, "Dommene er ikke funnet i DCE sin juridiske database og kan ikke bekreftes av noe orakel.",
        ha="center", color=GRAY, fontsize=9)

    arrow(ax, 6, 2.2, 6, 1.5, GREEN, 2)

    # Principle check
    ax.add_patch(mpatches.FancyBboxPatch((0.5, 0.3), 11.0, 1.0,
        boxstyle="round,pad=0.08", facecolor="#052E16", edgecolor=GREEN, lw=2))
    ax.text(6, 0.95, "Steg 4: Juridisk prinsipp sjekket mot norsk lov",
        ha="center", color=GREEN, fontsize=10, fontweight="bold")
    ax.text(6, 0.55, "EMK Art. 10 vs eierrardighet: [OK] KORREKT (100%)   |   "
            "Leiekontrakt uten politiinvolvering: [?] USIKKER (50%)",
        ha="center", color=WHITE, fontsize=9)

    fig.tight_layout()
    save(fig, "asker_remora_output.png")


# -- Visual 3: The systemic problem -------------------------------------------
def systemic_problem():
    fig, ax = plt.subplots(figsize=(13, 8), facecolor=BG)
    ax.set_facecolor(BG); ax.axis("off")
    ax.set_xlim(0, 13); ax.set_ylim(0, 9)

    fig.suptitle("Systemisk problem: AI-hallusinasjoner i norsk juridisk saksbehandling",
                 color=WHITE, fontsize=17, fontweight="bold", y=1.02)

    # Timeline
    events = [
        (0.5,  "April 2025",   "Advokat sender hallusinerte\nforarbeider til Høyesterett",
         "Norges Høyesterett\noppdaterer advokatveileder", RED),
        (3.7,  "Mars 2025",    "Tromsø kommune:\nRapport med fiktive kilder\ntil kommunestyret",
         "Saken avslørt av\niTromsø", ORANGE),
        (6.9,  "April 2026",   "Asker kommune:\n3 oppdiktede HR-dommer\ni saksfremlegg",
         "Politiet nekter\nassistanse. VG: 7. mai.", RED),
        (10.1, "Fremtiden?",   "Neste hendelse...\nuten REMORA",
         "Kan stoppes med\nautomatisk sjekk", GREEN),
    ]

    ax.plot([0.2, 12.5], [5.5, 5.5], color=BORDER, lw=2, zorder=0)

    for x, date, incident, consequence, col in events:
        # Dot on timeline
        ax.scatter([x+1.3], [5.5], s=200, color=col, zorder=5, edgecolors=BG, lw=2)
        # Date
        ax.text(x+1.3, 5.9, date, ha="center", color=GRAY, fontsize=9, fontweight="bold")
        # Incident box (above)
        ax.add_patch(mpatches.FancyBboxPatch((x, 6.3), 2.5, 2.3,
            boxstyle="round,pad=0.08", facecolor=PANEL, edgecolor=col, lw=2))
        ax.text(x+1.25, 8.2, "HENDELSE", ha="center", color=col, fontsize=8, fontweight="bold")
        ax.text(x+1.25, 7.45, incident, ha="center", color=WHITE, fontsize=9)
        arrow(ax, x+1.3, 6.3, x+1.3, 5.7, col, 1.5)
        # Consequence box (below)
        ax.add_patch(mpatches.FancyBboxPatch((x, 3.0), 2.5, 2.0,
            boxstyle="round,pad=0.08", facecolor=PANEL, edgecolor=GRAY, lw=1.5))
        ax.text(x+1.25, 4.6, "KONSEKVENS", ha="center", color=GRAY, fontsize=8, fontweight="bold")
        ax.text(x+1.25, 3.9, consequence, ha="center", color=GRAY, fontsize=9)
        arrow(ax, x+1.3, 5.3, x+1.3, 5.0, GRAY, 1.5)

    # Pattern annotation
    ax.add_patch(mpatches.FancyBboxPatch((0.2, 0.2), 12.4, 2.4,
        boxstyle="round,pad=0.1", facecolor=PANEL, edgecolor=BLUE, lw=2))
    ax.text(6.4, 2.3, "Det felles monsteret:", ha="center", color=BLUE, fontsize=12, fontweight="bold")
    _pattern_cols = [RED, ORANGE, RED]  # noqa: F841
    patterns = [
        ("AI genererer plausible\nmen falske kilder", 2.2),
        ("Ingen automatisk\nkildesjekk", 6.4),
        ("Vedtak fattet pa\nfeil grunnlag", 10.6),
    ]
    for txt, x in patterns:
        ax.text(x, 1.1, txt, ha="center", color=WHITE, fontsize=10,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#1E293B", edgecolor=BORDER))

    ax.text(6.4, 0.4, "REMORA verifiserer sitater automatisk FoR dokumentet brukes i formell saksbehandling.",
        ha="center", color=GREEN, fontsize=10, fontweight="bold")

    fig.tight_layout()
    save(fig, "systemic_ai_hallucination.png")


if __name__ == "__main__":
    print("Generating Asker case visuals...")
    asker_what_happened()
    asker_remora_output()
    systemic_problem()
    print(f"\nSaved to: {OUT}")
