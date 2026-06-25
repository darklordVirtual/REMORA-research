#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""
REMORA × AutoGen — governance overlay example.

Demonstrates how to gate AutoGen function/tool calls through REMORA.
No AutoGen installation required — the adapter is framework-decoupled.

    python examples/autogen_integration.py

Key pattern
-----------
  1. Wrap every registered function body with AutoGenActionAdapter.intercept_function_call()
  2. Check result.should_execute before executing the real function
  3. Return a governance-aware error string when blocked

Real-world wiring
-----------------
    from autogen import ConversableAgent, register_function
    from remora.adapters.action_gate import AutoGenActionAdapter

    adapter = AutoGenActionAdapter(gateway=DirectPolicyGateway())

    def governed_run_bash(command: str) -> str:
        result = adapter.intercept_function_call(
            func_name="run_bash",
            func_args={"command": command},
            agent_name="ExecutorAgent",
            domain="code-execution",
            risk_tier="critical",
            action_type="execute",
            target_environment="sandbox",
        )
        if not result.should_execute:
            return f"BLOCKED: {result.envelope.gate.outcome}"
        return subprocess.check_output(command, shell=True).decode()

    register_function(governed_run_bash, caller=assistant, executor=user_proxy,
                      name="run_bash", description="Execute shell command")
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, ".")

from remora.adapters.action_gate import ActionGateResult, AutoGenActionAdapter
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
            action_type=action_type or "function_call",
            target_environment=target_environment or "prod",
        )
        report = self._engine.decide(obs)
        action = report.action.value if hasattr(report.action, "value") else str(report.action)
        h = hashlib.sha256(
            f"{self._prev_hash}:{question[:40]}:{action}".encode()
        ).hexdigest()
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
# Simulated AutoGen registered functions
# ---------------------------------------------------------------------------

@dataclass
class GovernedFunction:
    func_name: str
    agent_name: str
    domain: str
    risk_tier: str
    action_type: str
    calls: list[ActionGateResult] = field(default_factory=list)

    def __post_init__(self):
        self._adapter = AutoGenActionAdapter(
            gateway=DirectPolicyGateway(risk_tier=self.risk_tier)
        )

    def call(self, **kwargs) -> str:
        result = self._adapter.intercept_function_call(
            func_name=self.func_name,
            func_args=kwargs,
            agent_name=self.agent_name,
            domain=self.domain,
            risk_tier=self.risk_tier,
            action_type=self.action_type,
            target_environment="prod",
        )
        self.calls.append(result)
        if result.should_execute:
            return f"[EXECUTED] {self.func_name}({kwargs}) → success"
        return f"[BLOCKED: {result.envelope.gate.outcome}] {self.func_name}"


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SCENARIOS: list[dict[str, Any]] = [
    dict(func_name="read_document",    agent_name="AssistantAgent", domain="documents",
         risk_tier="low",      action_type="read",             kwargs={"path": "/docs/q4.pdf"}),
    dict(func_name="send_slack",       agent_name="NotifierAgent",  domain="comms",
         risk_tier="medium",   action_type="write",            kwargs={"channel": "#ops", "text": "done"}),
    dict(func_name="update_db_record", agent_name="DataAgent",      domain="database",
         risk_tier="high",     action_type="write",            kwargs={"table": "orders", "id": 8821}),
    dict(func_name="run_bash",         agent_name="ExecutorAgent",  domain="code-execution",
         risk_tier="critical", action_type="execute",          kwargs={"command": "rm -rf /tmp/cache"}),
    dict(func_name="deploy_to_prod",   agent_name="DeployAgent",    domain="infrastructure",
         risk_tier="critical", action_type="deploy",           kwargs={"service": "payment-api", "version": "2.1.0"}),
]

_EXPECTED: dict[str, set] = {
    "low":      {"accept"},
    "medium":   {"verify", "accept"},
    "high":     {"verify", "escalate"},
    "critical": {"verify", "escalate", "abstain"},
}


def main() -> int:
    print("=" * 65)
    print("  REMORA × AutoGen — Governance Overlay Demo")
    print("=" * 65)

    funcs = [GovernedFunction(
        func_name=s["func_name"], agent_name=s["agent_name"],
        domain=s["domain"], risk_tier=s["risk_tier"],
        action_type=s["action_type"],
    ) for s in SCENARIOS]

    failed = 0
    for func, scenario in zip(funcs, SCENARIOS):
        output = func.call(**scenario["kwargs"])
        r = func.calls[-1]
        outcome = r.envelope.gate.outcome
        symbol = "✓" if r.should_execute else "○"
        tier = scenario["risk_tier"]
        print(f"\n  {symbol} [{tier.upper():8}] {scenario['func_name']}")
        print(f"    agent  : {scenario['agent_name']}")
        print(f"    outcome: {outcome}")
        print(f"    output : {output[:70]}")
        if outcome not in _EXPECTED[tier]:
            print(f"    FAIL: unexpected '{outcome}' for {tier}")
            failed += 1

    # Structural checks
    print("\n" + "=" * 65)
    for func in funcs:
        env = func.calls[-1].envelope
        assert env.request.request_id
        assert env.audit.hash
        assert env.gate.outcome in ("accept", "verify", "abstain", "escalate")

    accepted = sum(1 for f in funcs if f.calls[-1].should_execute)
    blocked = len(funcs) - accepted
    print(f"  Accepted: {accepted}  |  Blocked/Gated: {blocked}")
    print("  Envelope structure : OK")
    print(f"  AutoGen adapter    : {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
