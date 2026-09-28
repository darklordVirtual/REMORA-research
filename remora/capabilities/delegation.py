# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Delegation never widens authority (quality program Q8.5).

A tool the agent may call can itself need another tool: ``report.generate``
reads a database and sends an email. If the inner call simply ran under the
caller's authority, the wrapper would be a confused deputy: the agent would
reach ``email.send`` through a tool it was allowed, with a scope nobody
granted it for that purpose.

A delegation is a child capability set derived from a parent set, for one
delegatee and one purpose:

subset
    the child's tools are a subset of the parent's; asking for more refuses.
narrowing
    the child inherits the parent's constraints for those tools and may only
    add conditions or narrow allowed fields, never drop them.
short-lived
    it cannot outlive its parent, and its lifetime is capped.
non-transitive by default
    a delegated set cannot be delegated again unless it was created with
    ``transitive=True``, which in turn needs a parent that permits it.
chained
    the child's digest covers the parent's digest, so the chain cannot be
    rewritten after the fact.

The child is an ordinary ``EffectiveCapabilitySet`` for the delegatee, so the
lease binding, the dispatcher checks and the constraints of Q8.2 to Q8.4
apply to the nested call unchanged: a nested call outside the delegation is
refused like any tool outside a set.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from remora.capabilities.model import CapabilityRefusal, EffectiveCapabilitySet, _parse
from remora.errors import RemoraError

__all__ = ["DelegationDenied", "MAX_DELEGATION_TTL_SECONDS", "delegate"]

#: A delegation is for one nested step, not a standing grant.
MAX_DELEGATION_TTL_SECONDS = 300


class DelegationDenied(RemoraError, ValueError):
    """A delegation that would widen, outlive or re-delegate authority."""

    code = CapabilityRefusal.DELEGATION_DENIED.value
    category = "capabilities"


def _narrowed(parent: Mapping[str, Any] | None, extra: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Parent constraint plus the extra one, which can only narrow it."""
    if parent is None and extra is None:
        return None
    parent = dict(parent or {})
    extra = dict(extra or {})
    out: dict[str, Any] = {"conditions": list(parent.get("conditions") or [])
                           + list(extra.get("conditions") or [])}
    fields = [f for f in (parent.get("allowed_fields"), extra.get("allowed_fields")) if f is not None]
    if fields:
        narrowed = set(fields[0])
        for more in fields[1:]:
            narrowed &= set(more)
        out["allowed_fields"] = sorted(narrowed)
    return out


def delegate(parent: EffectiveCapabilitySet, *, delegatee: str, tools: Iterable[str],
             purpose: str, now: datetime, ttl_seconds: int = 60,
             extra_constraints: Mapping[str, Mapping[str, Any]] | None = None,
             transitive: bool = False) -> EffectiveCapabilitySet:
    """A child set for ``delegatee``, or ``DelegationDenied``."""
    wanted: Sequence[str] = tuple(sorted(set(tools)))
    if not purpose.strip():
        raise DelegationDenied("a delegation must name its purpose")
    if not delegatee.strip():
        raise DelegationDenied("a delegation must name its delegatee")
    if parent.parent_digest and not parent.transitive:
        raise DelegationDenied("the parent is itself a delegation and is not transitive")
    outside = set(wanted) - set(parent.allowed_tools)
    if outside:
        raise DelegationDenied(f"tools outside the parent's set: {sorted(outside)}")
    if not 0 < ttl_seconds <= MAX_DELEGATION_TTL_SECONDS:
        raise DelegationDenied(f"ttl must be in (0, {MAX_DELEGATION_TTL_SECONDS}] seconds")
    if now < _parse(parent.issued_at) or now >= _parse(parent.expires_at):
        raise DelegationDenied("the parent set is not valid now")
    expires = min(now + timedelta(seconds=ttl_seconds), _parse(parent.expires_at))
    extra = extra_constraints or {}
    unknown = set(extra) - set(wanted)
    if unknown:
        raise DelegationDenied(f"constraints for tools not delegated: {sorted(unknown)}")
    constraints: dict[str, Any] = {}
    for tool in wanted:
        merged = _narrowed(parent.constraints.get(tool), extra.get(tool))
        if merged is not None:
            constraints[tool] = merged
    return EffectiveCapabilitySet(
        capability_set_id=str(uuid.uuid4()),
        principal_id=delegatee,
        tenant_id=parent.tenant_id,
        environment=parent.environment,
        task_type=parent.task_type,
        allowed_tools=tuple(wanted),
        policy_version=parent.policy_version,
        registry_version=parent.registry_version,
        issued_at=now.isoformat(),
        expires_at=expires.isoformat(),
        epochs=parent.epochs,
        constraints=constraints,
        parent_digest=parent.digest,
        purpose=purpose,
        delegation_depth=parent.delegation_depth + 1,
        transitive=transitive,
    )
