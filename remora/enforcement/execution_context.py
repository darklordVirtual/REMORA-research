# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The authority context of one governed execution (NTA-2).

Created by the enforcement layer when it dispatches a tool, from the lease and
the capability set it verified, and handed to the mediator. The tool
implementation receives the mediator, never the fields: it does not name its
principal, tenant, task, policy or parent set when it asks for an effect.

Research profile: the object is immutable, but code running in the same
Python process can build another one. Nothing here is a claim of bypass
resistance; that needs the strict profile's process separation (design
section 11).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from remora.capabilities.model import EffectiveCapabilitySet

__all__ = ["ExecutionContext"]


@dataclass(frozen=True)
class ExecutionContext:
    execution_id: str
    proposal_id: str
    tenant_id: str
    principal_id: str
    target_environment: str
    context_id: str
    task_id: str
    tool_name: str
    toolspec_hash: str
    policy_bundle_hash: str
    capability_digest: str
    runtime_identity_hash: str
    parent_lease_digest: str

    @classmethod
    def for_dispatch(cls, *, tool_name: str, capability_set: EffectiveCapabilitySet,
                     proposal_id: str, policy_bundle_hash: str, toolspec_hash: str,
                     lease_digest: str, context_id: str = "", task_id: str = "",
                     runtime_identity_hash: str = "") -> "ExecutionContext":
        """The context for dispatching ``tool_name`` under ``capability_set``."""
        return cls(
            execution_id=str(uuid.uuid4()),
            proposal_id=proposal_id,
            tenant_id=capability_set.tenant_id,
            principal_id=capability_set.principal_id,
            target_environment=capability_set.environment,
            context_id=context_id,
            task_id=task_id,
            tool_name=tool_name,
            toolspec_hash=toolspec_hash,
            policy_bundle_hash=policy_bundle_hash,
            capability_digest=capability_set.digest,
            runtime_identity_hash=runtime_identity_hash,
            parent_lease_digest=lease_digest,
        )
