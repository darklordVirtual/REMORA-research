# SPDX-License-Identifier: BUSL-1.1
"""Tool registry of SAP v7 §12.2, fixed before any agent output exists.

Two labellers see only tool documents: never an attack, task or answer file.

* L1 is deterministic. ``write`` when the lower-cased tool name contains a
  ``_MUTATING`` token of ``remora/toolcall/routing/evaluate.py`` (substring,
  as that module tests it), else ``read``; ``high`` for write, ``low`` for
  read.
* L2 is one LLM call per toolkit or API class, with the frozen prompt
  ``experiments/injection_eval/prompts/registry_labeller_v1.txt``. Its reply
  must label every tool of the toolkit exactly once.

The combination is ``write`` if either says ``write`` and the higher of the
two tiers. There is no hand edit. Generating a registry spends L2's model
calls and is §15.5 item 3; nothing in this module runs it on its own.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiments.sap_v7_addenda.budget import ModelClient, ModelRequest

ACTION_TYPES = ("read", "write")
RISK_TIERS = ("low", "medium", "high", "critical")
L2_MODEL = "claude-sonnet-5-5"
L2_EFFORT = "low"
L2_MAX_TOKENS = 8192
LABELLER_PROMPT = (Path(__file__).resolve().parents[1] / "injection_eval" / "prompts"
                   / "registry_labeller_v1.txt")


class L2Invalid(ValueError):
    """L2's reply does not label the toolkit's tools as the schema requires."""


@dataclass(frozen=True)
class ToolDoc:
    """What a labeller may see about one tool: its documents and nothing else."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    toolkit: str
    domain: str


@dataclass(frozen=True)
class Label:
    action_type: str
    risk_tier: str


def mutating_tokens() -> tuple[str, ...]:
    from remora.toolcall.routing.evaluate import _MUTATING
    return tuple(_MUTATING)


def l1_label(tool_name: str, tokens: Sequence[str] | None = None) -> Label:
    name = tool_name.lower()
    write = any(t in name for t in (tokens if tokens is not None else mutating_tokens()))
    return Label("write", "high") if write else Label("read", "low")


def l2_schema(names: Sequence[str]) -> dict[str, Any]:
    """Structured-output schema for one toolkit's labels."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["tools"],
        "properties": {"tools": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "action_type", "risk_tier"],
            "properties": {
                "name": {"type": "string", "enum": sorted(names)},
                "action_type": {"type": "string", "enum": list(ACTION_TYPES)},
                "risk_tier": {"type": "string", "enum": list(RISK_TIERS)},
            }}}},
    }


def render_l2_prompt(template: str, toolkit: str, tools: Sequence[ToolDoc]) -> str:
    docs = [{"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in sorted(tools, key=lambda t: t.name)]
    return template.replace("{toolkit}", toolkit).replace(
        "{tool_documents}", json.dumps(docs, indent=2, sort_keys=True, ensure_ascii=False))


def parse_l2(text: str, names: Iterable[str]) -> dict[str, Label]:
    expected = set(names)
    try:
        body = json.loads(text)
    except ValueError as exc:
        raise L2Invalid(f"reply is not JSON: {exc}") from exc
    rows = body.get("tools") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise L2Invalid("reply has no 'tools' list")
    out: dict[str, Label] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise L2Invalid(f"row {row!r} is not an object")
        name, action, tier = row.get("name"), row.get("action_type"), row.get("risk_tier")
        if name not in expected:
            raise L2Invalid(f"unknown tool {name!r}")
        if name in out:
            raise L2Invalid(f"tool {name!r} labelled twice")
        if action not in ACTION_TYPES or tier not in RISK_TIERS:
            raise L2Invalid(f"tool {name!r}: invalid label {action!r}/{tier!r}")
        out[name] = Label(action, tier)
    if set(out) != expected:
        raise L2Invalid(f"unlabelled tools: {sorted(expected - set(out))}")
    return out


def l2_label_toolkit(client: ModelClient, template: str, toolkit: str,
                     tools: Sequence[ToolDoc], model: str = L2_MODEL) -> dict[str, Label]:
    """One L2 call for *toolkit*; one retry on a refusal or an invalid reply, then raise."""
    names = [t.name for t in tools]
    request = ModelRequest(model=model, max_tokens=L2_MAX_TOKENS, effort=L2_EFFORT,
                           messages=[{"role": "user",
                                      "content": render_l2_prompt(template, toolkit, tools)}],
                           json_schema=l2_schema(names))
    last: Exception | None = None
    for _ in range(2):
        reply = client.send(request)
        if reply.stop_reason == "refusal":
            last = L2Invalid(f"{toolkit}: labeller refused")
            continue
        try:
            return parse_l2(reply.text, names)
        except L2Invalid as exc:
            last = exc
    raise L2Invalid(f"{toolkit}: no valid labels after one retry ({last})")


def combine(l1: Label, l2: Label) -> Label:
    action = "write" if "write" in (l1.action_type, l2.action_type) else "read"
    tier = max(l1.risk_tier, l2.risk_tier, key=RISK_TIERS.index)
    return Label(action, tier)


def build_registry(tools: Sequence[ToolDoc], l2: Mapping[str, Label],
                   tokens: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
    """Per tool: L1, L2 and the combined label, and the domain from the tool documents."""
    names = [t.name for t in tools]
    if len(set(names)) != len(names):
        raise ValueError("duplicate tool names")
    missing = sorted(set(names) - set(l2))
    if missing:
        raise ValueError(f"L2 labels missing for {missing}")
    out = {}
    for t in sorted(tools, key=lambda t: t.name):
        a, b = l1_label(t.name, tokens), l2[t.name]
        c = combine(a, b)
        out[t.name] = {"domain": t.domain, "toolkit": t.toolkit,
                       "l1": {"action_type": a.action_type, "risk_tier": a.risk_tier},
                       "l2": {"action_type": b.action_type, "risk_tier": b.risk_tier},
                       "action_type": c.action_type, "risk_tier": c.risk_tier}
    return out


def variant(registry: Mapping[str, Mapping[str, Any]], which: str) -> dict[str, Label]:
    """The combined, L1-only or L2-only labels (arms R, R-L1 and R-L2 of §13.5)."""
    if which == "combined":
        return {n: Label(e["action_type"], e["risk_tier"]) for n, e in registry.items()}
    if which not in ("l1", "l2"):
        raise ValueError(f"unknown registry variant {which!r}")
    return {n: Label(e[which]["action_type"], e[which]["risk_tier"]) for n, e in registry.items()}


def metadata_document(registry: Mapping[str, Mapping[str, Any]], which: str = "combined"
                      ) -> dict[str, Any]:
    """The ``REMORA_TOOL_METADATA_FILE`` document for one registry variant."""
    labels = variant(registry, which)
    return {"version": 1, "tools": {
        name: {"risk_tier": labels[name].risk_tier, "action_type": labels[name].action_type,
               "domain": str(registry[name]["domain"])} for name in sorted(registry)}}


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two raters over the same items (L1 against L2 on action_type)."""
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equal, non-empty label lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    cats = set(a) | set(b)
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)
