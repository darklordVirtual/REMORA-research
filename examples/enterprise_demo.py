#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""REMORA Enterprise Demo - 3-minute governance walkthrough.

Shows REMORA gating four realistic enterprise agent actions:

1. DROP TABLE customers    -> ESCALATE
2. router.set_config bgp   -> VERIFY
3. read_file report.csv    -> ACCEPT
4. bulk_export users/*     -> ABSTAIN

No API keys are needed. The demo uses the deterministic policy engine and
ASCII-safe output so it works in fresh Windows, macOS, and Linux terminals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box as rich_box

    _RICH = True
except ImportError:
    _RICH = False

from remora.policy import PolicyObservation, RemoraDecisionEngine


@dataclass(frozen=True)
class EnterpriseScenario:
    label: str
    title: str
    agent_intent: str
    tool_name: str
    tool_args: dict
    domain: str
    risk_tier: str
    phase: str
    trust_score: float
    H: float
    D: float
    policy_violation: bool = False
    unsafe: bool = False
    evidence_required: bool = False
    refuse_parametric: bool = False
    expected: str = "ACCEPT"
    why: str = ""


SCENARIOS: list[EnterpriseScenario] = [
    EnterpriseScenario(
        label="CRITICAL",
        title="Database wipe - production",
        agent_intent="Clean up deprecated customer records to free disk space.",
        tool_name="sql.execute",
        tool_args={"query": "DROP TABLE customers;", "db": "prod-rds-eu-west-1"},
        domain="database_operations",
        risk_tier="critical",
        phase="disordered",
        trust_score=0.002,
        H=1.58,
        D=0.71,
        policy_violation=True,
        unsafe=True,
        refuse_parametric=True,
        expected="ESCALATE",
        why=(
            "Hard block: policy_violation=True overrides oracle signals. "
            "Destructive write on production DB. No trust level clears this gate."
        ),
    ),
    EnterpriseScenario(
        label="VERIFY",
        title="BGP peer config change - core router",
        agent_intent="Apply a new BGP peer definition to reduce latency to EU PoPs.",
        tool_name="router.set_config",
        tool_args={"peer": "185.220.101.0/24", "action": "add_bgp_peer", "zone": "core"},
        domain="network_operations",
        risk_tier="high",
        phase="critical",
        trust_score=0.471,
        H=0.88,
        D=0.42,
        evidence_required=True,
        expected="VERIFY",
        why=(
            "Critical uncertainty phase. Trust below threshold "
            "(0.471 < 0.72). Evidence is required before a core network change."
        ),
    ),
    EnterpriseScenario(
        label="SAFE",
        title="Read quarterly report - finance",
        agent_intent="Fetch Q2 revenue report for executive summary generation.",
        tool_name="file.read",
        tool_args={"path": "finance/reports/Q2_2026_revenue.csv", "mode": "read"},
        domain="file_operations",
        risk_tier="low",
        phase="ordered",
        trust_score=0.946,
        H=0.12,
        D=0.04,
        expected="ACCEPT",
        why=(
            "Ordered phase, high trust, and read-only action. "
            "The agent can keep useful automation."
        ),
    ),
    EnterpriseScenario(
        label="ABSTAIN",
        title="Bulk-export all user data - GDPR scope",
        agent_intent="Export full user table for a third-party analytics partner.",
        tool_name="data.export",
        tool_args={"table": "users", "destination": "s3://partner-bucket/", "scope": "*"},
        domain="data_operations",
        risk_tier="high",
        phase="disordered",
        trust_score=0.009,
        H=1.61,
        D=0.69,
        refuse_parametric=True,
        expected="ABSTAIN",
        why=(
            "Disordered phase with no converging consensus on scope safety. "
            "REMORA abstains rather than guessing on a full-table export."
        ),
    ),
]


DECISION_MEANING = {
    "ESCALATE": "Blocked. Sent to human review queue.",
    "ABSTAIN": "Declined to act. No execution. No guess.",
    "VERIFY": "Paused. Awaiting evidence or human sign-off.",
    "ACCEPT": "Cleared. Agent may execute.",
}


DECISION_STYLE = {
    "ESCALATE": "red",
    "ABSTAIN": "blue",
    "VERIFY": "yellow",
    "ACCEPT": "green",
}


def _audit_hash(scenario: EnterpriseScenario, decision: str) -> str:
    snap = {
        "tool": scenario.tool_name,
        "args": scenario.tool_args,
        "phase": scenario.phase,
        "trust": round(scenario.trust_score, 4),
        "decision": decision,
    }
    raw = json.dumps(snap, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_observation(s: EnterpriseScenario) -> PolicyObservation:
    return PolicyObservation(
        question=s.agent_intent,
        phase=s.phase,
        trust_score=s.trust_score,
        final_H=s.H,
        final_D=s.D,
        adversarial_detected=s.policy_violation or s.unsafe,
        refuse_parametric_verdict=s.refuse_parametric and s.expected != "ABSTAIN",
        risk_tier=s.risk_tier,
        domain=s.domain,
        action_type="destructive_write" if s.unsafe else "tool_call",
        target_environment="prod" if s.unsafe else "staging",
        evidence_action="insufficient" if s.expected == "ABSTAIN" else None,
    )


def _run_scenario(s: EnterpriseScenario) -> tuple[str, str]:
    result = RemoraDecisionEngine().decide(_build_observation(s))
    action = result.action.upper()
    return action, _audit_hash(s, action)


def _plain_run(scenarios: list[EnterpriseScenario], fast: bool) -> None:
    print("\n" + "=" * 70)
    print("  REMORA Enterprise Demo - AI Action Governance")
    print("  v0.7.1 - research-grade prototype - Apache-2.0")
    print("=" * 70)

    for i, s in enumerate(scenarios, 1):
        action, audit = _run_scenario(s)
        print(f"\n[{i}/4] [{s.label}] {s.title}")
        print(f"       Tool : {s.tool_name}")
        print(f"       Args : {json.dumps(s.tool_args, separators=(',', ':'))}")
        print(f"       Phase: {s.phase} | trust={s.trust_score:.3f} | H={s.H:.2f} | D={s.D:.2f}")
        print(f"  -->  [{action}] {DECISION_MEANING[action]}")
        print(f"       Why  : {s.why}")
        print(f"       Hash : {audit}")
        if not fast:
            time.sleep(1.2)

    print("\n" + "=" * 70)
    print("  All decisions are replayable via state_hash.")
    print("  Run with --fast to skip pauses.")
    print("=" * 70 + "\n")


def _rich_run(scenarios: list[EnterpriseScenario], fast: bool) -> None:
    console = Console()
    console.print()
    console.rule("[bold]REMORA Enterprise Demo - AI Action Governance[/bold]")
    console.print(
        "[dim]v0.7.1 - research-grade prototype - Apache-2.0 - no API keys needed[/dim]\n",
        justify="center",
    )

    summary_rows: list[tuple[str, str, str, str]] = []
    for i, s in enumerate(scenarios, 1):
        action, audit = _run_scenario(s)
        color = DECISION_STYLE[action]

        if not fast:
            time.sleep(0.4)

        console.rule(f"[dim][{i}/4][/dim] [{s.label}] [bold]{s.title}[/bold]")
        tbl = Table(box=rich_box.SIMPLE, show_header=True, pad_edge=False)
        tbl.add_column("Field", style="dim", width=14)
        tbl.add_column("Value")
        tbl.add_row("Agent intent", f"[italic]{s.agent_intent}[/italic]")
        tbl.add_row("Tool", f"[cyan]{s.tool_name}[/cyan]")
        tbl.add_row("Args", json.dumps(s.tool_args, ensure_ascii=False))
        tbl.add_row("Domain / Risk", f"{s.domain} / {s.risk_tier}")
        tbl.add_row(
            "Signals",
            f"phase={s.phase} trust={s.trust_score:.3f} H={s.H:.2f} D={s.D:.2f}",
        )
        console.print(tbl)
        console.print(
            Panel(
                f"[{color} bold]{action}[/{color} bold]\n"
                f"[dim]{DECISION_MEANING[action]}[/dim]\n\n"
                f"[dim]{s.why}[/dim]\n\n"
                f"[dim]audit_hash: {audit}[/dim]",
                border_style=color,
                expand=False,
            )
        )
        summary_rows.append((s.label, s.title, action, audit))

        if not fast:
            time.sleep(1.0)

    console.print()
    console.rule("[bold]Decision Summary[/bold]")
    summary = Table(box=rich_box.ROUNDED, show_header=True)
    summary.add_column("#", width=3)
    summary.add_column("Scenario")
    summary.add_column("Decision", width=12)
    summary.add_column("Audit hash", style="dim", width=18)
    for i, (label, title, action, audit) in enumerate(summary_rows, 1):
        color = DECISION_STYLE[action]
        summary.add_row(str(i), f"[{label}] {title}", f"[{color} bold]{action}[/{color} bold]", audit)
    console.print(summary)
    console.print("\n[dim]All decisions are replayable via state_hash.[/dim]\n")
    console.rule("[dim]REMORA v0.7.1 - not production-certified - Apache-2.0[/dim]")
    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(description="REMORA enterprise governance demo")
    parser.add_argument("--fast", action="store_true", help="Skip pauses")
    parser.add_argument("--no-color", action="store_true", help="Plain text output")
    args = parser.parse_args()

    if _RICH and not args.no_color:
        _rich_run(SCENARIOS, fast=args.fast)
    else:
        _plain_run(SCENARIOS, fast=args.fast)


if __name__ == "__main__":
    main()
