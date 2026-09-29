# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Effect capabilities and the authority a tool's implementation may use (NTA-2).

A tool is an application-level operation (``report.generate``). An effect
capability is a primitive ability to touch an effect-bearing resource
(``filesystem.read`` on ``workspace://reports/*``). Authorizing the tool does
not authorize whatever its implementation can technically reach.

The maximum a tool's implementation may use is declared per tool as a
:class:`DownstreamCeiling`, the shape a signed ToolSpec will carry (phase 2 of
docs/design/authority-preserving-capability-mediation-v1.md). The ceiling is a
limit, not a grant: :func:`derive_effect_authority` issues effect authority only
for a tool the caller's capability set already authorizes, only while that set
is valid, and only up to the ceiling, which deployment policy can narrow and
never widen. The result is an ordinary ``EffectiveCapabilitySet`` chained to the
parent set, so the Q8.4 constraints, the Q8.5 attenuation rules and the Q8.6
revocation cascade apply to every effect unchanged.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from remora.capabilities.delegation import (
    MAX_DELEGATION_DEPTH,
    MAX_DELEGATION_TTL_SECONDS,
    DelegationDenied,
)
from remora.capabilities.model import EffectiveCapabilitySet, _parse
from remora.capabilities.resource import ResourceRefused, canonical_resource_pattern

__all__ = ["CeilingRefused", "DownstreamCeiling", "EffectCapability",
           "INITIAL_EFFECT_CAPABILITIES", "derive_effect_authority"]

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


def derive_effect_authority(parent: EffectiveCapabilitySet, *, tool_name: str,
                            ceiling: DownstreamCeiling, now: datetime, ttl_seconds: int = 60,
                            policy_allows: Iterable[str] | None = None) -> EffectiveCapabilitySet:
    """The effect authority for one execution of ``tool_name``, or ``DelegationDenied``.

    Bound to the tool as its principal, chained to ``parent`` (digest and
    ancestry), inside the parent's lifetime, never transitive.
    """
    if ceiling.tool != tool_name:
        raise DelegationDenied(f"the ceiling is declared for {ceiling.tool!r}, not {tool_name!r}")
    if tool_name not in parent.allowed_tools:
        raise DelegationDenied(f"{tool_name!r} is outside the parent's set")
    if now < _parse(parent.issued_at) or now >= _parse(parent.expires_at):
        raise DelegationDenied("the parent set is not valid now")
    if parent.delegation_depth + 1 > MAX_DELEGATION_DEPTH:
        raise DelegationDenied(f"delegation deeper than {MAX_DELEGATION_DEPTH} hops")
    if not 0 < ttl_seconds <= MAX_DELEGATION_TTL_SECONDS:
        raise DelegationDenied(f"ttl must be in (0, {MAX_DELEGATION_TTL_SECONDS}] seconds")
    allowed = {c.capability for c in ceiling.capabilities}
    if policy_allows is not None:
        allowed &= set(policy_allows)
    constraints = {
        c.capability: {"conditions": [{"argument": "resource", "within": list(c.resources)}]}
        for c in ceiling.capabilities if c.capability in allowed
    }
    expires = min(now + timedelta(seconds=ttl_seconds), _parse(parent.expires_at))
    return EffectiveCapabilitySet(
        capability_set_id=str(uuid.uuid4()),
        principal_id=tool_name,
        tenant_id=parent.tenant_id,
        environment=parent.environment,
        task_type=parent.task_type,
        allowed_tools=tuple(sorted(allowed)),
        policy_version=parent.policy_version,
        registry_version=parent.registry_version,
        issued_at=now.isoformat(),
        expires_at=expires.isoformat(),
        epochs=parent.epochs,
        constraints=constraints,
        parent_digest=parent.digest,
        purpose=f"implementation_effects:{tool_name}",
        delegation_depth=parent.delegation_depth + 1,
        transitive=False,
        ancestor_ids=(*parent.ancestor_ids, parent.capability_set_id),
    )
