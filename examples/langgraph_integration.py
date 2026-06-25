#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""REMORA x LangGraph ToolNode demo.

No LangGraph dependency is required for this evaluator demo. The `GovernedToolNode`
below mirrors the important LangGraph pattern: a node receives proposed tool
calls, checks each call with REMORA, and invokes the underlying tool only when
the gate outcome is ACCEPT.
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from remora.adapters.action_gate import ActionGateResult, LangGraphActionAdapter
from remora.adapters.gateway import GatewayResult
from remora.policy import PolicyObservation, RemoraDecisionEngine


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    risk_tier: str
    action_type: str
    target_environment: str
    phase: str
    trust_score: float
    adversarial_detected: bool = False


class DemoGateway:
    def __init__(self) -> None:
        self._engine = RemoraDecisionEngine()

    def assess_sync(
        self,
        question: str,
        *,
        context: str | None = None,
        domain: str | None = None,
        risk_tier: str | None = None,
        action_type: str | None = None,
        target_environment: str | None = None,
        tenant_id: str | None = None,
    ) -> GatewayResult:
        context_data = json.loads(context or "{}")
        phase = context_data.get("phase") or _phase_for(action_type, risk_tier)
        trust_score = context_data.get("trust_score")
        if trust_score is None:
            trust_score = _trust_for(action_type, risk_tier)
        adversarial_detected = bool(
            context_data.get("adversarial_detected")
            or action_type == "destructive_write"
            or "ignore previous" in question.lower()
        )
        obs = PolicyObservation(
            question=question,
            phase=phase,
            trust_score=trust_score,
            risk_tier=risk_tier,
            domain=domain,
            action_type=action_type,
            target_environment=target_environment,
            adversarial_detected=adversarial_detected,
        )
        report = self._engine.decide(obs)
        state_hash = hashlib.sha256(
            json.dumps(
                {
                    "question": question,
                    "domain": domain,
                    "risk_tier": risk_tier,
                    "action_type": action_type,
                    "target_environment": target_environment,
                    "action": report.action.value,
                    "source": report.source_of_decision,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return GatewayResult(
            action=report.action.value,
            human_review_required=report.human_review_required,
            evidence_required=report.evidence_required,
            explanation=report.explanation,
            confidence=report.confidence,
            risk_estimate=report.risk_estimate,
            require_rag=False,
            refuse_parametric_verdict=False,
            source_of_decision=report.source_of_decision,
            state_hash=state_hash,
        )


class GovernedToolNode:
    """Minimal LangGraph-style tool node with REMORA pre-execution gating."""

    def __init__(self, tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]) -> None:
        self.tools = tools
        self.adapter = LangGraphActionAdapter(gateway=DemoGateway())
        self.executed: list[str] = []

    def invoke(self, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for call in tool_calls:
            result: ActionGateResult = self.adapter.intercept(
                action_name=call.name,
                action_args=call.args,
                proposed_by="langgraph-agent",
                domain="agent-workflow",
                risk_tier=call.risk_tier,
                action_type=call.action_type,
                target_environment=call.target_environment,
                context={
                    "phase": call.phase,
                    "trust_score": call.trust_score,
                    "adversarial_detected": call.adversarial_detected,
                },
            )
            if result.should_execute:
                self.executed.append(call.name)
                payload = self.tools[call.name](call.args)
            else:
                payload = {
                    "blocked": result.envelope.gate.outcome,
                    "request_id": result.envelope.request.request_id,
                }
            outputs.append(
                {
                    "tool": call.name,
                    "outcome": result.envelope.gate.outcome,
                    "executed": result.should_execute,
                    "payload": payload,
                }
            )
        return outputs


def search_docs(args: dict[str, Any]) -> dict[str, Any]:
    return {"docs": [f"result for {args['query']}"]}


def send_email(args: dict[str, Any]) -> dict[str, Any]:
    return {"queued": args["to"]}


def delete_table(args: dict[str, Any]) -> dict[str, Any]:
    raise AssertionError("delete_table should have been blocked before dispatch")


def _phase_for(action_type: str | None, risk_tier: str | None) -> str:
    if action_type == "destructive_write" or risk_tier == "critical":
        return "disordered"
    if risk_tier in {"medium", "high"}:
        return "critical"
    return "ordered"


def _trust_for(action_type: str | None, risk_tier: str | None) -> float:
    if action_type == "destructive_write" or risk_tier == "critical":
        return 0.10
    if risk_tier == "medium":
        return 0.62
    if risk_tier == "high":
        return 0.45
    return 0.96


TOOL_CALLS = [
    ToolCall(
        name="search_docs",
        args={"query": "Q2 revenue"},
        risk_tier="low",
        action_type="read",
        target_environment="staging",
        phase="ordered",
        trust_score=0.96,
    ),
    ToolCall(
        name="send_email",
        args={"to": "team@example.com"},
        risk_tier="medium",
        action_type="write",
        target_environment="staging",
        phase="critical",
        trust_score=0.62,
    ),
    ToolCall(
        name="delete_table",
        args={"table": "users"},
        risk_tier="critical",
        action_type="destructive_write",
        target_environment="prod",
        phase="disordered",
        trust_score=0.14,
        adversarial_detected=True,
    ),
]


def run_demo() -> tuple[list[dict[str, Any]], list[str]]:
    node = GovernedToolNode(
        {
            "search_docs": search_docs,
            "send_email": send_email,
            "delete_table": delete_table,
        }
    )
    return node.invoke(TOOL_CALLS), node.executed


def main() -> None:
    outputs, executed = run_demo()
    print("REMORA x LangGraph ToolNode demo")
    print("The ToolNode invokes tools only when REMORA returns ACCEPT.\n")
    for item in outputs:
        status = "EXECUTED" if item["executed"] else "BLOCKED"
        print(f"{item['tool']:<16} -> {item['outcome'].upper():<8} {status}")
    print("\nActual tool invocations:", ", ".join(executed) or "none")


if __name__ == "__main__":
    main()
