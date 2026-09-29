# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Effect capabilities and the authority a tool's implementation may use (NTA-2).

A tool is an application-level operation (``report.generate``). An effect
capability is a primitive ability to touch an effect-bearing resource
(``filesystem.read`` on ``workspace://reports/*``). Authorizing the tool does
not authorize whatever its implementation can technically reach.

The maximum a tool's implementation may use is declared per tool as a
:class:`DownstreamCeiling` (``remora.capabilities.ceiling``), which a signed
ToolSpec carries as ``downstream_capabilities``. The ceiling is a
limit, not a grant: :func:`derive_effect_authority` issues effect authority only
for a tool the caller's capability set already authorizes, only while that set
is valid, and only up to the ceiling, which deployment policy can narrow and
never widen. The result is an ordinary ``EffectiveCapabilitySet`` chained to the
parent set, so the Q8.4 constraints, the Q8.5 attenuation rules and the Q8.6
revocation cascade apply to every effect unchanged.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta

from remora.capabilities.delegation import (
    MAX_DELEGATION_DEPTH,
    MAX_DELEGATION_TTL_SECONDS,
    DelegationDenied,
)
from remora.capabilities.ceiling import (
    INITIAL_EFFECT_CAPABILITIES,
    CeilingRefused,
    DownstreamCeiling,
    EffectCapability,
)
from remora.capabilities.model import EffectiveCapabilitySet, _parse

__all__ = ["CeilingRefused", "DownstreamCeiling", "EffectCapability",
           "INITIAL_EFFECT_CAPABILITIES", "derive_effect_authority"]

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
