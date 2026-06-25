#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""
REMORA × CrewAI — governance overlay example.

Demonstrates how to gate CrewAI tool calls through REMORA before execution.
No CrewAI installation required — the adapter is framework-decoupled.

    python examples/crewai_integration.py

Key pattern
-----------
  1. Wrap every BaseTool._run() body with CrewAIActionAdapter.intercept_tool()
  2. Check result.should_execute before calling the real tool logic
  3. Log result.envelope for full audit trail

Policy routing by risk tier (with calibrated trust params)
----------------------------------------------------------
  low      → H=0.30 D=0.08 phase=ordered    trust=0.92  → ACCEPT
  medium   → H=0.70 D=0.25 phase=critical   trust=0.74  → VERIFY
  high     → H=1.10 D=0.50 phase=critical   trust=0.55  → VERIFY
  critical → H=1.60 D=0.75 phase=disordered trust=0.30  → ESCALATE
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

from remora.adapters.action_gate import ActionGateResult, CrewAIActionAdapter
from remora.adapters.gateway import GatewayResult
from remora.policy import PolicyObservation, RemoraDecisionEngine


# ---------------------------------------------------------------------------
# Risk-tier → thermodynamic parameter mapping
# ---------------------------------------------------------------------------

_TIER_PARAMS: dict[str, dict] = {
    "low":      dict(phase="ordered",    H=0.30, D=0.08, trust=0.92),
    "medium":   dict(phase="critical",   H=0.70, D=0.25, trust=0.74),
    "high":     dict(phase="critical",   H=1.10, D=0.50, trust=0.55),
    "critical": dict(phase="disordered", H=1.60, D=0.75, trust=0.30),
}


class DirectPolicyGateway:
    """Wraps RemoraDecisionEngine with risk-tier-calibrated thermodynamics."""

    def __init__(self, risk_tier: str = "medium") -> None:
        self._engine = RemoraDecisionEngine()
        self._risk_tier = risk_tier
        self._prev_hash = "0" * 64

    def assess_sync(
        self,
        question: str,
        *,
        context=None,
        domain=None,
        risk_tier=None,
        action_type=None,
        target_environment=None,
    ) -> GatewayResult:
        tier = risk_tier or self._risk_tier
        p = _TIER_PARAMS.get(tier, _TIER_PARAMS["medium"])
        obs = PolicyObservation(
            question=question,
            phase=p["phase"], trust_score=p["trust"],
            final_H=p["H"], final_D=p["D"],
            risk_tier=tier, domain=domain,
            action_type=action_type or "tool_call",
            target_environment=target_environment or "prod",
        )
        report = self._engine.decide(obs)
        action = report.action.value if hasattr(report.action, "value") else str(report.action)
        h = hashlib.sha256(f"{self._prev_hash}:{question[:40]}:{action}".encode()).hexdigest()
        self._prev_hash = h
        return GatewayResult(
            action=action,
            human_review_required=report.human_review_required,
            evidence_required=report.evidence_required,
            explanation="; ".join(
                r.value if hasattr(r, "value") else str(r) for r in report.reasons
            ),
            confidence=p["trust"],
            risk_estimate=None,
            require_rag=False,
            refuse_parametric_verdict=False,
            source_of_decision="direct_policy",
            state_hash=h,
        )


# ---------------------------------------------------------------------------
# Simulated CrewAI BaseTool
# ---------------------------------------------------------------------------

@dataclass
class GovernedTool:
    """Simulates a CrewAI BaseTool with REMORA governance wired in."""
    name: str
    description: str
    risk_tier: str
    domain: str
    action_type: str
    agent_role: str

    def __post_init__(self):
        self._adapter = CrewAIActionAdapter(
            gateway=DirectPolicyGateway(risk_tier=self.risk_tier)
        )
        self.calls: list[ActionGateResult] = []

    def _run(self, **kwargs) -> str:
        result = self._adapter.intercept_tool(
            tool_name=self.name,
            tool_input=kwargs,
            agent_role=self.agent_role,
            domain=self.domain,
            risk_tier=self.risk_tier,
            action_type=self.action_type,
            target_environment="prod",
        )
        self.calls.append(result)
        if result.should_execute:
            return f"[EXECUTED] {self.name}({kwargs}) → success"
        return f"[BLOCKED by REMORA: {result.envelope.gate.outcome}] {self.name}"


# ---------------------------------------------------------------------------
# Demo crew with 4 tools across risk tiers
# ---------------------------------------------------------------------------

TOOLS = [
    GovernedTool("web_search", "Search the web", "low", "research", "read", "research-analyst"),
    GovernedTool("send_report_email", "Email stakeholders", "medium", "comms", "write", "comms-agent"),
    GovernedTool("update_customer_record", "Update CRM record", "high", "crm", "write", "crm-agent"),
    GovernedTool("delete_all_inactive_users", "Bulk delete users", "critical", "user-mgmt",
                 "destructive_write", "cleanup-agent"),
]
CALLS = [
    {"query": "latest AI governance frameworks 2025"},
    {"to": "team@acme.com", "subject": "Weekly digest"},
    {"user_id": "u-4421", "field": "plan", "value": "enterprise"},
    {"older_than_days": 365, "dry_run": False},
]

# Expected outcomes by tier
_EXPECTED: dict[str, set] = {
    "low": {"accept"},
    "medium": {"verify", "accept"},
    "high": {"verify", "escalate"},
    "critical": {"verify", "escalate", "abstain"},
}


def main() -> int:
    print("=" * 65)
    print("  REMORA × CrewAI — Governance Overlay Demo")
    print("=" * 65)

    failed = 0
    for tool, call_args in zip(TOOLS, CALLS):
        result_str = tool._run(**call_args)
        r = tool.calls[-1]
        outcome = r.envelope.gate.outcome
        symbol = "✓" if r.should_execute else "○"
        print(f"\n  {symbol} [{tool.risk_tier.upper():8}] {tool.name}")
        print(f"    args   : {call_args}")
        print(f"    outcome: {outcome}")
        print(f"    result : {result_str[:70]}")
        if outcome not in _EXPECTED[tool.risk_tier]:
            print(f"    FAIL: unexpected outcome '{outcome}' for {tool.risk_tier}")
            failed += 1

    print("\n" + "=" * 65)
    # Structural checks
    for tool in TOOLS:
        env = tool.calls[-1].envelope
        assert env.request.request_id
        assert env.audit.hash
        assert env.gate.outcome in ("accept", "verify", "abstain", "escalate")

    print("  Envelope structure : OK")
    print(f"  CrewAI adapter     : {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
