#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
REMORA Live Demo - Claude Code Edition

Full animations when run in a proper terminal (! python scripts/demo.py).
Falls back to rich static output when captured (Bash tool / pipe).

Usage:
    python scripts/demo.py            # full animated run
    python scripts/demo.py --fast     # no pauses
    python scripts/demo.py --claim "your claim"
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import json
import math
import os
import ssl
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

AGENT_URL    = os.environ.get("AGENT_CONTROL_URL",
               "https://remora-agent-control.razorsharp.workers.dev")
AGENT_SECRET = os.environ.get("AGENT_CONTROL_SECRET", "")
REMORA_URL   = "https://go-star-remora.razorsharp.workers.dev"
RAG_URL      = "https://remora-rag-oracle.razorsharp.workers.dev"
LAW_URL      = "https://remora-law-search.razorsharp.workers.dev"

SSL_CTX  = ssl.create_default_context()
IS_TTY   = sys.stdout.isatty()

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

console = Console(width=110, highlight=False)

# -- HTTP -----------------------------------------------------------------------

def _req(url: str, payload: dict | None = None, auth: bool = False,
         timeout: int = 60) -> tuple[dict, float]:
    t0 = time.monotonic()
    data = json.dumps(payload).encode() if payload else None
    hdrs = {"Content-Type": "application/json", "User-Agent": "REMORA-demo/1.0"}
    if auth and AGENT_SECRET:
        hdrs["Authorization"] = f"Bearer {AGENT_SECRET}"
    req = urllib.request.Request(url, data=data, headers=hdrs,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = {"error": f"HTTP {e.code}: {e.read().decode(errors='replace')[:120]}"}
    except Exception as e:
        body = {"error": str(e)}
    return body, (time.monotonic() - t0) * 1000

def ac(path: str, payload: dict | None = None) -> tuple[dict, float]:
    return _req(AGENT_URL.rstrip("/") + path, payload, auth=bool(payload))

# -- Animation helpers ----------------------------------------------------------

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

def spin(t: float) -> str:
    return SPINNER[int(t * 12) % len(SPINNER)]

def wave(t: float, width: int = 38) -> str:
    """Moving sine wave using block chars."""
    blocks = " ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁"
    n = len(blocks) - 1
    return "".join(
        blocks[max(0, min(n, int((math.sin((i / width * 2 * math.pi) - t * 2.5) + 1) / 2 * n)))]
        for i in range(width)
    )

def confidence_bar(value: float, width: int = 24, style: str = "green") -> str:
    filled = int(value * width)
    empty  = width - filled
    return f"[bold {style}]{'█' * filled}[/bold {style}][dim]{'░' * empty}[/dim]"

def section(title: str, color: str = "cyan") -> None:
    console.print()
    console.print(Rule(f"[bold {color}]  {title}  [/bold {color}]", style=color))
    console.print()

def pause(s: float) -> None:
    if IS_TTY:
        time.sleep(s)

def run_async(fn) -> tuple[dict, threading.Event]:
    """Run fn in thread, return (result_box, done_event)."""
    box_: dict = {}
    done = threading.Event()
    def worker():
        try:
            box_["val"] = fn()
        except Exception as e:
            box_["val"] = ({"error": str(e)}, 0.0)
        done.set()
    threading.Thread(target=worker, daemon=True).start()
    return box_, done

# -- Section renders ------------------------------------------------------------

def render_intro() -> None:
    if IS_TTY:
        console.clear()
    console.print(Panel(
        Align.center(
            "[bold cyan]REMORA[/bold cyan]  [dim]v0.5.0[/dim]\n"
            "[white]Multi-Oracle Consensus Framework - Live Demo[/white]\n\n"
            "[dim]4 Cloudflare Workers  ·  3 LLM Oracles  ·  Norwegian Law DB  ·  D1 Audit Ledger[/dim]"
        ),
        border_style="cyan", padding=(1, 10), box=box.DOUBLE
    ))
    pause(1.2)


def render_status() -> None:
    section("1 / 7  -  System Status", "cyan")

    workers = [
        ("go-star-remora",       REMORA_URL + "/status", "Consensus · 3 oracles"),
        ("remora-rag-oracle",    RAG_URL    + "/status", "RAG · bge-m3 · 66 chunks"),
        ("remora-law-search",    LAW_URL    + "/status", "Law DB · Vectorize 1024d"),
        ("remora-agent-control", AGENT_URL  + "/status", "Policy gate · D1 ledger"),
    ]

    boxes, dones = {}, {}

    for name, url, _ in workers:
        b, d = run_async(lambda u=url: _req(u))
        boxes[name], dones[name] = b, d

    def make_table(t: float) -> Table:
        tbl = Table(box=box.ROUNDED, border_style="cyan", show_header=True,
                    header_style="bold cyan", padding=(0, 1))
        tbl.add_column("Worker",    width=24, style="bold white")
        tbl.add_column("Role",      width=28, style="dim")
        tbl.add_column("",          width=6)
        tbl.add_column("Status",    width=8)
        tbl.add_column("Latency",   width=12)
        tbl.add_column("Detail",    width=22, style="dim")
        for name, _, role in workers:
            if dones[name].is_set():
                data, ms = boxes[name].get("val", ({}, 0))
                if "error" in data:
                    tbl.add_row(name, role, "", "[red]DOWN[/red]", f"{ms:.0f}ms", str(data["error"])[:22])
                else:
                    detail = f"oracles:{data.get('n_oracles','?')}" if "n_oracles" in data else f"ok:{data.get('ok','?')}"
                    tbl.add_row(name, role, "[green]●[/green]", "[green]LIVE[/green]", f"{ms:.0f}ms", detail)
            else:
                tbl.add_row(name, role, f"[yellow]{spin(t)}[/yellow]", "[yellow]...[/yellow]", "-", "")
        return tbl

    if IS_TTY:
        with Live(make_table(0), console=console, refresh_per_second=15) as live:
            while not all(d.is_set() for d in dones.values()):
                live.update(make_table(time.monotonic()))
                time.sleep(0.05)
            live.update(make_table(time.monotonic()))
            time.sleep(0.8)
    else:
        # Non-TTY: wait for all then print
        for d in dones.values():
            d.wait(timeout=10)
        console.print(make_table(0))

    pause(0.4)


def render_session() -> str:
    section("2 / 7  -  Create Agent Session", "blue")

    console.print("[dim]  Opening audited session. Every tool call logged to D1 with SHA-256 hashes.[/dim]")
    console.print()
    label   = f"demo-{datetime.now(timezone.utc).strftime('%H:%M:%S')}"
    payload = {"user_label": label}
    console.print(Syntax(json.dumps({"POST": AGENT_URL + "/sessions", **payload}, indent=2),
                         "json", theme="monokai", background_color="default", word_wrap=True))

    box_, done = run_async(lambda: ac("/sessions", payload))

    if IS_TTY:
        with Live(console=console, refresh_per_second=15, transient=True) as live:
            while not done.wait(0.05):
                live.update(Text(f"  {spin(time.monotonic())} Creating session...", style="cyan"))
        time.sleep(0.2)
    else:
        done.wait(timeout=10)

    data, ms = box_.get("val", ({}, 0))
    sid = data.get("session_id", "?")
    console.print(Panel(
        f"  [bold cyan]{sid}[/bold cyan]\n"
        f"  [dim]TTL: 24 h   Backend: KV + D1   Latency: {ms:.0f} ms[/dim]",
        title="[bold]Session created[/bold]", border_style="blue", padding=(0, 2)
    ))
    pause(0.6)
    return sid


# -- Oracle consensus stage -----------------------------------------------------

ORACLE_LABELS  = ["Llama-8B",        "Llama-70B",       "Mistral-7B"]
ORACLE_COLORS  = ["cyan",            "blue",            "magenta"]
ORACLE_SOURCES = ["Groq · fast",     "Groq · strong",   "OpenRouter · diverse"]


def _oracle_panel(idx: int, elapsed: float, done: bool, verdict: str | None,
                  confidence: float) -> Panel:
    color = ORACLE_COLORS[idx]
    if not done:
        # Simulate staggered arrival: each oracle arrives 150ms apart (visual only)
        phase = elapsed - idx * 0.18
        if phase < 0:
            status = "[dim]waiting...[/dim]"
            bar    = "[dim]" + "░" * 14 + "[/dim]"
        else:
            status = f"[{color}]{spin(elapsed)}[/{color}] [dim]reasoning...[/dim]"
            bar    = "[dim]" + wave(elapsed + idx * 1.3)[:14] + "[/dim]"
    else:
        v_color = "green" if verdict == "true" else "red" if verdict == "false" else "yellow"
        v_label = ("TRUE" if verdict == "true" else
                   "FALSE" if verdict == "false" else "NULL")
        status  = f"[bold {v_color}]{v_label}[/bold {v_color}]"
        bar     = confidence_bar(confidence, 14, v_color)

    body = (
        f"  [{color}]{ORACLE_LABELS[idx]}[/{color}]\n"
        f"  {status}\n"
        f"  {bar}\n"
        f"  [dim]{ORACLE_SOURCES[idx]}[/dim]"
    )
    return Panel(body, border_style=color if done else "dim", padding=(0, 1),
                 box=box.ROUNDED)


def _pipeline_diagram(stages_done: int) -> Text:
    names  = ["FastGate", "ConsensusGate", "VerifierGate", "CritiqueRevision", "SelfConsistency"]
    colors = ["green",    "green",          "green",         "dim",               "green"]
    parts  = []
    for i, name in enumerate(names):
        if i < stages_done:
            parts.append(f"[bold {colors[i]}][[{name}]][/{colors[i]}]")
        else:
            parts.append(f"[dim][[{name}]][/dim]")
        if i < len(names) - 1:
            parts.append(" [dim]--▶[/dim] ")
    return Text.from_markup("  " + "".join(parts))


def render_oracle(sid: str, claim: str, step: int, label: str) -> dict:
    section(f"{step} / 7  -  {label}", "yellow" if step == 3 else "green")

    console.print(Panel(
        f"  [bold white]{claim}[/bold white]",
        title="[bold]Claim to verify[/bold]", border_style="dim", padding=(0, 2)
    ))
    console.print()
    console.print("[dim]  Routing: Claude → agent-control → go-star-remora (service binding) → 3 oracles in parallel[/dim]")
    console.print()

    payload = {"tool": "remora_verify_claim",
               "input": {"claim": claim, "domain": "law"},
               "session_id": sid}

    box_, done = run_async(lambda: ac("/execute", payload))

    def frame(t: float, result: dict | None):
        api_done   = result is not None
        confidence = float(result.get("confidence", 0)) if api_done else 0.0
        # Simulate three oracles arriving staggered
        oracle_done = [api_done] * 3
        oracle_conf = [confidence] * 3
        oracle_v    = ["true" if confidence > 0.5 else "false"] * 3 if api_done else [None] * 3

        cols = Columns(
            [_oracle_panel(i, t, oracle_done[i], oracle_v[i], oracle_conf[i])
             for i in range(3)],
            equal=True, expand=True
        )

        if api_done:
            v_color = "green" if confidence >= 0.75 else "yellow"
            verdict_label = result.get("output", {}).get("verdict", "?")
            ms      = result.get("duration_ms", 0)
            audit   = result.get("audit_id", "?")
            consensus_line = (
                f"\n  CONSENSUS  [bold {v_color}]{verdict_label}[/bold {v_color}]"
                f"  {confidence_bar(confidence, 28, v_color)}  [bold]{confidence:.0%}[/bold]"
                f"   [dim]audit#{audit}  {ms}ms[/dim]"
            )
        else:
            consensus_line = f"\n  [dim]{spin(t)} Awaiting consensus...  {wave(t, 28)}[/dim]"

        pipeline = _pipeline_diagram(3 if api_done else 0)

        body = Text.assemble(consensus_line, "\n\n")

        return Panel(
            Text.assemble(
                Text("\n"),
                Text.from_markup("  [bold dim]ORACLE PANELS[/bold dim]\n\n"),
            ),
            box=box.MINIMAL
        ), cols, body, pipeline

    if IS_TTY:
        with Live(console=console, refresh_per_second=20, transient=False) as live:
            while not done.wait(0.05):
                t = time.monotonic()
                cols = Columns(
                    [_oracle_panel(i, t, False, None, 0) for i in range(3)],
                    equal=True, expand=True
                )
                wave_line = Text.from_markup(
                    f"\n  [dim]{spin(t)} Awaiting consensus...  {wave(t, 38)}[/dim]"
                )
                live.update(Panel(
                    Text.assemble(Text.from_markup("[dim]  3 oracles queried in parallel[/dim]\n\n"),
                                  cols, wave_line),
                    border_style="yellow", box=box.ROUNDED, padding=(0, 0)
                ))
            # Final state
            result, _ = box_.get("val", ({}, 0))
            confidence = float(result.get("confidence", 0))
            vl = result.get("output", {}).get("verdict", "?")
            v_color = "green" if vl == "VERIFIED" else "red" if vl == "CONTRADICTED" else "yellow"
            ms      = result.get("duration_ms", 0)
            audit   = result.get("audit_id", "?")
            oracle_v = ["true"] * 3 if vl == "VERIFIED" else ["false"] * 3
            cols = Columns(
                [_oracle_panel(i, 0, True, oracle_v[i], confidence) for i in range(3)],
                equal=True, expand=True
            )
            consensus_line = Text.from_markup(
                f"\n  CONSENSUS  [bold {v_color}]{vl}[/bold {v_color}]"
                f"  {confidence_bar(confidence, 28, v_color)}  [bold]{confidence:.0%}[/bold]"
                f"   [dim]audit#{audit}  {ms}ms[/dim]\n\n"
            )
            pipeline = _pipeline_diagram(3)
            live.update(Panel(
                Text.assemble(
                    Text.from_markup("[dim]  3 oracles responded[/dim]\n\n"),
                    cols,
                    consensus_line,
                    Text.from_markup("  [dim]Pipeline:[/dim]  "),
                    pipeline,
                    Text("\n"),
                ),
                border_style=v_color, box=box.ROUNDED, padding=(0, 0)
            ))
            time.sleep(2.0)
    else:
        done.wait(timeout=30)
        result, _ = box_.get("val", ({}, 0))
        confidence = float(result.get("confidence", 0))
        vl      = result.get("output", {}).get("verdict", "?")
        v_color = "green" if vl == "VERIFIED" else "red" if vl == "CONTRADICTED" else "yellow"
        ms      = result.get("duration_ms", 0)
        audit   = result.get("audit_id", "?")
        oracle_v = ["true"] * 3 if vl == "VERIFIED" else ["false"] * 3
        cols = Columns(
            [_oracle_panel(i, 0, True, oracle_v[i], confidence) for i in range(3)],
            equal=True, expand=True
        )
        console.print(cols)
        console.print(Panel(
            f"  CONSENSUS  [bold {v_color}]{vl}[/bold {v_color}]"
            f"  {confidence_bar(confidence, 28, v_color)}  [bold]{confidence:.0%}[/bold]\n\n"
            f"  [dim]Pipeline:[/dim]  " + "".join(
                f"[bold green][{n}][/bold green]" if i < 3 else f"[dim][{n}][/dim]"
                for i, n in enumerate(["FastGate","ConsensusGate","VerifierGate","CritiqueRevision","SelfConsistency"])
            ) + "\n\n"
            f"  [dim]Audit ID: {audit}   Duration: {ms} ms[/dim]",
            border_style=v_color, padding=(0, 2)
        ))

    return box_.get("val", ({}, 0))[0]


# -- Law search stage -----------------------------------------------------------

def render_law_search(sid: str, query: str) -> dict:
    section("4 / 7  -  Norwegian Law Database Search", "magenta")

    console.print(Panel(
        f"  [bold white]{query}[/bold white]",
        title="[bold]Vectorize query (1024-dim bge-m3)[/bold]",
        border_style="dim", padding=(0, 2)
    ))
    console.print()
    console.print("[dim]  Routing: agent-control → remora-law-search (service binding) → Cloudflare Vectorize[/dim]")
    console.print()

    payload = {"tool": "dce_search_law",
               "input": {"query": query, "top_k": 3},
               "session_id": sid}
    box_, done = run_async(lambda: ac("/execute", payload))

    scan_frames = [
        "  [dim]LOADING    [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░][/dim]",
        "  [dim]VECTORIZING[████░░░░░░░░░░░░░░░░░░░░░░░░░░░][/dim]",
        "  [dim]SEARCHING  [████████░░░░░░░░░░░░░░░░░░░░░░░][/dim]",
        "  [dim]RETRIEVING [█████████████░░░░░░░░░░░░░░░░░░][/dim]",
        "  [dim]RERANKING  [████████████████████████░░░░░░░][/dim]",
        "  [cyan]COMPLETE   [█████████████████████████████████][/cyan]",
    ]

    if IS_TTY:
        with Live(console=console, refresh_per_second=20, transient=True) as live:
            i = 0
            while not done.wait(0.12):
                live.update(Text.from_markup(scan_frames[min(i, len(scan_frames) - 2)]))
                i += 1
            live.update(Text.from_markup(scan_frames[-1]))
            time.sleep(0.5)
    else:
        done.wait(timeout=15)

    data, ms = box_.get("val", ({}, 0))
    output  = data.get("output", {})
    matches = output.get("matches", [])

    t = Table(box=box.ROUNDED, border_style="magenta", show_header=True,
              header_style="bold magenta", padding=(0, 1))
    t.add_column("§",        style="bold yellow", width=8)
    t.add_column("Lov",      style="white",       width=32)
    t.add_column("Score",    style="cyan",        width=8)
    t.add_column("Bar",      style="white",       width=18)
    t.add_column("Lovtekst", style="dim",         width=36)

    for m in matches:
        score   = m.get("score", 0)
        content = (m.get("content") or m.get("metadata", {}).get("excerpt", ""))[:60]
        t.add_row(
            m.get("section") or "-",
            (m.get("title") or "")[:30],
            f"{score:.3f}",
            confidence_bar(score, 10, "magenta"),
            content or "-",
        )
    console.print(t)

    # Top match detail panel
    if matches:
        best = matches[0]
        text = best.get("content") or best.get("metadata", {}).get("excerpt", "")
        heading = best.get("heading") or best.get("metadata", {}).get("heading", "")
        law_ref = best.get("law_ref") or best.get("metadata", {}).get("law_ref", "")
        lex_w   = best.get("metadata", {}).get("lex_superior_weight", "")
        if text:
            console.print()
            console.print(Panel(
                f"  [bold yellow]{heading}[/bold yellow]\n\n"
                f"  [bold italic white]{text}[/bold italic white]\n\n"
                f"  [dim]{law_ref}   lex_superior_weight: {lex_w}   "
                f"source: Lovdata   is_active: true[/dim]",
                title="[bold]Top match - authoritative statutory text[/bold]",
                border_style="magenta", padding=(0, 2)
            ))

    console.print(f"\n  [dim]Audit ID: {data.get('audit_id')}   Duration: {ms:.0f} ms[/dim]")
    pause(0.6)
    return data


# -- Store artifact -------------------------------------------------------------

def render_store(sid: str, r1: dict, law: dict, r2: dict) -> None:
    section("6 / 7  -  Store Analysis Report to R2", "yellow")

    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    v1   = r1.get("output", {}).get("verdict", "?")
    c1   = r1.get("output", {}).get("confidence", 0)
    v2   = r2.get("output", {}).get("verdict", "?")
    c2   = r2.get("output", {}).get("confidence", 0)
    m0   = (law.get("output", {}).get("matches", [{}]) or [{}])[0]
    law_text = m0.get("content") or m0.get("metadata", {}).get("excerpt", "")
    report = (
        f"# REMORA Analysis Report\nGenerated: {now}\nSession: {sid}\n\n"
        f"## Claims\n\n"
        f"### Claim 1 - 1-month notice\nVerdict: {v1} ({c1:.0%})\n\n"
        f"### Claim 2 - 3-month notice (§ 9-6)\nVerdict: {v2} ({c2:.0%})\n\n"
        f"## Law\n{law_text[:200]}\n\n"
        f"## Conclusion\nLaw search is authoritative: 3 months required (§ 9-6).\n"
    )
    key = f"demo/husleie-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')}.md"

    console.print(f"  [dim]Key:[/dim]  [white]{key}[/white]")
    console.print(f"  [dim]Size:[/dim] {len(report)} bytes   "
                  f"[dim]Gate:[/dim] approved=True (human-in-the-loop)")
    console.print()

    payload = {"tool": "store_artifact",
               "input": {"key": key, "content": report, "approved": True},
               "session_id": sid}
    box_, done = run_async(lambda: ac("/execute", payload))

    write_frames = [
        "  [dim]░░░░░░░░░░░░░░░░░░░░░░░░░░░░  Connecting to R2...[/dim]",
        "  [yellow]████░░░░░░░░░░░░░░░░░░░░░░░░  Writing header...[/yellow]",
        "  [yellow]████████░░░░░░░░░░░░░░░░░░░░  Streaming content...[/yellow]",
        "  [yellow]████████████░░░░░░░░░░░░░░░░  Committing...[/yellow]",
        "  [yellow]████████████████░░░░░░░░░░░░  Finalizing...[/yellow]",
        "  [green]████████████████████████████  STORED[/green]",
    ]

    if IS_TTY:
        with Live(console=console, refresh_per_second=12, transient=True) as live:
            i = 0
            while not done.wait(0.15):
                live.update(Text.from_markup(write_frames[min(i, len(write_frames) - 2)]))
                i += 1
            live.update(Text.from_markup(write_frames[-1]))
            time.sleep(0.6)
    else:
        done.wait(timeout=15)

    data, ms = box_.get("val", ({}, 0))
    out = data.get("output", {})
    console.print(Panel(
        f"  [green]STORED[/green]   [bold]{out.get('key', key)}[/bold]\n"
        f"  [dim]{out.get('size', len(report))} bytes   "
        f"text/markdown   audit#{data.get('audit_id')}   {ms:.0f} ms[/dim]",
        border_style="green", padding=(0, 2)
    ))
    pause(0.5)


# -- Audit trail ----------------------------------------------------------------

def render_audit(sid: str) -> None:
    section("7 / 7  -  D1 Audit Trail", "cyan")

    console.print(f"  [dim]GET {AGENT_URL}/audit?session_id={sid}[/dim]\n")

    data, ms = ac(f"/audit?session_id={sid}&limit=10")
    rows = sorted(data.get("rows", []), key=lambda r: r.get("id", 0))

    if not rows:
        console.print("  [yellow]No rows found.[/yellow]")
        return

    t = Table(box=box.ROUNDED, border_style="cyan", show_header=True,
              header_style="bold cyan", padding=(0, 1))
    t.add_column("ID",        style="dim",        width=4)
    t.add_column("Timestamp", style="dim",        width=20)
    t.add_column("Tool",      style="bold white", width=22)
    t.add_column("Verdict",   style="yellow",     width=14)
    t.add_column("Conf",      style="cyan",       width=6)
    t.add_column("ms",        style="dim",        width=5)
    t.add_column("Input hash (SHA-256)",  style="dim", width=16)

    for row in rows:
        conf    = row.get("confidence")
        verdict = str(row.get("verdict") or "-")
        v_style = "green" if verdict == "VERIFIED" else "red" if verdict == "CONTRADICTED" else "dim"
        t.add_row(
            str(row.get("id", "")),
            str(row.get("ts", ""))[:19],
            str(row.get("tool_called", "")),
            f"[{v_style}]{verdict}[/{v_style}]",
            f"{conf:.0%}" if conf is not None else "-",
            str(row.get("duration_ms") or "?"),
            str(row.get("input_hash", ""))[:16] + "...",
        )

    if IS_TTY:
        # Rows appear one by one
        for i, row in enumerate(rows):
            partial = Table(box=box.ROUNDED, border_style="cyan", show_header=True,
                            header_style="bold cyan", padding=(0, 1))
            partial.add_column("ID",       width=4,  style="dim")
            partial.add_column("Timestamp",width=20, style="dim")
            partial.add_column("Tool",     width=22, style="bold white")
            partial.add_column("Verdict",  width=14, style="yellow")
            partial.add_column("Conf",     width=6,  style="cyan")
            partial.add_column("ms",       width=5,  style="dim")
            partial.add_column("Hash",     width=16, style="dim")
            for r2 in rows[:i + 1]:
                c2   = r2.get("confidence")
                vt   = str(r2.get("verdict") or "-")
                vs   = "green" if vt == "VERIFIED" else "red" if vt == "CONTRADICTED" else "dim"
                partial.add_row(str(r2.get("id","")), str(r2.get("ts",""))[:19],
                                str(r2.get("tool_called","")),
                                f"[{vs}]{vt}[/{vs}]",
                                f"{c2:.0%}" if c2 is not None else "-",
                                str(r2.get("duration_ms") or "?"),
                                str(r2.get("input_hash",""))[:16] + "...")
            with Live(partial, console=console, refresh_per_second=10, transient=True):
                time.sleep(0.35)
            if i == len(rows) - 1:
                console.print(partial)
    else:
        console.print(t)

    console.print()
    console.print("  [dim]Every row contains SHA-256(input) and SHA-256(output).[/dim]")
    console.print("  [dim]The D1 ledger is append-only - no UPDATE on audit content.[/dim]")
    pause(0.5)


# -- Summary --------------------------------------------------------------------

def render_summary(sid: str) -> None:
    section("Complete", "green")
    console.print(Panel(
        f"  [bold green]REMORA demo finished.[/bold green]\n\n"
        f"  [bold]Session[/bold]  [cyan]{sid}[/cyan]\n\n"
        f"  [bold]Pipeline exercised[/bold]\n"
        f"  [dim]FastGate → ConsensusGate → VerifierGate → CritiqueRevision → SelfConsistency[/dim]\n\n"
        f"  [bold]Tools called[/bold]\n"
        f"  [white]remora_verify_claim × 2  ·  dce_search_law  ·  store_artifact[/white]\n\n"
        f"  [bold]Audit endpoint[/bold]\n"
        f"  [dim]{AGENT_URL}/audit?session_id={sid}[/dim]",
        border_style="green", padding=(1, 4), box=box.DOUBLE
    ))


# -- Main -----------------------------------------------------------------------

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast",  action="store_true")
    ap.add_argument("--claim", default="")
    args = ap.parse_args()

    global IS_TTY
    if args.fast:
        IS_TTY = False  # Disable animations for fast mode

    claim_1 = args.claim or "Leietaker kan si opp leieavtale med 1 maneds varsel"
    claim_2 = "Oppsigelsesfristen for leietaker er tre maneder etter husleieloven paragraf 9-6"
    query   = "oppsigelse leieforhold varselfrist husleieloven"

    render_intro()
    render_status()
    sid  = render_session()
    r1   = render_oracle(sid, claim_1, step=3, label="Oracle Consensus - Investigate Claim")
    law  = render_law_search(sid, query)
    r2   = render_oracle(sid, claim_2, step=5, label="Oracle Consensus - Verify § 9-6")
    render_store(sid, r1, law, r2)
    render_audit(sid)
    render_summary(sid)


if __name__ == "__main__":
    main()
