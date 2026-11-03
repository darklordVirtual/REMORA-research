# SPDX-License-Identifier: BUSL-1.1
"""AgentDojo chat messages to and from Messages API requests, as plain dicts.

Why not AgentDojo's own ``AnthropicLLM`` (agentdojo 0.1.35): it sends
``temperature=0.0`` by default and ``thinking={"type": "enabled",
"budget_tokens": N}`` when thinking is on, and the current Claude models
(claude-sonnet-5-5, claude-haiku-5-5) reject both with a 400. It also drops
the response's ``usage``, so no budget guard can settle a call, sets no
``cache_control``, and maps unknown content block types to ``None``. This
module keeps AgentDojo's message shapes (the same system prompt, tool
schemas from ``Function.parameters.model_json_schema()``, tool results as
``tool_result`` blocks merged into one user turn, tool calls only when
``stop_reason == "tool_use"``, the same tool-name filter) and changes only
what the current API requires.

Nothing here imports AgentDojo: messages are the TypedDicts AgentDojo uses
(plain dicts), and a tool call is any object with ``id``, ``function`` and
``args``. ``agentdojo_glue.ClaudeAgent`` wraps it as a pipeline element.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

VALID_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _blocks_text(blocks: Any) -> str:
    if isinstance(blocks, str):
        return blocks
    return "\n".join(b.get("content") or "" for b in blocks or () if isinstance(b, Mapping))


def _content_block(block: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = block.get("type")
    if kind == "text":
        text = block.get("content") or ""
        return {"type": "text", "text": text} if text else None
    if kind == "thinking":
        if block.get("id") is None:
            return {"type": "redacted_thinking", "data": block.get("content") or ""}
        return {"type": "thinking", "thinking": block.get("content") or "",
                "signature": block["id"]}
    if kind == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.get("content") or ""}
    raise ValueError(f"unsupported content block type {kind!r}")


def _tool_use(call: Any) -> dict[str, Any]:
    if getattr(call, "id", None) is None:
        raise ValueError("a tool call needs an id for the Messages API")
    return {"type": "tool_use", "id": call.id, "name": call.function, "input": dict(call.args)}


def to_messages_api(messages: Sequence[Mapping[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    """(system prompt, messages) for a Messages API request."""
    if not messages:
        raise ValueError("at least one message is required")
    system = None
    rest = list(messages)
    if rest[0]["role"] == "system":
        system = _blocks_text(rest[0]["content"])
        rest = rest[1:]
    out: list[dict[str, Any]] = []
    for m in rest:
        role = m["role"]
        if role == "user":
            content = [b for b in (_content_block(x) for x in m["content"]) if b]
            item = {"role": "user", "content": content}
        elif role == "tool":
            if m.get("tool_call_id") is None:
                raise ValueError("a tool result needs tool_call_id")
            error = m.get("error")
            text = error if error is not None else _blocks_text(m.get("content"))
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": m["tool_call_id"],
                                      "content": [{"type": "text", "text": text}] if text else [],
                                      "is_error": error is not None}
            item = {"role": "user", "content": [result]}
        elif role == "assistant":
            content = [b for b in (_content_block(x) for x in m.get("content") or ()) if b]
            content += [_tool_use(c) for c in m.get("tool_calls") or ()]
            item = {"role": "assistant", "content": content}
        else:
            raise ValueError(f"unsupported role {role!r}")
        if out and out[-1]["role"] == item["role"] == "user":
            out[-1]["content"] = [*out[-1]["content"], *item["content"]]
        else:
            out.append(item)
    return system, out


def tool_param(name: str, description: str, input_schema: Mapping[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "input_schema": dict(input_schema)}


def build_request(*, model: str, max_tokens: int, effort: str | None, system: str | None,
                  messages: list[dict[str, Any]], tools: Iterable[Mapping[str, Any]],
                  cache: bool = True) -> dict[str, Any]:
    """A Messages API request with no sampling parameter and no thinking budget.

    Thinking is left at the model's default (adaptive on the current models);
    ``effort`` goes in ``output_config``. ``cache_control`` at top level
    caches the longest stable prefix (tools, system, earlier turns).
    """
    request: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        request["system"] = system
    tools = [dict(t) for t in tools]
    if tools:
        request["tools"] = tools
    if effort:
        request["output_config"] = {"effort": effort}
    if cache:
        request["cache_control"] = {"type": "ephemeral"}
    return request


def from_response(response: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """(AgentDojo content blocks, tool calls or None) from a response dict.

    Tool calls are taken only when ``stop_reason == "tool_use"``, as
    AgentDojo does; calls with names outside its pattern are dropped.
    """
    content: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    for b in response.get("content") or ():
        kind = b.get("type")
        if kind == "text":
            content.append({"type": "text", "content": b.get("text", "")})
        elif kind == "thinking":
            content.append({"type": "thinking", "content": b.get("thinking", ""),
                            "id": b.get("signature")})
        elif kind == "redacted_thinking":
            content.append({"type": "redacted_thinking", "content": b.get("data", "")})
        elif kind == "tool_use":
            calls.append({"id": b["id"], "function": b["name"], "args": dict(b.get("input") or {})})
    if response.get("stop_reason") != "tool_use":
        return content, None
    return content, [c for c in calls if VALID_TOOL_NAME.match(c["function"])]
