# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Project a capability set into the tool list an agent sees (quality program Q8.3).

Enforcement (Q8.2) refuses a tool outside the set when it is called. This is
the other half: the agent is never shown it. A tool the model does not see is
one it cannot reason about, be talked into calling by an injected
instruction, or name in a proposal enforcement then has to reject.

Visibility is not authorization. Everything projected here is enforced again
at invocation, so a client that skips the projection and calls a hidden tool
directly is still refused.

Formats: an OpenAI tool list, an MCP ``tools/list`` result, and a filter
over any list of tool descriptors that carry a ``name``. Each takes the set
and the registered tools, and returns only tools that are in both.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from remora.capabilities.model import EffectiveCapabilitySet

__all__ = ["CapabilityProjector", "Projection"]

_EMPTY_OBJECT_SCHEMA: Mapping[str, Any] = {"type": "object", "properties": {}}


@dataclass(frozen=True)
class Projection:
    """What an agent is shown, and how much of the registry that is."""

    capability_set_id: str
    capability_digest: str
    exposed: tuple[str, ...]
    registered_count: int

    @property
    def exposure_ratio(self) -> float:
        """Capability exposure ratio (SDD §28): exposed over registered."""
        return len(self.exposed) / self.registered_count if self.registered_count else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"capability_set_id": self.capability_set_id,
                "capability_digest": self.capability_digest,
                "exposed": list(self.exposed),
                "registered_count": self.registered_count,
                "exposure_ratio": round(self.exposure_ratio, 6)}


class CapabilityProjector:
    """Turns a capability set into agent-facing tool lists."""

    def __init__(self, capability_set: EffectiveCapabilitySet) -> None:
        self.capability_set = capability_set
        self._allowed = frozenset(capability_set.allowed_tools)

    def project(self, registered: Iterable[str]) -> Projection:
        """The tools to expose: in the set and actually registered."""
        registry = sorted(set(registered))
        exposed = tuple(name for name in registry if name in self._allowed)
        return Projection(self.capability_set.capability_set_id, self.capability_set.digest,
                          exposed, len(registry))

    def filter(self, descriptors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Keep only descriptors whose ``name`` is in the set, order preserved."""
        return [dict(d) for d in descriptors if d.get("name") in self._allowed]

    def for_mcp(self, tools_list_result: Mapping[str, Any]) -> dict[str, Any]:
        """Filter an MCP ``tools/list`` result (``{"tools": [...]}``)."""
        return {**tools_list_result, "tools": self.filter(tools_list_result.get("tools") or [])}

    def for_openai(self, specs: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        """An OpenAI ``tools`` list for the tools in the set.

        ``specs`` maps a tool name to its ``description`` and ``parameters``
        (a JSON Schema). A tool with no schema gets an empty object schema:
        the projection never invents arguments.
        """
        return [
            {"type": "function",
             "function": {"name": name,
                          "description": str(specs[name].get("description") or ""),
                          "parameters": dict(specs[name].get("parameters") or _EMPTY_OBJECT_SCHEMA)}}
            for name in self.project(specs).exposed
        ]
