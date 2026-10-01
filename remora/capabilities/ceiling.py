# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Declared downstream capabilities: the ceiling on what a tool's
implementation may use (NTA-2).

Neutral ground between the ToolSpec, which declares the ceiling
(``remora.toolcall.toolspec``), and enforcement, which derives effect
authority from it (``remora.enforcement.effect_capability``). Those two may
not import each other, so the type both need lives here.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from remora.capabilities.resource import ResourceRefused, canonical_resource_pattern

__all__ = ["CeilingRefused", "DownstreamCeiling", "EffectCapability",
           "INITIAL_EFFECT_CAPABILITIES"]

#: The initial classes from the design (section 4). The set is extensible: a
#: name only has to be a dotted lower-case identifier.
INITIAL_EFFECT_CAPABILITIES = frozenset({
    "filesystem.read", "filesystem.write",
    "network.http.get", "network.http.post", "network.http.put", "network.http.patch",
    "network.http.delete",
    "database.read", "database.write", "database.delete",
    "secret.read", "process.execute", "queue.publish", "cloud.invoke",
})

_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class CeilingRefused(ValueError):
    """A downstream declaration that is malformed or ambiguous."""


@dataclass(frozen=True)
class EffectCapability:
    """One primitive ability, the resources it may touch, and why."""

    capability: str
    resources: tuple[str, ...]
    purpose: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EffectCapability":
        name = str(data.get("capability") or "")
        if not _NAME.match(name):
            raise CeilingRefused(f"invalid capability name {name!r}")
        purpose = str(data.get("purpose") or "").strip()
        if not purpose:
            raise CeilingRefused(f"{name}: a downstream capability states its purpose")
        raw = data.get("resources")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise CeilingRefused(f"{name}: at least one resource pattern")
        try:
            resources = tuple(sorted({canonical_resource_pattern(r) for r in raw}))
        except ResourceRefused as exc:
            raise CeilingRefused(f"{name}: {exc}") from exc
        return cls(capability=name, resources=resources, purpose=purpose)


@dataclass(frozen=True)
class DownstreamCeiling:
    """The most a tool's implementation may ever use. A ceiling, not a grant."""

    tool: str
    capabilities: tuple[EffectCapability, ...]

    @classmethod
    def from_dict(cls, tool: str, entries: Sequence[Mapping[str, Any]]) -> "DownstreamCeiling":
        parsed = [EffectCapability.from_dict(e) for e in entries]
        names = [c.capability for c in parsed]
        if len(names) != len(set(names)):
            raise CeilingRefused("a capability is declared once, with all its resources")
        return cls(tool=tool, capabilities=tuple(sorted(parsed, key=lambda c: c.capability)))

    def capability(self, name: str) -> EffectCapability | None:
        return next((c for c in self.capabilities if c.capability == name), None)

    def to_list(self) -> list[dict[str, Any]]:
        """The declaration form, so ``from_dict(tool, to_list())`` is the identity."""
        return [{"capability": c.capability, "resources": list(c.resources),
                 "purpose": c.purpose} for c in self.capabilities]

