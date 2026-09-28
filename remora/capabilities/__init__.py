# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Capability minimization before reasoning (quality program WS8).

REMORA enforces authority after an agent proposes an action. This package
reduces what the agent can see and request in the first place: a capability
set is derived from trusted state for one principal, tenant, environment and
task, and everything outside it is denied by default. Design:
docs/design/capability-minimized-execution-v1.md.
"""
from remora.capabilities.delegation import DelegationDenied, delegate
from remora.capabilities.model import (
    CapabilityEpochs,
    CapabilityRefusal,
    EffectiveCapabilitySet,
)
from remora.capabilities.projector import CapabilityProjector, Projection
from remora.capabilities.resolver import CapabilityPolicy, CapabilityResolver
from remora.capabilities.revocation import EpochSource, StaticEpochSource, revocation_refusal

__all__ = [
    "CapabilityEpochs",
    "CapabilityPolicy",
    "CapabilityProjector",
    "CapabilityRefusal",
    "CapabilityResolver",
    "DelegationDenied",
    "EffectiveCapabilitySet",
    "EpochSource",
    "Projection",
    "StaticEpochSource",
    "delegate",
    "revocation_refusal",
]
