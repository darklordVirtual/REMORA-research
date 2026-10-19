# SPDX-License-Identifier: BUSL-1.1
"""Ungated agent trajectories of SAP v7 §14.4.

The agent works through an entry turn by turn with native tool calling and
at most 20 model steps per turn. Every proposed call runs in the injected
environment, which at run time is BFCL's executable API classes at the
pinned commit. Each call is logged with the conversation before it. No call
is constructed, substituted or mutated.

The driver keeps one provider-neutral transcript (OpenAI-style messages)
for the arms, and converts it to each provider's message shape for the
agent. Anthropic assistant turns are replayed from the raw content blocks,
so thinking blocks go back unchanged.

Functions available at a turn are the entry's classes' functions, without
the entry's ``excluded_function`` names and without any ``missed_function``
name before the turn that adds it. An empty user turn is the turn at which
BFCL adds a missed function; the run glue must supply the text BFCL sends
there, and the driver refuses an empty turn without it.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from experiments.routing_baselines.arms import CallContext
from experiments.routing_baselines.split import Entry
from experiments.sap_v7_addenda.budget import (
    BudgetExceeded,
    ModelClient,
    ModelReply,
    ModelRequest,
)

MAX_STEPS_PER_TURN = 20
API_RETRIES = 3
AGENT_MAX_TOKENS = 4096


@dataclass(frozen=True)
class TrajectoryAgent:
    key: str
    model: str
    provider: str


AGENTS = {"K1": TrajectoryAgent("K1", "claude-haiku-5-5", "anthropic"),
          "K2": TrajectoryAgent("K2", "llama-3.3-70b-versatile", "groq")}
#: §14.4: K2 runs on test only if K1's primary wrong set is below this.
WRONG_SET_TARGET = 381


class Environment(Protocol):
    def execute(self, name: str, arguments: Mapping[str, Any]) -> str: ...


def available_docs(entry: Entry, turn: int, catalogue: Mapping[str, Mapping[str, Any]],
                   owner: Mapping[str, str]) -> list[Mapping[str, Any]]:
    withheld = {n for t, names in entry.missed_functions.items() if t > turn for n in names}
    excluded = set(entry.excluded_functions)
    return [catalogue[n] for n in sorted(catalogue)
            if owner.get(n) in entry.involved_classes and n not in excluded and n not in withheld]


def _anthropic_messages(transcript: Sequence[Mapping[str, Any]],
                        raw: Mapping[int, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, m in enumerate(transcript):
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            out.append({"role": "assistant", "content": [dict(b) for b in raw[i]]})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"],
                     "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def _openai_messages(transcript: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in transcript:
        if m["role"] == "assistant":
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": [
                {"id": c["id"], "type": "function", "function": {
                    "name": c["function"]["name"],
                    "arguments": json.dumps(c["function"]["arguments"])}}
                for c in m.get("tool_calls") or ()]})
        else:
            out.append(dict(m))
    return out


def agent_request(agent: TrajectoryAgent, transcript: Sequence[Mapping[str, Any]],
                  raw: Mapping[int, Sequence[Mapping[str, Any]]],
                  docs: Sequence[Mapping[str, Any]]) -> ModelRequest:
    tools = [{"name": d["name"], "description": d.get("description", ""),
              "parameters": d.get("parameters") or {}} for d in docs]
    if agent.provider == "anthropic":
        return ModelRequest(model=agent.model, messages=_anthropic_messages(transcript, raw),
                            max_tokens=AGENT_MAX_TOKENS, tools=tools, effort="low")
    return ModelRequest(model=agent.model, messages=_openai_messages(transcript),
                        max_tokens=AGENT_MAX_TOKENS, tools=tools,
                        sampling={"temperature": 0.0, "top_p": 1.0})


def _send(client: ModelClient, req: ModelRequest) -> tuple[ModelReply | None, str]:
    error = ""
    for _ in range(API_RETRIES + 1):
        try:
            return client.send(req), ""
        except BudgetExceeded:
            raise
        except Exception as exc:  # an agent API error, §14.9
            error = f"{type(exc).__name__}: {exc}"
    return None, error


def run_entry(entry: Entry, agent: TrajectoryAgent, client: ModelClient, env: Environment,
              catalogue: Mapping[str, Mapping[str, Any]], owner: Mapping[str, str],
              empty_turn_text: str | None = None,
              call_id: Callable[[str, int, int, int], str] | None = None) -> dict[str, Any]:
    """One entry; returns the logged calls, the contexts the arms judge and what did not run."""
    transcript: list[dict[str, Any]] = []
    raw: dict[int, Sequence[Mapping[str, Any]]] = {}
    user_turns: list[str] = []
    calls: list[dict[str, Any]] = []
    contexts: list[CallContext] = []
    step_limit_turns: list[int] = []
    make_id = call_id or (lambda e, t, s, k: f"{e}:t{t}:s{s}:c{k}")
    for turn, messages in enumerate(entry.turns):
        text = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
        if not text:
            if empty_turn_text is None:
                raise ValueError(f"{entry.entry_id} turn {turn} is empty and no BFCL text was given")
            text = empty_turn_text
        user_turns.append(text)
        transcript.append({"role": "user", "content": text})
        docs = available_docs(entry, turn, catalogue, owner)
        for step in range(MAX_STEPS_PER_TURN):
            reply, error = _send(client, agent_request(agent, transcript, raw, docs))
            if reply is None:
                return {"entry_id": entry.entry_id, "calls": calls, "contexts": contexts,
                        "stopped_at_turn": turn, "api_error": error,
                        "turns_not_run": list(range(turn, len(entry.turns))),
                        "step_limit_turns": step_limit_turns}
            if not reply.tool_calls:
                transcript.append({"role": "assistant", "content": reply.text, "tool_calls": []})
                raw[len(transcript) - 1] = reply.raw_content or (
                    {"type": "text", "text": reply.text},)
                break
            assistant_index = len(transcript)
            transcript.append({"role": "assistant", "content": reply.text, "tool_calls": []})
            raw[assistant_index] = reply.raw_content
            for k, tc in enumerate(reply.tool_calls):
                cid = make_id(entry.entry_id, turn, step, k)
                ctx = CallContext(call_id=cid, entry_id=entry.entry_id, turn=turn,
                                  tool_name=str(tc.get("name")), arguments=tc.get("arguments"),
                                  user_turns=tuple(user_turns), transcript=tuple(
                                      json.loads(json.dumps(transcript, default=str))),
                                  function_docs=tuple(docs), entry_classes=entry.involved_classes)
                contexts.append(ctx)
                args = tc.get("arguments") if isinstance(tc.get("arguments"), Mapping) else None
                output = (env.execute(ctx.tool_name, args) if args is not None
                          else "Error: arguments are not an object")
                transcript[assistant_index]["tool_calls"].append(
                    {"id": tc.get("id") or cid, "type": "function",
                     "function": {"name": ctx.tool_name, "arguments": args or {}}})
                transcript.append({"role": "tool", "tool_call_id": tc.get("id") or cid,
                                   "content": output})
                calls.append({"call_id": cid, "entry_id": entry.entry_id, "turn": turn,
                              "step": step, "tool_name": ctx.tool_name,
                              "arguments": tc.get("arguments"), "output": output,
                              "available": [d["name"] for d in docs]})
        else:
            step_limit_turns.append(turn)  # §14.9: kept up to the limit
    return {"entry_id": entry.entry_id, "calls": calls, "contexts": contexts,
            "stopped_at_turn": None, "api_error": "", "turns_not_run": [],
            "step_limit_turns": step_limit_turns}
