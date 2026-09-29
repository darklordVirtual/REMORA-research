# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The effective capability set and its refusals (quality program Q8.1).

An :class:`EffectiveCapabilitySet` names the tools one principal may see and
request, in one tenant and environment, for one task, until it expires. It
is derived from trusted state by :class:`~remora.capabilities.resolver.
CapabilityResolver` and never from anything the agent says.

The digest is SHA-256 over a canonical form of every field. It is what the
execution lease will carry (Q8.2), so a set cannot be widened after the
authorization it backed without the lease refusing. The set itself is not
signed here: its integrity comes from the lease signature that binds it.

Refusal codes are snake_case strings, the form every other REMORA refusal
uses (``task_mismatch``, ``stale_plan``).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

__all__ = ["CapabilityEpochs", "CapabilityRefusal", "EffectiveCapabilitySet"]


class CapabilityRefusal(str, Enum):
    """Why a capability check refused. Machine-readable and stable."""

    NOT_VISIBLE = "capability_not_visible"
    NOT_ALLOWED = "capability_not_allowed"
    EXPIRED = "capability_expired"
    NOT_YET_VALID = "capability_not_yet_valid"
    REVOKED = "capability_revoked"
    STALE = "capability_stale"
    ARGUMENT_MISMATCH = "capability_argument_mismatch"
    DELEGATION_DENIED = "capability_delegation_denied"
    SCOPE_VIOLATION = "capability_scope_violation"
    ENVIRONMENT_MISMATCH = "capability_environment_mismatch"
    TENANT_MISMATCH = "capability_tenant_mismatch"
    PRINCIPAL_MISMATCH = "capability_principal_mismatch"
    DIGEST_MISMATCH = "capability_digest_mismatch"
    STATE_UNVERIFIABLE = "capability_state_unverifiable"
    EPOCH_UNVERIFIABLE = "capability_epoch_unverifiable"
    # NTA-2 (docs/design/authority-preserving-capability-mediation-v1.md):
    # an effect capability used on a resource outside its patterns, or a
    # mediated effect with no active execution, no resolved resource, or no
    # executor for the capability.
    RESOURCE_NOT_AUTHORIZED = "capability_resource_not_authorized"
    CONTEXT_MISSING = "capability_context_missing"
    DEFAULT_UNRESOLVED = "capability_default_unresolved"
    EXECUTOR_UNAVAILABLE = "capability_executor_unavailable"


@dataclass(frozen=True)
class CapabilityEpochs:
    """Revocation counters the set was issued under (used by Q8.6).

    A set issued at an epoch behind the current one is stale. Zero means the
    deployment keeps no counter for that scope.
    """

    principal: int = 0
    tenant: int = 0
    policy: int = 0
    toolspec: int = 0

    def behind(self, current: "CapabilityEpochs") -> tuple[str, ...]:
        """The scopes whose current epoch has moved past this set's."""
        return tuple(name for name in ("principal", "tenant", "policy", "toolspec")
                     if getattr(current, name) > getattr(self, name))


def _freeze(value: Any) -> Any:
    """Deep read-only copy: mappings become MappingProxyType, lists tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    """The JSON form of a frozen value; identical to what was frozen."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def _parse(ts: str) -> datetime:
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without a timezone: {ts!r}")
    return parsed


@dataclass(frozen=True)
class EffectiveCapabilitySet:
    """The tools one principal may see and request for one task."""

    capability_set_id: str
    principal_id: str
    tenant_id: str
    environment: str
    task_type: str
    allowed_tools: tuple[str, ...]
    policy_version: str
    registry_version: str
    issued_at: str
    expires_at: str
    #: Requested tools the resolution removed, kept for evidence. Not part of
    #: what the set permits.
    denied_tools: tuple[str, ...] = ()
    epochs: CapabilityEpochs = field(default_factory=CapabilityEpochs)
    #: Q8.4: canonical ToolConstraint forms for allowed tools that have one.
    #: Part of the digest only when non-empty, so a set without constraints
    #: keeps the digest it had before constraints existed.
    constraints: Mapping[str, Any] = field(default_factory=dict)
    #: Q8.5: set on a delegated set only (remora.capabilities.delegation).
    #: The parent's digest chains the child to the authority it came from;
    #: all four enter the digest only on a delegated set.
    parent_digest: str = ""
    purpose: str = ""
    delegation_depth: int = 0
    transitive: bool = False
    #: Every set this one was delegated from, nearest last. Revoking any of
    #: them revokes this one (Q8.6). Part of the delegation block.
    ancestor_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("capability_set_id", "principal_id", "tenant_id", "environment",
                     "task_type", "policy_version", "registry_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be blank")
        if tuple(sorted(set(self.allowed_tools))) != self.allowed_tools:
            raise ValueError("allowed_tools must be sorted and unique")
        if any("*" in tool for tool in self.allowed_tools):
            # A wildcard cannot be attenuated or audited; the A2A delegation
            # chain refuses it for the same reason.
            raise ValueError("a capability set may not contain a wildcard")
        if _parse(self.expires_at) <= _parse(self.issued_at):
            raise ValueError("expires_at must be after issued_at")
        # A frozen dataclass does not freeze a dict field. The digest would
        # catch a later change at the dispatcher, but delegation reads the
        # constraints directly, so they are made read-only here.
        object.__setattr__(self, "constraints", _freeze(self.constraints))
        object.__setattr__(self, "ancestor_ids", tuple(self.ancestor_ids))

    def canonical(self) -> dict[str, Any]:
        return {
            "allowed_tools": list(self.allowed_tools),
            "capability_set_id": self.capability_set_id,
            "denied_tools": list(self.denied_tools),
            "environment": self.environment,
            "epochs": {"policy": self.epochs.policy, "principal": self.epochs.principal,
                       "tenant": self.epochs.tenant, "toolspec": self.epochs.toolspec},
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "policy_version": self.policy_version,
            "principal_id": self.principal_id,
            "registry_version": self.registry_version,
            "task_type": self.task_type,
            "tenant_id": self.tenant_id,
            **({"constraints": {k: _thaw(self.constraints[k]) for k in sorted(self.constraints)}}
               if self.constraints else {}),
            **({"delegation": {"ancestors": list(self.ancestor_ids),
                               "depth": self.delegation_depth,
                               "parent_digest": self.parent_digest,
                               "purpose": self.purpose,
                               "transitive": self.transitive}}
               if self.parent_digest else {}),
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical form; carried by the execution lease."""
        canonical = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical(), "digest": self.digest}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EffectiveCapabilitySet":
        """Rebuild a set and refuse one whose content does not match its digest."""
        epochs = data.get("epochs") or {}
        built = cls(
            capability_set_id=str(data["capability_set_id"]),
            principal_id=str(data["principal_id"]),
            tenant_id=str(data["tenant_id"]),
            environment=str(data["environment"]),
            task_type=str(data["task_type"]),
            allowed_tools=tuple(data["allowed_tools"]),
            policy_version=str(data["policy_version"]),
            registry_version=str(data["registry_version"]),
            issued_at=str(data["issued_at"]),
            expires_at=str(data["expires_at"]),
            denied_tools=tuple(data.get("denied_tools") or ()),
            epochs=CapabilityEpochs(**{k: int(v) for k, v in epochs.items()}),
            constraints=dict(data.get("constraints") or {}),
            parent_digest=str((data.get("delegation") or {}).get("parent_digest", "")),
            purpose=str((data.get("delegation") or {}).get("purpose", "")),
            delegation_depth=int((data.get("delegation") or {}).get("depth", 0)),
            transitive=bool((data.get("delegation") or {}).get("transitive", False)),
            ancestor_ids=tuple((data.get("delegation") or {}).get("ancestors") or ()),
        )
        claimed = data.get("digest")
        if claimed is not None and claimed != built.digest:
            raise ValueError(CapabilityRefusal.DIGEST_MISMATCH.value)
        return built

    def check(self, tool_name: str, *, principal_id: str, tenant_id: str,
              environment: str, now: datetime) -> CapabilityRefusal | None:
        """Why ``tool_name`` may not be used under this set now, or None.

        The binding is checked before membership, so a set presented by the
        wrong principal, in the wrong tenant or environment, refuses for that
        reason rather than looking like an ordinary missing tool.
        """
        if principal_id != self.principal_id:
            return CapabilityRefusal.PRINCIPAL_MISMATCH
        if tenant_id != self.tenant_id:
            return CapabilityRefusal.TENANT_MISMATCH
        if environment != self.environment:
            return CapabilityRefusal.ENVIRONMENT_MISMATCH
        if now < _parse(self.issued_at):
            return CapabilityRefusal.NOT_YET_VALID
        if now >= _parse(self.expires_at):
            return CapabilityRefusal.EXPIRED
        if tool_name not in self.allowed_tools:
            return CapabilityRefusal.NOT_ALLOWED
        return None

    def check_arguments(self, tool_name: str, arguments: Any,
                        reader: Any = None) -> CapabilityRefusal | None:
        """Why ``arguments`` exceed the tool's scope in this set (Q8.4), or None.

        ``reader`` is the deployment's trusted-state reader; a constraint that
        needs state refuses without one.
        """
        from remora.capabilities.constraints import ToolConstraint, evaluate_constraint

        raw = self.constraints.get(tool_name)
        if raw is None:
            return None
        return evaluate_constraint(ToolConstraint.from_dict(raw), arguments, reader)
