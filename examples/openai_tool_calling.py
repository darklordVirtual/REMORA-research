#!/usr/bin/env python3
# Author: Stian Skogbrott  |  License: Apache-2.0
"""REMORA x OpenAI tool-calling demo.

This is a no-key, runnable reproduction of the OpenAI tool-call control flow:

1. The model proposes tool calls.
2. REMORA gates each proposed call before execution.
3. The local tool dispatcher is invoked only for ACCEPT decisions.
4. Blocked calls return a structured governance result instead of executing.

The simulated tool-call objects use the same shape as OpenAI tool calls after
parsing `function.arguments` JSON.
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from remora.adapters.action_gate import ActionGateResult, OpenAIToolCallingAdapter
from remora.adapters.gateway import GatewayResult
from remora.policy import PolicyObservation, RemoraDecisionEngine


@dataclass(frozen=True)
class ProposedToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    risk_tier: str
    action_type: str
    target_environment: str
    phase: str
    trust_score: float
    adversarial_detected: bool = False


class DemoGateway:
    """Small gateway that exposes the adapter protocol used in production."""

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
        action = report.action.value
        state_hash = hashlib.sha256(
            json.dumps(
                {
                    "question": question,
                    "domain": domain,
                    "risk_tier": risk_tier,
                    "action_type": action_type,
                    "target_environment": target_environment,
                    "action": action,
                    "source": report.source_of_decision,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return GatewayResult(
            action=action,
            human_review_required=report.human_review_required,
            evidence_required=report.evidence_required,
            explanation=report.explanation,
            confidence=report.confidence,
            risk_estimate=report.risk_estimate,
            require_rag=False,
            refuse_parametric_verdict=False,
            source_of_decision=report.source_of_decision,
            state_hash=state_hash,
            fallback_used=False,
        )


class ToolDispatcher:
    """Local tool registry used to prove blocked calls are not invoked."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "search_knowledge_base": self._search_knowledge_base,
            "create_support_ticket": self._create_support_ticket,
            "delete_account": self._delete_account,
        }

    def dispatch(self, call: ProposedToolCall) -> dict[str, Any]:
        self.executed.append(call.name)
        return self.tools[call.name](call.arguments)

    def _search_knowledge_base(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"result": f"found policy article for {args['query']}"}

    def _create_support_ticket(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ticket_id": "SUP-1001", "subject": args["subject"]}

    def _delete_account(self, args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("delete_account should have been blocked before dispatch")


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
        return 0.64
    if risk_tier == "high":
        return 0.45
    return 0.96


TOOL_CALLS = [
    ProposedToolCall(
        id="call_001",
        name="search_knowledge_base",
        arguments={"query": "cancellation policy"},
        risk_tier="low",
        action_type="read",
        target_environment="staging",
        phase="ordered",
        trust_score=0.96,
    ),
    ProposedToolCall(
        id="call_002",
        name="create_support_ticket",
        arguments={"subject": "Billing issue"},
        risk_tier="medium",
        action_type="write",
        target_environment="staging",
        phase="critical",
        trust_score=0.64,
    ),
    ProposedToolCall(
        id="call_003",
        name="delete_account",
        arguments={"user_id": "u-882", "hard_delete": True},
        risk_tier="critical",
        action_type="destructive_write",
        target_environment="prod",
        phase="disordered",
        trust_score=0.10,
        adversarial_detected=True,
    ),
]


def govern_and_dispatch() -> tuple[list[dict[str, Any]], list[str]]:
    adapter = OpenAIToolCallingAdapter(gateway=DemoGateway())
    dispatcher = ToolDispatcher()
    outputs: list[dict[str, Any]] = []

    for call in TOOL_CALLS:
        tool_call = {"name": call.name, "arguments": call.arguments}
        result: ActionGateResult = adapter.intercept_tool_call(
            tool_call=tool_call,
            proposed_by="simulated-openai-response",
            domain="customer-support",
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
            tool_output = dispatcher.dispatch(call)
        else:
            tool_output = {
                "blocked": result.envelope.gate.outcome,
                "review_required": True,
                "request_id": result.envelope.request.request_id,
            }
        outputs.append(
            {
                "id": call.id,
                "tool": call.name,
                "outcome": result.envelope.gate.outcome,
                "executed": result.should_execute,
                "output": tool_output,
            }
        )

    return outputs, dispatcher.executed


def run_demo() -> dict[str, Any]:
    outputs, executed = govern_and_dispatch()
    return {"outputs": outputs, "executed": executed}


def main() -> None:
    result = run_demo()
    outputs = result["outputs"]
    executed = result["executed"]
    print("REMORA x OpenAI tool-calling demo")
    print("Tool calls are dispatched only when REMORA returns ACCEPT.\n")
    for item in outputs:
        status = "EXECUTED" if item["executed"] else "BLOCKED"
        print(f"{item['id']} {item['tool']:<24} -> {item['outcome'].upper():<8} {status}")
    print("\nActual dispatcher invocations:", ", ".join(executed) or "none")


if __name__ == "__main__":
    main()
