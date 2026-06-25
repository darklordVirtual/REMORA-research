#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""
REMORA Shadow Mode — counterfactual governance replay demo.

Shadow Mode answers: "What would REMORA have done for this agent's past
actions?" — without touching production, modifying live systems, or
rerunning queries against live models.

Use it to:
  • Audit an existing agent deployment retroactively
  • Measure governance delta (how many unsafe calls would have been blocked)
  • Pilot REMORA before committing to production integration
  • Reproduce governance decisions from an audit trail

    python examples/shadow_mode_demo.py
    python examples/shadow_mode_demo.py --input path/to/your/agent_log.jsonl

Input format (one JSON object per line)
---------------------------------------
  {"question": "...", "domain": "...", "risk_tier": "...",
   "action_type": "...", "target_environment": "...",
   "trust_score": 0.85, "phase": "ordered", "unsafe": false}

All fields except ``question`` are optional.  ``unsafe: true`` flags
actions that were later found to be harmful (used for delta reporting).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich import box as rich_box
    _RICH = True
except ImportError:
    _RICH = False

from remora.shadow import replay_action_log, GovernanceDeltaReport


console = Console(highlight=False) if _RICH else None

DEMO_LOG = Path(__file__).parent.parent / "artifacts" / "demo" / "shadow_mode_sample_agent_action_log.jsonl"


def _print_delta_report(report: GovernanceDeltaReport) -> None:
    if console:
        # Decision breakdown table
        tbl = Table(
            box=rich_box.ROUNDED, border_style="cyan",
            show_header=True, header_style="bold cyan", padding=(0, 2),
        )
        tbl.add_column("Metric",  style="white", width=38)
        tbl.add_column("Value",   style="bold cyan", width=14)

        def bar(pct: float, width: int = 20) -> str:
            filled = int(pct / 100 * width)
            return "█" * filled + "░" * (width - filled)

        rows = [
            ("Actions reviewed",                     str(report.total_actions_reviewed)),
            ("", ""),
            ("✅  ACCEPT",                            f"{report.accepted}"),
            ("🔍  VERIFY (evidence/human required)",  f"{report.verify_required}"),
            ("⏸   ABSTAIN",                           f"{report.abstained}"),
            ("🚨  ESCALATE (blocked)",                f"{report.escalated}"),
            ("", ""),
            ("Critical actions proposed",             str(report.critical_actions_proposed)),
            ("Critical autonomous-accepts prevented", f"[bold red]{report.critical_false_accept}[/bold red]"),
            ("Policy violations detected",            f"[bold red]{report.policy_violations_detected}[/bold red]"),
            ("Missing evidence cases",                str(report.missing_evidence_cases)),
            ("Oracle disagreement cases",             str(report.oracle_disagreement_cases)),
            ("", ""),
            ("Audit completeness",                    f"[bold]{report.audit_completeness_pct:.1f}%[/bold]  {bar(report.audit_completeness_pct)}"),
            ("Estimated unsafe executions avoided",  f"[bold green]{report.estimated_avoided_unsafe_executions}[/bold green]"),
            ("Utility retained",                     f"[bold]{report.utility_retained_pct:.1f}%[/bold]  {bar(report.utility_retained_pct)}"),
            ("Human review burden",                  f"[bold]{report.human_review_burden_pct:.1f}%[/bold]  {bar(report.human_review_burden_pct, 12)}"),
        ]
        for label, value in rows:
            if not label:
                tbl.add_row("", "")
            else:
                tbl.add_row(label, value)

        console.print(tbl)
        console.print()

        # Baseline comparison
        if report.baseline_comparison:
            console.print(Rule("[bold]Baseline comparison[/bold]", style="dim"))
            console.print()
            btbl = Table(
                box=rich_box.ROUNDED, border_style="dim",
                show_header=True, header_style="bold dim", padding=(0, 1),
            )
            btbl.add_column("Strategy",          style="white",  width=28)
            btbl.add_column("Unsafe exec rate",  style="red",    width=16)
            btbl.add_column("Mean utility",      style="green",  width=14)
            btbl.add_column("Human burden %",    style="yellow", width=14)

            for strategy, metrics in report.baseline_comparison.items():
                unsafe_rate = metrics.get("unsafe_execution_rate", 0)
                utility     = metrics.get("mean_utility", 0)
                burden      = metrics.get("human_review_burden_pct", 0)
                style_u     = "bold green" if strategy == "remora_full_policy_gate" else "white"
                btbl.add_row(
                    f"[{style_u}]{strategy}[/{style_u}]",
                    f"[{'green' if unsafe_rate == 0 else 'red'}]{unsafe_rate:.1%}[/{'green' if unsafe_rate == 0 else 'red'}]",
                    f"{utility:.2f}",
                    f"{burden:.1f}%",
                )

            console.print(btbl)
            console.print()
    else:
        print(f"  Actions reviewed:  {report.total_actions_reviewed}")
        print(f"  ACCEPT:            {report.accepted}")
        print(f"  VERIFY:            {report.verify_required}")
        print(f"  ESCALATE:          {report.escalated}")
        print(f"  Unsafe avoided:    {report.estimated_avoided_unsafe_executions}")
        print(f"  Utility retained:  {report.utility_retained_pct:.1f}%")
        print(f"  Audit completeness:{report.audit_completeness_pct:.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="REMORA Shadow Mode replay demo")
    ap.add_argument(
        "--input", "-i", default=str(DEMO_LOG),
        help="Path to agent action log JSONL (default: included demo log)",
    )
    ap.add_argument("--out-dir", default="/tmp/remora_shadow_demo", help="Output directory")
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        print("Run from the REMORA repository root or pass --input path/to/log.jsonl")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    envelopes_out = str(out_dir / "decision_envelopes.jsonl")
    report_out    = str(out_dir / "governance_delta_report.json")
    audit_out     = str(out_dir / "replay_audit.jsonl")

    if console:
        console.print()
        console.print(Panel(
            "[bold cyan]REMORA Shadow Mode[/bold cyan]\n"
            "[white]Counterfactual governance replay[/white]\n\n"
            "[dim]Replay historical agent action logs through the REMORA policy engine\n"
            "to measure: what would have been blocked, verified, or escalated.[/dim]",
            border_style="cyan", padding=(1, 4), box=rich_box.DOUBLE,
        ))
        console.print()
        console.print(f"  [dim]Input:[/dim]  [white]{input_path}[/white]")
        console.print(f"  [dim]Output:[/dim] [white]{out_dir}[/white]")
        console.print()
        console.print(Rule("[bold]Running replay[/bold]", style="dim"))
        console.print()
    else:
        print("\n REMORA Shadow Mode\n")
        print(f"  Input:  {input_path}")
        print(f"  Output: {out_dir}\n")

    # Count lines first for progress display
    with open(input_path) as f:
        n_lines = sum(1 for _ in f)

    if console:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=32),
            TextColumn("[bold cyan]{task.completed}/{task.total}[/bold cyan] actions"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Replaying actions…", total=n_lines)
            result = replay_action_log(
                str(input_path),
                output_envelopes_jsonl=envelopes_out,
                output_report_json=report_out,
                output_audit_jsonl=audit_out,
            )
            progress.update(task, completed=n_lines)
    else:
        print(f"  Replaying {n_lines} actions…")
        result = replay_action_log(
            str(input_path),
            output_envelopes_jsonl=envelopes_out,
            output_report_json=report_out,
            output_audit_jsonl=audit_out,
        )

    if console:
        console.print(Rule("[bold cyan]Governance Delta Report[/bold cyan]", style="cyan"))
        console.print()

    _print_delta_report(result.report)

    if console:
        console.print(Panel(
            f"  [bold]Output artifacts[/bold]\n"
            f"  [dim]Decision envelopes:[/dim]  [white]{envelopes_out}[/white]\n"
            f"  [dim]Delta report JSON:[/dim]   [white]{report_out}[/white]\n"
            f"  [dim]Audit chain JSONL:[/dim]   [white]{audit_out}[/white]\n\n"
            f"  [dim]Each envelope contains the full thermodynamic state (H, D, F, phase),\n"
            f"  policy triggers, and SHA-256 audit hash for every replayed action.[/dim]",
            title="[bold]Outputs[/bold]",
            border_style="cyan", padding=(0, 2),
        ))
        console.print()
    else:
        print(f"\n  Outputs written to: {out_dir}")
        print("  decision_envelopes.jsonl | governance_delta_report.json | replay_audit.jsonl\n")


if __name__ == "__main__":
    main()
