# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Capability sets can be revoked after they are issued (quality program Q8.6).

A capability set is valid until it expires. Between issuance and dispatch the
world can change: a principal is suspended, a tenant is frozen, the policy or
a ToolSpec is replaced. Each of those scopes has an epoch, a counter the
deployment advances when it changes. A set records the epochs it was issued
under; at dispatch the current epochs are read again, and a set issued under
an older epoch refuses as ``capability_stale``. A deployment can also revoke
one set outright, which refuses as ``capability_revoked``.

REMORA keeps no revocation state of its own here. The deployment supplies an
:class:`EpochSource` over whatever store it already makes durable, so there is
no in-process counter that a restart would reset. A source that cannot answer
refuses as ``capability_epoch_unverifiable``: an unknown epoch is not a
current one, or an outage would be the way around revocation.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from remora.capabilities.model import CapabilityEpochs, CapabilityRefusal, EffectiveCapabilitySet

__all__ = ["EpochSource", "StaticEpochSource", "revocation_refusal"]


@runtime_checkable
class EpochSource(Protocol):
    def current(self, tenant_id: str, principal_id: str) -> CapabilityEpochs:
        """The epochs in force now. Raises when it cannot answer."""
        ...

    def revoked(self, capability_set_id: str) -> bool:
        """Whether this one set was revoked. Raises when it cannot answer."""
        ...


@dataclass(frozen=True)
class StaticEpochSource:
    """An immutable epoch source: the deployment's current counters as data.

    For tests and for deployments that publish epochs as configuration. A
    deployment with a live store implements :class:`EpochSource` over it.
    """

    policy: int = 0
    toolspec: int = 0
    tenants: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    principals: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    revoked_sets: frozenset[str] = field(default_factory=frozenset)

    def current(self, tenant_id: str, principal_id: str) -> CapabilityEpochs:
        return CapabilityEpochs(principal=self.principals.get(principal_id, 0),
                                tenant=self.tenants.get(tenant_id, 0),
                                policy=self.policy, toolspec=self.toolspec)

    def revoked(self, capability_set_id: str) -> bool:
        return capability_set_id in self.revoked_sets


def revocation_refusal(capability_set: EffectiveCapabilitySet,
                       source: EpochSource | None) -> CapabilityRefusal | None:
    """Why the set is no longer current, or None. No source means no epochs."""
    if source is None:
        return None
    try:
        # A delegated set is revoked with any set it was delegated from, or a
        # revoked parent's children would keep working until they expired.
        for set_id in (capability_set.capability_set_id, *capability_set.ancestor_ids):
            if source.revoked(set_id):
                return CapabilityRefusal.REVOKED
        current = source.current(capability_set.tenant_id, capability_set.principal_id)
    except Exception:  # noqa: BLE001 - unknown is not current
        return CapabilityRefusal.EPOCH_UNVERIFIABLE
    if capability_set.epochs.behind(current):
        return CapabilityRefusal.STALE
    return None
