# Author: Stian Skogbrott
# License: Apache-2.0
"""Reference action-gate adapters for agent frameworks.

These wrappers keep REMORA as a governance overlay in front of tool execution.
They return a DecisionEnvelope and expose replay-log hooks for benchmark mode.

Supported adapters
------------------
- ``LangGraphActionAdapter``    — LangGraph ToolNode interception
- ``OpenAIToolCallingAdapter``  — OpenAI function-calling interception
- ``CrewAIActionAdapter``       — CrewAI tool/task interception
- ``AutoGenActionAdapter``      — AutoGen tool-call interception
- ``AsyncActionGate``           — async-first base for any framework

All sync adapters are thin wrappers over ``_BaseActionGate``.
All async adapters are thin wrappers over ``_AsyncActionGate``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from remora.adapters.gateway import GatewayResult, RemoraGateway
from remora.governance.envelope import (
    AssessmentBlock,
    AuditBlock,
    DecisionEnvelope,
    GateBlock,
    RequestBlock,
)
from remora.policy.observation import canonical_tool_call_hash


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class RemoraActionGate(Protocol):
    def assess_action(
        self,
        action_name: str,
        action_args: dict,
        proposed_by: str,
        domain: str,
        risk_tier: str,
        action_type: str,
        target_environment: str,
        context: dict,
    ) -> DecisionEnvelope:
        ...


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ActionGateResult:
    """Outcome of a single action-gate assessment."""

    envelope: DecisionEnvelope
    should_execute: bool
    """True only when the gate outcome is ACCEPT."""


# ---------------------------------------------------------------------------
# Shared envelope builder
# ---------------------------------------------------------------------------

def _build_envelope(
    gateway: Any,
    action_name: str,
    action_args: dict,
    proposed_by: str,
    domain: str,
    risk_tier: str,
    action_type: str,
    target_environment: str,
    context: dict,
    result: GatewayResult,
    policy_version: str,
) -> DecisionEnvelope:
    # The request identity binds the FULL governance context, not just the
    # action payload: the same tool call assessed in staging vs production, or
    # under a different risk classification, is a different governance event
    # and must not collide on one request_id.
    identity_payload = {
        "action_name": action_name,
        "action_args": action_args,
        "proposed_by": proposed_by,
        "context": context,
        "domain": domain,
        "risk_tier": risk_tier,
        "action_type": action_type,
        "target_environment": target_environment,
    }
    question = f"Assess action execution safety: {json.dumps(identity_payload, sort_keys=True)}"
    request_id = hashlib.sha256(question.encode()).hexdigest()[:16]
    tenant = str(context.get("tenant_id") or "") if isinstance(context, dict) else ""
    return DecisionEnvelope(
        request=RequestBlock(
            request_id=request_id,
            domain=domain,
            risk_tier=risk_tier,
            proposed_action=action_name,
            action_type=action_type,
            target_environment=target_environment,
        ),
        assessment=AssessmentBlock(
            oracle_votes=[],
            thermodynamic={"trust_score": result.confidence},
            evidence_quality={"required": result.evidence_required},
            policy_triggers=[result.explanation],
        ),
        gate=GateBlock(
            outcome=result.action,
            # blocked_action iff execution is not authorized: VERIFY is just as
            # unexecutable as abstain/escalate (should_execute requires accept).
            blocked_action=action_name if result.action != "accept" else None,
            allowed_next_steps=["human_review"] if result.human_review_required else [],
        ),
        audit=AuditBlock(
            policy_version=policy_version,
            hash=result.state_hash,
            previous_hash=None,
            signature=None,
            tenant_id=tenant or None,
            tool_args_hash=canonical_tool_call_hash(
                name=action_name,
                arguments=action_args,
                tenant=tenant,
                target=target_environment,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Sync base
# ---------------------------------------------------------------------------

class _BaseActionGate:
    """Synchronous base for all action-gate adapters."""

    def __init__(
        self,
        gateway: RemoraGateway,
        policy_version: str = "remora-action-gate-v1",
    ) -> None:
        self._gateway = gateway
        self._policy_version = policy_version

    def assess_action(
        self,
        action_name: str,
        action_args: dict,
        proposed_by: str,
        domain: str,
        risk_tier: str,
        action_type: str,
        target_environment: str,
        context: dict,
    ) -> DecisionEnvelope:
        payload = {
            "action_name": action_name,
            "action_args": action_args,
            "proposed_by": proposed_by,
            "context": context,
        }
        question = f"Assess action execution safety: {json.dumps(payload, sort_keys=True)}"
        result = self._gateway.assess_sync(
            question=question,
            context=context.get("prompt") if isinstance(context, dict) else None,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
        )
        return _build_envelope(
            self._gateway,
            action_name, action_args, proposed_by,
            domain, risk_tier, action_type, target_environment,
            context, result, self._policy_version,
        )

    def intercept(
        self,
        action_name: str,
        action_args: dict,
        proposed_by: str,
        domain: str,
        risk_tier: str,
        action_type: str,
        target_environment: str,
        context: dict,
    ) -> ActionGateResult:
        env = self.assess_action(
            action_name=action_name,
            action_args=action_args,
            proposed_by=proposed_by,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
            context=context,
        )
        return ActionGateResult(envelope=env, should_execute=env.gate.outcome == "accept")

    def to_shadow_replay_record(
        self, envelope: DecisionEnvelope, *, unsafe: bool = False
    ) -> dict[str, Any]:
        d = envelope.to_dict()
        return {
            "question": d["request"]["proposed_action"],
            "domain": d["request"]["domain"],
            "risk_tier": d["request"]["risk_tier"],
            "action_type": d["request"]["action_type"],
            "target_environment": d["request"]["target_environment"],
            "evidence_action": (
                "verify" if d["assessment"]["evidence_quality"].get("required") else "answer"
            ),
            "evidence_confidence": d["assessment"]["thermodynamic"].get("trust_score"),
            "unsafe": unsafe,
        }


# ---------------------------------------------------------------------------
# Async base
# ---------------------------------------------------------------------------

class _AsyncActionGate:
    """Async-first base for all action-gate adapters.

    Implements ``async assess_action()`` and ``async intercept()``.
    Falls back to a thread-pool if the underlying gateway only exposes
    a synchronous ``assess_sync()`` method.
    """

    def __init__(
        self,
        gateway: RemoraGateway,
        policy_version: str = "remora-action-gate-v1",
    ) -> None:
        self._gateway = gateway
        self._policy_version = policy_version

    async def _call_gateway(
        self,
        question: str,
        *,
        context: str | None,
        domain: str,
        risk_tier: str,
        action_type: str,
        target_environment: str,
    ) -> GatewayResult:
        """Dispatch to async or sync gateway, transparently."""
        if hasattr(self._gateway, "assess"):
            # Native async gateway
            return await self._gateway.assess(  # type: ignore[attr-defined]
                question=question,
                context=context,
                domain=domain,
                risk_tier=risk_tier,
                action_type=action_type,
                target_environment=target_environment,
            )
        # Sync gateway — run in thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._gateway.assess_sync(
                question,
                context=context,
                domain=domain,
                risk_tier=risk_tier,
                action_type=action_type,
                target_environment=target_environment,
            ),
        )

    async def assess_action(
        self,
        action_name: str,
        action_args: dict,
        proposed_by: str,
        domain: str,
        risk_tier: str,
        action_type: str,
        target_environment: str,
        context: dict,
    ) -> DecisionEnvelope:
        payload = {
            "action_name": action_name,
            "action_args": action_args,
            "proposed_by": proposed_by,
            "context": context,
        }
        question = f"Assess action execution safety: {json.dumps(payload, sort_keys=True)}"
        result = await self._call_gateway(
            question=question,
            context=context.get("prompt") if isinstance(context, dict) else None,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
        )
        return _build_envelope(
            self._gateway,
            action_name, action_args, proposed_by,
            domain, risk_tier, action_type, target_environment,
            context, result, self._policy_version,
        )

    async def intercept(
        self,
        action_name: str,
        action_args: dict,
        proposed_by: str,
        domain: str,
        risk_tier: str,
        action_type: str,
        target_environment: str,
        context: dict,
    ) -> ActionGateResult:
        env = await self.assess_action(
            action_name=action_name,
            action_args=action_args,
            proposed_by=proposed_by,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
            context=context,
        )
        return ActionGateResult(envelope=env, should_execute=env.gate.outcome == "accept")

    def to_shadow_replay_record(
        self, envelope: DecisionEnvelope, *, unsafe: bool = False
    ) -> dict[str, Any]:
        d = envelope.to_dict()
        return {
            "question": d["request"]["proposed_action"],
            "domain": d["request"]["domain"],
            "risk_tier": d["request"]["risk_tier"],
            "action_type": d["request"]["action_type"],
            "target_environment": d["request"]["target_environment"],
            "evidence_action": (
                "verify" if d["assessment"]["evidence_quality"].get("required") else "answer"
            ),
            "evidence_confidence": d["assessment"]["thermodynamic"].get("trust_score"),
            "unsafe": unsafe,
        }


# ---------------------------------------------------------------------------
# AsyncLocalGateway — async wrapper over a synchronous RemoraGateway (e.g. LocalGateway)
# ---------------------------------------------------------------------------

class AsyncLocalGateway:
    """Async-native gateway wrapping a synchronous ``RemoraGateway``.

    Wraps any synchronous gateway so it can be awaited.  Suitable for
    use with ``asyncio``, ``trio``, or any framework that runs an event loop.

    Example
    -------
    ::

        from remora.adapters.action_gate import AsyncLocalGateway, AsyncActionGate
        from remora.adapters.gateway import LocalGateway

        # Wrap a sync gateway
        async_gw = AsyncLocalGateway(sync_gateway=LocalGateway(engine))
        adapter = AsyncActionGate(gateway=async_gw)
        result = await adapter.intercept(
            action_name="send_email",
            action_args={"to": "ceo@example.com", "body": "..."},
            proposed_by="email-agent",
            domain="comms", risk_tier="high",
            action_type="write", target_environment="prod",
            context={},
        )
        if not result.should_execute:
            raise PermissionError(f"REMORA blocked: {result.envelope.gate.outcome}")
    """

    def __init__(self, sync_gateway: RemoraGateway) -> None:
        self._sync = sync_gateway

    async def assess(
        self,
        question: str,
        *,
        context: str | None = None,
        domain: str | None = None,
        risk_tier: str | None = None,
        action_type: str | None = None,
        target_environment: str | None = None,
    ) -> GatewayResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._sync.assess_sync(
                question,
                context=context,
                domain=domain,
                risk_tier=risk_tier,
                action_type=action_type,
                target_environment=target_environment,
            ),
        )

    # Mirror the sync interface for duck-typing compatibility
    def assess_sync(
        self,
        question: str,
        *,
        context: str | None = None,
        domain: str | None = None,
        risk_tier: str | None = None,
        action_type: str | None = None,
        target_environment: str | None = None,
    ) -> GatewayResult:
        return self._sync.assess_sync(
            question,
            context=context,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
        )


# ---------------------------------------------------------------------------
# Concrete sync adapters
# ---------------------------------------------------------------------------

class LangGraphActionAdapter(_BaseActionGate):
    """Reference governance wrapper for LangGraph ``ToolNode`` interception.

    Usage
    -----
    ::

        adapter = LangGraphActionAdapter(gateway=LocalGateway(engine))

        for call in state["messages"][-1].tool_calls:
            result = adapter.intercept(
                action_name=call["name"],
                action_args=call["args"],
                proposed_by="planner-agent",
                domain="infrastructure", risk_tier="high",
                action_type="write", target_environment="prod",
                context={},
            )
            if not result.should_execute:
                state["blocked"].append(result.envelope)
            else:
                tool_node.invoke(call)
    """


class OpenAIToolCallingAdapter(_BaseActionGate):
    """Reference governance wrapper for OpenAI function-calling.

    Usage
    -----
    ::

        adapter = OpenAIToolCallingAdapter(gateway=LocalGateway(engine))

        for call in response.choices[0].message.tool_calls:
            result = adapter.intercept_tool_call(
                tool_call={"name": call.function.name,
                           "arguments": json.loads(call.function.arguments)},
                proposed_by="openai-agent",
                domain="customer-data", risk_tier="critical",
                action_type="destructive_write", target_environment="prod",
                context={},
            )
    """

    def intercept_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        proposed_by: str,
        domain: str,
        risk_tier: str,
        action_type: str,
        target_environment: str,
        context: dict[str, Any],
    ) -> ActionGateResult:
        return self.intercept(
            action_name=tool_call.get("name", "unknown_tool"),
            action_args=tool_call.get("arguments", {}),
            proposed_by=proposed_by,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
            context=context,
        )


class CrewAIActionAdapter(_BaseActionGate):
    """Reference governance wrapper for CrewAI tool/task execution.

    Wrap any CrewAI ``BaseTool`` call before execution to gate it through
    REMORA.  The adapter is framework-decoupled — it does not import CrewAI
    directly, so REMORA stays installable in environments without it.

    Usage
    -----
    ::

        from remora.adapters.action_gate import CrewAIActionAdapter
        from remora.adapters.gateway import LocalGateway

        adapter = CrewAIActionAdapter(gateway=LocalGateway(engine))

        class GovernedWebSearch(BaseTool):
            name = "web_search"
            description = "Search the web"

            def _run(self, query: str) -> str:
                result = adapter.intercept(
                    action_name="web_search",
                    action_args={"query": query},
                    proposed_by="research-crew",
                    domain="web", risk_tier="medium",
                    action_type="read", target_environment="prod",
                    context={},
                )
                if not result.should_execute:
                    return f"[REMORA BLOCKED: {result.envelope.gate.outcome}]"
                return actual_search(query)
    """

    def intercept_tool(
        self,
        tool_name: str,
        tool_input: str | dict[str, Any],
        *,
        agent_role: str = "crew-agent",
        domain: str = "default",
        risk_tier: str = "medium",
        action_type: str = "tool_call",
        target_environment: str = "prod",
        context: dict[str, Any] | None = None,
    ) -> ActionGateResult:
        """Gate a CrewAI tool call.

        Parameters
        ----------
        tool_name:
            The tool's ``name`` attribute.
        tool_input:
            Raw tool input — string or dict.
        agent_role:
            The ``role`` of the CrewAI agent invoking the tool.
        """
        if isinstance(tool_input, str):
            tool_args: dict[str, Any] = {"input": tool_input}
        else:
            tool_args = dict(tool_input)

        return self.intercept(
            action_name=tool_name,
            action_args=tool_args,
            proposed_by=agent_role,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
            context=context or {},
        )


class AutoGenActionAdapter(_BaseActionGate):
    """Reference governance wrapper for AutoGen tool/function calls.

    AutoGen agents invoke tools via ``register_function`` / ``initiate_chat``
    patterns.  This adapter intercepts the resolved function call before
    execution.

    Usage
    -----
    ::

        from remora.adapters.action_gate import AutoGenActionAdapter

        adapter = AutoGenActionAdapter(gateway=LocalGateway(engine))

        def governed_execute_code(code: str, lang: str) -> str:
            result = adapter.intercept_function_call(
                func_name="execute_code",
                func_args={"code": code, "lang": lang},
                agent_name="CodeAssistant",
                domain="code-execution", risk_tier="critical",
                action_type="execute", target_environment="sandbox",
            )
            if not result.should_execute:
                return f"BLOCKED by REMORA: {result.envelope.gate.outcome}"
            return _real_execute_code(code, lang)
    """

    def intercept_function_call(
        self,
        func_name: str,
        func_args: dict[str, Any],
        *,
        agent_name: str = "autogen-agent",
        domain: str = "default",
        risk_tier: str = "medium",
        action_type: str = "function_call",
        target_environment: str = "prod",
        context: dict[str, Any] | None = None,
    ) -> ActionGateResult:
        """Gate an AutoGen function call.

        Parameters
        ----------
        func_name:
            Name of the registered function.
        func_args:
            Arguments dict passed by the LLM.
        agent_name:
            Originating agent's name or role.
        """
        return self.intercept(
            action_name=func_name,
            action_args=func_args,
            proposed_by=agent_name,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
            context=context or {},
        )


# ---------------------------------------------------------------------------
# Async concrete adapter
# ---------------------------------------------------------------------------

class AsyncActionGate(_AsyncActionGate):
    """Framework-agnostic async action gate.

    Use when your agent framework is async-first (FastAPI endpoint, async
    LangGraph pipeline, async AutoGen, etc.).

    Example
    -------
    ::

        import asyncio
        from remora.adapters.action_gate import AsyncActionGate, AsyncLocalGateway

        async def main():
            gw = AsyncLocalGateway(sync_gateway=LocalGateway(engine))
            gate = AsyncActionGate(gateway=gw)
            result = await gate.intercept(
                action_name="delete_record",
                action_args={"id": "u-123"},
                proposed_by="cleanup-agent",
                domain="data", risk_tier="critical",
                action_type="destructive_write",
                target_environment="prod",
                context={},
            )
            assert not result.should_execute  # critical tier → VERIFY/ESCALATE

        asyncio.run(main())
    """
