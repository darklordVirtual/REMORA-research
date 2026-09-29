# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The nested effects of one governed execution (NTA-2, design section 14).

``ResolvedEffect`` names the one effect a tool is declared to resolve to. A
tool's implementation can request more through its ``CapabilityMediator``;
the graph records each request as a node under the parent execution, in order:
capability, canonical resource, the authority it was checked against, the
hash of its arguments, and what became of it. Results are never part of it:
the graph records identities, as the audit chain does, not bodies.

The graph is bounded. The mediator refuses requests past
``MAX_NESTED_EFFECTS`` and counts them without recording them, and a graph
with an overflow is ``truncated``. An execution is ``settled`` only when no
child is ``UNKNOWN`` and nothing was truncated: missing evidence never reads
as established evidence (design section 15).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from remora.enforcement.capability_mediator import (
    MAX_NESTED_EFFECTS,
    CapabilityMediator,
    EffectState,
)

__all__ = ["MAX_NESTED_EFFECTS", "ResolvedEffectGraph", "ResolvedEffectNode"]


@dataclass(frozen=True)
class ResolvedEffectNode:
    index: int
    capability: str
    resource: str
    state: str
    refusal: str | None
    arguments_hash: str
    authority_digest: str


@dataclass(frozen=True)
class ResolvedEffectGraph:
    execution_id: str
    tool_name: str
    #: ``ResolvedEffect.digest()`` of the parent, when the lease carried one.
    root_effect_digest: str | None
    children: tuple[ResolvedEffectNode, ...]
    overflow: int = 0

    @property
    def truncated(self) -> bool:
        return self.overflow > 0

    @property
    def settled(self) -> bool:
        return not self.truncated and all(
            n.state != EffectState.UNKNOWN.value for n in self.children)

    @classmethod
    def from_mediator(cls, mediator: CapabilityMediator, *,
                      root_effect_digest: str | None) -> "ResolvedEffectGraph":
        nodes = tuple(
            ResolvedEffectNode(index=i, capability=r.capability, resource=r.resource,
                               state=r.state.value, refusal=r.refusal,
                               arguments_hash=r.arguments_hash,
                               authority_digest=r.authority_digest)
            for i, r in enumerate(mediator.records))
        return cls(execution_id=mediator.context.execution_id,
                   tool_name=mediator.context.tool_name,
                   root_effect_digest=root_effect_digest, children=nodes,
                   overflow=mediator.overflow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "tool_name": self.tool_name,
            "root_effect_digest": self.root_effect_digest,
            "children": [asdict(n) for n in self.children],
            "overflow": self.overflow,
            "max_nested_effects": MAX_NESTED_EFFECTS,
        }

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    def summary(self) -> dict[str, Any]:
        """The record the audit chain carries: counts and the graph's digest."""
        return {
            "mediated": True,
            "count": len(self.children),
            "by_state": dict(sorted(Counter(n.state for n in self.children).items())),
            "overflow": self.overflow,
            "settled": self.settled,
            "graph_sha256": self.digest(),
        }
