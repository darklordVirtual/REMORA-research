# SPDX-License-Identifier: BUSL-1.1
"""Model clients under a budget cap (SAP v7 §15.2).

Every model call in Q6 and Q7 goes through :class:`BudgetedClient`. Before a
call it asks the guard whether the worst case could pass the cap; after the
call it records the tokens the provider reported in the response's usage
fields. A response without usage fields stops the run: an uncounted call is
not counted as free.

The worst case is the request's UTF-8 byte length plus a fixed overhead for
input, and ``max_tokens`` for output. A token covers at least one byte in
both providers' tokenizers, so the byte length bounds the text's tokens; the
overhead covers the provider's own framing of tools and messages. The bound
is deliberately loose. Prices are not set here: the owner fixes them on the
sealing date and they are recorded in the manifest (§15.2).

Provider SDK objects are injected. :class:`AnthropicClient` wraps an
``anthropic.Anthropic`` instance and :class:`OpenAICompatibleClient` wraps an
OpenAI-compatible client such as Groq's. Neither imports its SDK, so the
tests drive both with fakes and no network.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from experiments.control_eval.metrics import BudgetExceeded, BudgetGuard

__all__ = [
    "AnthropicClient", "BudgetExceeded", "BudgetGuard", "BudgetedClient", "ModelClient",
    "ModelReply", "ModelRequest", "OpenAICompatibleClient", "Usage", "UsageMissing",
    "anthropic_usage", "openai_usage", "worst_case_input_tokens",
]

#: Input tokens added to every worst case for framing the provider adds
#: around messages, tools and the output schema.
FRAMING_OVERHEAD_TOKENS = 2048


class UsageMissing(BudgetExceeded):
    """The response carried no usable usage fields; the run stops."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelRequest:
    """One provider-neutral request. ``tools`` use the BFCL/JSON-schema shape
    ``{"name", "description", "parameters"}``; each client converts them."""

    model: str
    messages: Sequence[Mapping[str, Any]]
    max_tokens: int
    system: str = ""
    tools: Sequence[Mapping[str, Any]] = ()
    json_schema: Mapping[str, Any] | None = None
    effort: str | None = None
    #: Sampling parameters, sent only where the plan fixes them (Groq models).
    sampling: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelReply:
    text: str
    stop_reason: str
    usage: Usage
    #: ``{"id", "name", "arguments"}``; ``arguments`` is a dict when the
    #: provider returned an object and the raw string otherwise.
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    #: The provider's content blocks as plain dicts, for replaying an
    #: assistant turn unchanged (Anthropic thinking blocks must be sent back).
    raw_content: tuple[Mapping[str, Any], ...] = ()


def _block_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, Mapping):
        return dict(block)
    dump = getattr(block, "model_dump", None)
    if callable(dump):
        return dict(dump(exclude_none=True))
    return dict(vars(block))


class ModelClient(Protocol):
    def send(self, request: ModelRequest) -> ModelReply: ...


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _count(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise UsageMissing(f"usage field {name!r} is {value!r}; refusing to count the call as free")
    return value


def anthropic_usage(response: Any) -> Usage:
    """Tokens billed for one Messages API response, cache reads and writes included as input."""
    usage = _field(response, "usage")
    if usage is None:
        raise UsageMissing("response has no usage object")
    inp = _count(_field(usage, "input_tokens"), "input_tokens")
    for extra in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        value = _field(usage, extra)
        if value is not None:
            inp += _count(value, extra)
    return Usage(inp, _count(_field(usage, "output_tokens"), "output_tokens"))


def openai_usage(response: Any) -> Usage:
    usage = _field(response, "usage")
    if usage is None:
        raise UsageMissing("response has no usage object")
    return Usage(_count(_field(usage, "prompt_tokens"), "prompt_tokens"),
                 _count(_field(usage, "completion_tokens"), "completion_tokens"))


def worst_case_input_tokens(request: ModelRequest) -> int:
    body = json.dumps({"system": request.system, "messages": list(request.messages),
                       "tools": list(request.tools), "schema": request.json_schema},
                      default=str, ensure_ascii=False)
    return len(body.encode("utf-8")) + FRAMING_OVERHEAD_TOKENS


def _json_schema_type(schema: Any) -> Any:
    """BFCL parameter schemas use ``dict``, ``float``, ``tuple`` and ``any``; JSON Schema does not."""
    if isinstance(schema, list):
        return [_json_schema_type(s) for s in schema]
    if not isinstance(schema, Mapping):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            mapped = {"dict": "object", "float": "number", "tuple": "array"}.get(value, value)
            if mapped == "any":
                continue
            out[key] = mapped
        else:
            out[key] = _json_schema_type(value)
    return out


def tool_input_schema(tool: Mapping[str, Any]) -> dict[str, Any]:
    params = _json_schema_type(tool.get("parameters") or {"type": "dict", "properties": {}})
    if not isinstance(params, dict):
        params = {"type": "object", "properties": {}}
    params.setdefault("type", "object")
    params.setdefault("properties", {})
    return params


class AnthropicClient:
    """Messages API through an injected ``anthropic.Anthropic``-like object.

    With ``effort`` set the request uses adaptive thinking and that effort,
    and sets no sampling parameter (SAP v7 §13.4, §14.4, §14.6). No
    server-side fallback model is configured: a refusal returns as
    ``stop_reason == "refusal"`` and the study's own rule handles it.
    """

    def __init__(self, sdk: Any) -> None:
        self._sdk = sdk

    def kwargs(self, request: ModelRequest) -> dict[str, Any]:
        if request.sampling:
            raise ValueError("the plan sends no sampling parameter to Claude models")
        kwargs: dict[str, Any] = {"model": request.model, "max_tokens": request.max_tokens,
                                  "messages": [dict(m) for m in request.messages]}
        if request.system:
            kwargs["system"] = request.system
        if request.tools:
            kwargs["tools"] = [{"name": t["name"], "description": t.get("description", ""),
                                "input_schema": tool_input_schema(t)} for t in request.tools]
        output_config: dict[str, Any] = {}
        if request.effort:
            kwargs["thinking"] = {"type": "adaptive"}
            output_config["effort"] = request.effort
        if request.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": dict(request.json_schema)}
        if output_config:
            kwargs["output_config"] = output_config
        return kwargs

    def send(self, request: ModelRequest) -> ModelReply:
        response = self._sdk.messages.create(**self.kwargs(request))
        usage = anthropic_usage(response)
        texts, calls = [], []
        blocks = list(_field(response, "content") or ())
        for block in blocks:
            kind = _field(block, "type")
            if kind == "text":
                texts.append(_field(block, "text") or "")
            elif kind == "tool_use":
                calls.append({"id": _field(block, "id"), "name": _field(block, "name"),
                              "arguments": _field(block, "input")})
        return ModelReply("".join(texts), str(_field(response, "stop_reason")), usage, tuple(calls),
                          tuple(_block_dict(b) for b in blocks))


class OpenAICompatibleClient:
    """Chat Completions through an injected OpenAI-compatible client (Groq)."""

    def __init__(self, sdk: Any) -> None:
        self._sdk = sdk

    def kwargs(self, request: ModelRequest) -> dict[str, Any]:
        messages = [{"role": "system", "content": request.system}] if request.system else []
        messages += [dict(m) for m in request.messages]
        kwargs: dict[str, Any] = {"model": request.model, "max_tokens": request.max_tokens,
                                  "messages": messages, **dict(request.sampling)}
        if request.tools:
            kwargs["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": tool_input_schema(t)}} for t in request.tools]
        if request.json_schema is not None:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "decision", "schema": dict(request.json_schema)}}
        return kwargs

    def send(self, request: ModelRequest) -> ModelReply:
        response = self._sdk.chat.completions.create(**self.kwargs(request))
        usage = openai_usage(response)
        choice = (_field(response, "choices") or [None])[0]
        message = _field(choice, "message") or {}
        calls = []
        for call in _field(message, "tool_calls") or ():
            fn = _field(call, "function") or {}
            raw = _field(fn, "arguments")
            try:
                args: Any = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                args = raw
            calls.append({"id": _field(call, "id"), "name": _field(fn, "name"), "arguments": args})
        return ModelReply(_field(message, "content") or "", str(_field(choice, "finish_reason")),
                          usage, tuple(calls))


class BudgetedClient:
    """Wraps a :class:`ModelClient`; refuses a call whose worst case could pass the cap."""

    def __init__(self, client: ModelClient, guard: BudgetGuard) -> None:
        self._client = client
        self.guard = guard

    def send(self, request: ModelRequest) -> ModelReply:
        self.guard.check(request.model, worst_case_input_tokens(request), request.max_tokens)
        reply = self._client.send(request)
        self.guard.record(request.model, reply.usage.input_tokens, reply.usage.output_tokens)
        return reply
