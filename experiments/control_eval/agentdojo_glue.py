# SPDX-License-Identifier: BUSL-1.1
"""Plug a SAP v7 defence into an AgentDojo pipeline.

Imports AgentDojo, so it is used only by ``scripts/run_control_eval.py`` with
the pinned packages in ``requirements.txt``; CI tests the defences without it.

``GatedToolsExecutor`` replaces AgentDojo's ``ToolsExecutor``. Before each
proposed call runs, it asks the defence. A blocked call is not executed;
the agent receives ``BLOCKED_MESSAGE`` as the tool result and may continue.
Every decision is appended to ``log`` with the call, so the per-call
analysis (Q3) reads exactly what the run decided.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.tool_execution import ToolsExecutor, tool_result_to_str
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionCall, FunctionsRuntime
from agentdojo.types import (
    ChatAssistantMessage,
    ChatMessage,
    ChatToolResultMessage,
    text_content_block_from_string,
)

from experiments.control_eval.claude_messages import (
    build_request,
    from_response,
    to_messages_api,
    tool_param,
)
from experiments.control_eval.gateway import EpisodeContext, MeteredModel
from experiments.control_eval.policies import Defence, ProposedCall, ToolSpec
from experiments.control_eval.run_config import ModelSpec

BLOCKED_MESSAGE = "Blocked by policy."


def tool_specs(runtime: FunctionsRuntime) -> tuple[ToolSpec, ...]:
    out = []
    for fn in runtime.functions.values():
        required = tuple(fn.parameters.model_json_schema().get("required") or ())
        out.append(ToolSpec(name=fn.name, description=fn.description or "", required=required))
    return tuple(sorted(out, key=lambda t: t.name))


def _text(message: ChatMessage) -> str:
    content = message.get("content") or []
    if isinstance(content, str):
        return content
    return "\n".join(block.get("content", "") for block in content if isinstance(block, dict))


class GatedToolsExecutor(ToolsExecutor):
    """``ToolsExecutor`` that asks a defence before each call."""

    def __init__(self, defence: Defence, *, suite: str, user_task_id: str,
                 injection_task_id: str | None, log: list[dict[str, Any]]) -> None:
        super().__init__(tool_result_to_str)
        self.defence = defence
        self.suite, self.user_task_id, self.injection_task_id = suite, user_task_id, injection_task_id
        self.log = log

    def query(self, query: str, runtime: FunctionsRuntime, env: Env = EmptyEnv(),
              messages: Sequence[ChatMessage] = (), extra_args: dict | None = None,
              ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict]:
        extra_args = dict(extra_args or {})
        if not messages or messages[-1]["role"] != "assistant" or not messages[-1].get("tool_calls"):
            return query, runtime, env, messages, extra_args
        tools = tool_specs(runtime)
        prior = tuple(_text(m) for m in messages if m["role"] == "tool")
        prior_calls = tuple(
            {"name": m["tool_call"].function, "args": dict(m["tool_call"].args), "output": _text(m)}
            for m in messages
            if m["role"] == "tool" and m.get("tool_call") is not None and _text(m) != BLOCKED_MESSAGE
        )
        user_task = next((_text(m) for m in messages if m["role"] == "user"), query)
        results: list[ChatMessage] = []
        for tool_call in messages[-1]["tool_calls"]:
            call = ProposedCall(user_task=user_task, name=tool_call.function,
                                args=dict(tool_call.args), tools=tools, prior_outputs=prior,
                                suite=self.suite, user_task_id=self.user_task_id,
                                injection_task_id=self.injection_task_id,
                                prior_calls=prior_calls, env=env.model_copy(deep=True))
            verdict = self.defence.decide(call)
            self.log.append({"suite": self.suite, "user_task": self.user_task_id,
                             "injection_task": self.injection_task_id, "defence": self.defence.name,
                             "function": call.name, "args": dict(call.args),
                             "execute": verdict.execute, "score": verdict.score,
                             "reason": verdict.reason})
            if not verdict.execute:
                results.append(ChatToolResultMessage(
                    role="tool", content=[text_content_block_from_string(BLOCKED_MESSAGE)],
                    tool_call_id=tool_call.id, tool_call=tool_call, error=None))
                continue
            # Run this one call through the stock executor, in proposal order.
            single = {**messages[-1], "tool_calls": [tool_call]}
            _, runtime, env, executed, extra_args = super().query(
                query, runtime, env, [*messages[:-1], single], extra_args)  # type: ignore[list-item]
            results.extend(executed[len(messages):])
        return query, runtime, env, [*messages, *results], extra_args


class ClaudeAgent(BasePipelineElement):
    """The untrusted agent: one Claude call per turn through the metered gateway.

    Replaces AgentDojo's ``AnthropicLLM`` (see ``claude_messages`` for why).
    Every request goes through :class:`~experiments.control_eval.gateway.MeteredModel`,
    so it is shared across arms when identical (CRN), reserved against the
    budget before it is sent, and settled from usage after.
    """

    def __init__(self, model: MeteredModel, spec: ModelSpec, context: EpisodeContext) -> None:
        self.model, self.spec, self.context = model, spec, context
        self.name = spec.model

    def query(self, query: str, runtime: FunctionsRuntime, env: Env = EmptyEnv(),
              messages: Sequence[ChatMessage] = (), extra_args: dict | None = None,
              ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict]:
        extra_args = dict(extra_args or {})
        system, api_messages = to_messages_api(messages)
        tools = [tool_param(fn.name, fn.description or "", fn.parameters.model_json_schema())
                 for fn in runtime.functions.values()]
        request = build_request(model=self.spec.model, max_tokens=self.spec.max_tokens,
                                effort=self.spec.effort, system=system,
                                messages=api_messages, tools=tools)
        response = self.model.create(request, episode=self.context.episode, arm=self.context.arm)
        content, calls = from_response(response)
        output = ChatAssistantMessage(
            role="assistant", content=content,  # type: ignore[typeddict-item]
            tool_calls=None if calls is None else [
                FunctionCall(id=c["id"], function=c["function"], args=c["args"]) for c in calls])
        return query, runtime, env, [*messages, output], extra_args


def register_model_name(model_id: str) -> None:
    """Let ``important_instructions`` address a current Claude model as "Claude".

    agentdojo 0.1.35's ``MODEL_NAMES`` lists only claude-3.x IDs, and the
    attack raises for a pipeline whose name matches none. Upstream maps every
    Claude ID to "Claude"; this adds the run's model with the same name, so
    the injection text is the one upstream would produce for a Claude model.
    """
    from agentdojo.models import MODEL_NAMES
    MODEL_NAMES.setdefault(model_id, "Claude")
