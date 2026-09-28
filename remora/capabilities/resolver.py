# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Derive the minimal capability set from trusted state (quality program Q8.1).

The effective set is an intersection, and every operand comes from the
deployment, never from the agent::

    C_effective = C_requested ∩ C_principal ∩ C_task ∩ C_tenant
                  ∩ C_environment ∩ C_registry − C_denied

Default deny. A principal, task, tenant or environment the policy does not
name contributes the empty set, so the result is empty. A tool the registry
does not hold, or holds for other environments only, is never in the result.
``requested`` is the one operand a caller supplies, and it can only narrow:
asking for a tool adds nothing the other operands do not already allow.

``principal_id`` must be the authenticated principal, taken from the
transport, never from the request body; that is the caller's obligation and
the execution API meets it (Q8.2).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any

from remora.capabilities.model import CapabilityEpochs, EffectiveCapabilitySet

__all__ = ["CapabilityPolicy", "CapabilityResolver"]


def _frozen(mapping: Mapping[str, Iterable[str]] | None) -> Mapping[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    for key, tools in (mapping or {}).items():
        values = frozenset(tools)
        if any("*" in t for t in values):
            raise ValueError(f"capability policy {key!r}: wildcards are not allowed")
        out[str(key)] = values
    return MappingProxyType(out)


@dataclass(frozen=True)
class CapabilityPolicy:
    """Deployment configuration: which tools each scope may use.

    ``registry`` maps each registered tool to the environments it may run
    in; it is the ToolSpec-eligibility operand. Every mapping is closed:
    a key it does not contain allows nothing.
    """

    policy_version: str
    registry_version: str
    registry: Mapping[str, frozenset[str]]
    principal_tools: Mapping[str, frozenset[str]]
    task_tools: Mapping[str, frozenset[str]]
    tenant_tools: Mapping[str, frozenset[str]]
    environment_tools: Mapping[str, frozenset[str]]
    denied_tools: frozenset[str] = field(default_factory=frozenset)
    ttl_seconds: int = 900

    def __post_init__(self) -> None:
        if not self.policy_version or not self.registry_version:
            raise ValueError("a capability policy needs a policy and a registry version")
        if not 0 < self.ttl_seconds <= 86400:
            raise ValueError("ttl_seconds must be in (0, 86400]")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityPolicy":
        """Load the deployment's policy, for example from a YAML file."""
        return cls(
            policy_version=str(data["policy_version"]),
            registry_version=str(data["registry_version"]),
            registry=_frozen(data.get("registry")),
            principal_tools=_frozen(data.get("principals")),
            task_tools=_frozen(data.get("tasks")),
            tenant_tools=_frozen(data.get("tenants")),
            environment_tools=_frozen(data.get("environments")),
            denied_tools=frozenset(data.get("denied") or ()),
            ttl_seconds=int(data.get("ttl_seconds", 900)),
        )


class CapabilityResolver:
    """Computes :class:`EffectiveCapabilitySet` from a :class:`CapabilityPolicy`."""

    def __init__(self, policy: CapabilityPolicy) -> None:
        self.policy = policy

    def resolve(self, *, principal_id: str, tenant_id: str, environment: str,
                task_type: str, now: datetime,
                requested: Iterable[str] | None = None,
                epochs: CapabilityEpochs | None = None) -> EffectiveCapabilitySet:
        p = self.policy
        eligible = {tool for tool, envs in p.registry.items() if environment in envs}
        wanted = set(requested) if requested is not None else set(p.registry)
        allowed = (wanted
                   & p.principal_tools.get(principal_id, frozenset())
                   & p.task_tools.get(task_type, frozenset())
                   & p.tenant_tools.get(tenant_id, frozenset())
                   & p.environment_tools.get(environment, frozenset())
                   & eligible) - p.denied_tools
        denied = wanted - allowed if requested is not None else set()
        return EffectiveCapabilitySet(
            capability_set_id=str(uuid.uuid4()),
            principal_id=principal_id,
            tenant_id=tenant_id,
            environment=environment,
            task_type=task_type,
            allowed_tools=tuple(sorted(allowed)),
            policy_version=p.policy_version,
            registry_version=p.registry_version,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=p.ttl_seconds)).isoformat(),
            denied_tools=tuple(sorted(denied)),
            epochs=epochs or CapabilityEpochs(),
        )
