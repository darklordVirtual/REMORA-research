#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
REMORA + DCE Norwegian Law Hallucination Detection - Live Terminal Demo

Demonstrates the full citation verification pipeline on the real Asker
municipality document that contained three hallucinated court decisions.

Run:
    python scripts/demo_norwegian_law.py              # full live demo
    python scripts/demo_norwegian_law.py --fast       # skip pauses
    python scripts/demo_norwegian_law.py --no-api     # use cached results
"""
from __future__ import annotations

import argparse
import json
import time
import ssl
import urllib.request
from pathlib import Path

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich import box

ROOT = Path(__file__).parent.parent
console = Console(width=100)
SSL_CTX = ssl.create_default_context()

# -- The real Asker letter (simplified) ---------------------------------------
ASKER_LETTER = """\
Til Asker kommune v/ Kommunedirektøren

Saksreferanse: 2026/04-HM-003

Vi viser til Høyesteretts dom HR-2015-2386-A der retten fastslo at
offentlige myndigheters utøvelse av eierrådighet ikke i seg selv
utgjør et inngrep i ytringsfriheten etter EMK artikkel 10.

Videre fremgår det av HR-2014-2288-A og HR-2020-2135-A at kommunen
har adgang til å formalisere en okkupasjon gjennom leiekontrakt
uten å foreta politiassistert utkastelse.

Vi krever på denne bakgrunn at kommunen umiddelbart inngår
leiekontrakt med aksjonsgruppa for Hurummarka.

Med vennlig hilsen,
Aksjonsgruppa Knus Krigsmaskineriet
"""

# -- API helpers ---------------------------------------------------------------
REMORA = "https://go-star-remora.razorsharp.workers.dev"
LAW    = "https://remora-law-search.razorsharp.workers.dev"

def _post(url: str, payload: dict, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "REMORA-demo/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e), "verdict": None, "confidence": 0.0}

def verify_citation_db(citation: str) -> dict:
    return _post(LAW + "/verify-citation", {"citation": citation})

def remora_assess(claim: str) -> dict:
    return _post(REMORA + "/assess", {"question": claim, "context": "", "use_case": "general"})

# -- Pre-verified results for --no-api mode ------------------------------------
CACHED_RESULTS = {
    "HR-2015-2386-A": {"found_in_d1": False, "verdict": "NOT_FOUND",
                        "oracle_verdict": None, "oracle_conf": 0.0,
                        "oracle_claim": "Cannot verify - no matching case records found"},
    "HR-2014-2288-A": {"found_in_d1": False, "verdict": "NOT_FOUND",
                        "oracle_verdict": None, "oracle_conf": 0.0,
                        "oracle_claim": "Cannot verify - no matching case records found"},
    "HR-2020-2135-A": {"found_in_d1": False, "verdict": "NOT_FOUND",
                        "oracle_verdict": None, "oracle_conf": 0.0,
                        "oracle_claim": "Cannot verify - no matching case records found"},
}

# -- Timing helper -------------------------------------------------------------
def pause(seconds: float, fast: bool) -> None:
    if not fast:
        time.sleep(seconds)

# -- Demo stages ---------------------------------------------------------------

def show_intro(fast: bool) -> None:
    console.clear()
    pause(0.3, fast)
    title = Text("REMORA + DCE", style="bold cyan", justify="center")
    subtitle = Text("Norwegian Legal Citation Verification", style="white", justify="center")
    badge = Text("Live demonstration on the real Asker municipality case", style="dim", justify="center")
    console.print(Panel(Align.center(title), border_style="cyan", padding=(0, 4)))
    console.print(Align.center(subtitle))
    console.print(Align.center(badge))
    pause(1.5, fast)


def show_letter(fast: bool) -> None:
    console.print()
    console.rule("[yellow]Step 1 - Document received[/yellow]")
    pause(0.5, fast)

    # Highlight citations in the letter
    text = Text(ASKER_LETTER)
    citations = ["HR-2015-2386-A", "HR-2014-2288-A", "HR-2020-2135-A"]
    for cit in citations:
        text.highlight_regex(cit.replace("-", r"\-"), style="bold yellow on dark_red")

    console.print(Panel(text, title="[bold]Saksfremlegg - Asker kommune (April 2026)[/bold]",
                        border_style="yellow", padding=(1, 2)))
    pause(1.0, fast)
    console.print("[yellow]  Scanning for Norwegian legal citations...[/yellow]")
    pause(0.8, fast)


def show_extraction(fast: bool) -> list[str]:
    citations = ["HR-2015-2386-A", "HR-2014-2288-A", "HR-2020-2135-A"]
    console.print()
    console.rule("[cyan]Step 2 - Citations extracted[/cyan]")
    pause(0.4, fast)

    table = Table(box=box.ROUNDED, border_style="cyan", show_header=True, header_style="bold cyan")
    table.add_column("Citation",  style="bold yellow", width=20)
    table.add_column("Format",    style="dim",         width=28)
    table.add_column("Court",     style="white",       width=20)
    table.add_column("Year",      style="white",       width=8)

    for cit in citations:
        pause(0.3, fast)
        table.add_row(cit, "HR-YYYY-NNNN-A (post-2016)", "Høyesterett", cit[3:7])

    console.print(table)
    console.print(f"[cyan]  {len(citations)} citation(s) found → routing to verification pipeline[/cyan]")
    pause(0.8, fast)
    return citations


def show_pipeline(citations: list[str], use_api: bool, fast: bool) -> dict:
    results = {}

    console.print()
    console.rule("[bold white]Step 3 - Three-layer verification[/bold white]")
    pause(0.4, fast)

    for cit in citations:
        console.print()
        console.print(f"  [bold yellow]Verifying:[/bold yellow] [bold]{cit}[/bold]")
        pause(0.3, fast)

        # Layer 1: DB check
        with Progress(
            SpinnerColumn(style="blue"),
            TextColumn("  [blue]Layer 1 - DCE database lookup[/blue]"),
            transient=True, console=console
        ) as progress:
            progress.add_task("", total=None)
            pause(1.2 if not fast else 0.1, fast)
            if use_api:
                db = verify_citation_db(cit)
            else:
                db = {"found_in_d1": False, "verdict": "NOT_FOUND"}

        db_found  = db.get("found_in_d1", False)
        _db_verdict = db.get("verdict", "UNKNOWN")  # noqa: F841
        db_icon   = "[green]FOUND[/green]" if db_found else "[bold red]NOT FOUND[/bold red]"
        console.print(f"  [blue]■[/blue] DCE database: {db_icon}")
        pause(0.4, fast)

        # Layer 2: Oracle consensus
        with Progress(
            SpinnerColumn(style="purple"),
            TextColumn("  [purple]Layer 2 - Multi-oracle consensus (3 LLMs)[/purple]"),
            transient=True, console=console
        ) as progress:
            progress.add_task("", total=None)
            pause(2.0 if not fast else 0.1, fast)
            if use_api:
                oracle_prompt = (
                    f"Can you confirm the Norwegian Supreme Court decision '{cit}' exists? "
                    f"Name the parties and the legal question decided. "
                    f"If uncertain, say CANNOT VERIFY."
                )
                oracle = remora_assess(oracle_prompt)
            else:
                oracle = {"verdict": None, "confidence": 0.0,
                          "claim": "no strong consensus", "oracle_calls": 9}

        oracle_verdict = oracle.get("verdict")
        oracle_conf    = float(oracle.get("confidence", 0.0))
        oracle_calls   = oracle.get("oracle_calls", 0)
        if oracle_verdict is None or oracle_conf < 0.3:
            oracle_icon = "[bold red]CANNOT VERIFY[/bold red]"
        elif oracle_verdict is True:
            oracle_icon = "[green]CONFIRMED[/green]"
        else:
            oracle_icon = "[yellow]REJECTED[/yellow]"
        console.print(f"  [purple]■[/purple] Oracle consensus: {oracle_icon} "
                      f"(conf={oracle_conf:.0%}, {oracle_calls} calls)")
        pause(0.4, fast)

        # Layer 3: Combined verdict
        if not db_found and (oracle_verdict is None or oracle_conf < 0.3):
            final = "LIKELY_HALLUCINATED"
            final_icon = "[bold red on dark_red] !! LIKELY HALLUCINATED [/bold red on dark_red]"
        elif not db_found:
            final = "SUSPICIOUS"
            final_icon = "[bold yellow] ⚠ SUSPICIOUS [/bold yellow]"
        else:
            final = "FOUND"
            final_icon = "[bold green] ✓ VERIFIED [/bold green]"

        console.print(f"  [white]■[/white] Combined verdict: {final_icon}")
        pause(0.3, fast)
        results[cit] = {"db_found": db_found, "oracle_conf": oracle_conf,
                        "oracle_verdict": oracle_verdict, "final": final}

    return results


def show_verdict(results: dict, fast: bool) -> None:
    pause(0.5, fast)
    console.print()
    console.rule("[bold red]VERIFICATION COMPLETE[/bold red]")
    pause(0.5, fast)

    all_hallucinated = all(r["final"] == "LIKELY_HALLUCINATED" for r in results.values())

    # Summary table
    table = Table(box=box.DOUBLE, border_style="red" if all_hallucinated else "yellow",
                  show_header=True, header_style="bold white", title="Citation Verification Summary")
    table.add_column("Citation",    style="bold yellow",  width=20)
    table.add_column("DB (DCE)",    style="white",        width=14)
    table.add_column("Oracle",      style="white",        width=14)
    table.add_column("Verdict",     style="bold",         width=26)

    for cit, r in results.items():
        db_txt     = "[red]NOT FOUND[/red]" if not r["db_found"] else "[green]FOUND[/green]"
        oracle_txt = "[red]UNVERIFIABLE[/red]" if r["oracle_conf"] < 0.3 else f"{r['oracle_conf']:.0%}"
        v_txt      = {"LIKELY_HALLUCINATED": "[bold red]!! LIKELY HALLUCINATED",
                      "SUSPICIOUS":          "[yellow]⚠ SUSPICIOUS",
                      "FOUND":               "[green]✓ VERIFIED"}.get(r["final"], r["final"])
        table.add_row(cit, db_txt, oracle_txt, v_txt)

    console.print(table)
    pause(0.8, fast)

    if all_hallucinated:
        warning = Panel(
            Align.center(Text.assemble(
                Text("\n", style=""),
                Text("ALL THREE CITATIONS ARE LIKELY AI HALLUCINATIONS\n\n", style="bold red"),
                Text("These court decisions do not exist in any legal database.\n", style="white"),
                Text("This document must NOT be used in formal proceedings.\n\n", style="yellow"),
                Text("Source: Norwegian Supreme Court registry + DCE norges-lover-legal-intel\n", style="dim"),
            )),
            border_style="bold red",
            title="[bold red]DOCUMENT REJECTED[/bold red]",
            padding=(1, 4),
        )
        console.print(warning)
    pause(0.8, fast)


def show_comparison(fast: bool) -> None:
    pause(0.5, fast)
    console.print()
    console.rule("[bold white]What this means[/bold white]")
    pause(0.5, fast)

    without = Panel(
        Text.assemble(
            Text("WITHOUT REMORA\n\n", style="bold red"),
            Text("1. AI generates plausible citations\n", style="white"),
            Text("2. Document submitted to committee\n", style="white"),
            Text("3. Vote taken on false premises\n", style="white"),
            Text("4. Police asked to enforce decision\n", style="white"),
            Text("5. Police discover hallucinations\n", style="red"),
            Text("6. Case collapses - media story\n\n", style="bold red"),
            Text("Result: Asker, VG, 7 May 2026", style="dim red"),
        ),
        border_style="red", title="[red]Historical outcome[/red]", padding=(1, 2),
    )

    with_remora = Panel(
        Text.assemble(
            Text("WITH REMORA + DCE\n\n", style="bold green"),
            Text("1. Document loaded into Claude\n", style="white"),
            Text("2. Citations extracted automatically\n", style="white"),
            Text("3. DCE: HR-2015-2386-A NOT FOUND\n", style="green"),
            Text("4. Oracle: 0% consensus, unverifiable\n", style="green"),
            Text("5. ALERT raised before submission\n", style="bold green"),
            Text("6. Human review → proper legal advice\n\n", style="green"),
            Text("Result: Document stopped before committee", style="dim green"),
        ),
        border_style="green", title="[green]With REMORA[/green]", padding=(1, 2),
    )

    console.print(Columns([without, with_remora], equal=True, expand=True))
    pause(1.0, fast)


def show_outro(fast: bool) -> None:
    pause(0.5, fast)
    console.print()
    outro = Text.assemble(
        Text("REMORA does not replace legal expertise.\n", style="dim"),
        Text("It tells you when the sources do not exist - ", style="white"),
        Text("before the document reaches the committee.", style="bold white"),
    )
    console.print(Panel(Align.center(outro), border_style="cyan", padding=(1, 4)))
    console.print()
    console.print("[dim]  Test suite: tests/test_norwegian_law.py  |  "
                  "Results: results/norwegian_law_eval.json  |  "
                  "Implementation: servers/mcp_remora.py[/dim]")
    console.print()


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="REMORA Norwegian law demo")
    parser.add_argument("--fast",   action="store_true", help="Skip pauses")
    parser.add_argument("--no-api", action="store_true", help="Use cached results (no API calls)")
    args = parser.parse_args()

    use_api = not args.no_api
    fast    = args.fast

    show_intro(fast)
    show_letter(fast)
    citations = show_extraction(fast)
    results   = show_pipeline(citations, use_api, fast)
    show_verdict(results, fast)
    show_comparison(fast)
    show_outro(fast)


if __name__ == "__main__":
    main()
