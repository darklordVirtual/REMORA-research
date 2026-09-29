# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Mediated privileged effects inside a governed execution (NTA-2, phase 1).

A tool implementation asks the mediator for an effect instead of calling a
filesystem, database or HTTP client itself::

    rows = mediator.invoke("database.read", "database://reporting-eu/monthly",
                           {"query": q})

The mediator checks the request against the effect authority derived for this
execution (``derive_effect_authority``) and only then calls the executor the
deployment registered for that capability, with the canonical resource. It
fails closed: a missing context, an unresolved resource, a capability or
resource outside the authority, a revoked or stale parent, or a missing
executor all refuse before anything runs, and there is no fallback to direct
access. Every request, refused or not, is recorded.

Research profile only. The mediator runs in the tool's own process, so it
demonstrates authority semantics and records what was asked for; it does not
stop code that ignores it and uses a client directly. That needs the strict
profile's separation of effect credentials from tool workers (design
section 11), which is not implemented here.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from remora.capabilities.model import CapabilityRefusal, EffectiveCapabilitySet
from remora.capabilities.resource import ResourceRefused, canonical_resource
from remora.enforcement.execution_context import ExecutionContext

__all__ = ["CapabilityMediator", "EffectExecutor", "EffectState", "MediatedEffect"]

#: ``(canonical_resource, arguments) -> result``, registered by the deployment
#: per effect capability. It holds whatever client or credential the effect needs.
EffectExecutor = Callable[[str, Mapping[str, Any]], Any]


class EffectState(str, Enum):
    REFUSED = "REFUSED"
    EXECUTED = "EXECUTED"
    # The executor was called and raised: the effect may or may not have
    # happened, which is not the same claim as "nothing happened".
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MediatedEffect:
    """One mediated request and what became of it."""

    execution_id: str
    capability: str
    resource: str
    state: EffectState
    refusal: str | None
    arguments_hash: str
    authority_digest: str
    result: Any = None

    @property
    def executed(self) -> bool:
        return self.state is EffectState.EXECUTED


def _arguments_hash(capability: str, resource: str, arguments: Any) -> str:
    payload = json.dumps({"capability": capability, "resource": resource,
                          "arguments": arguments}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class CapabilityMediator:
    """The one path from a governed tool to its privileged effects."""

    def __init__(self, context: ExecutionContext, authority: EffectiveCapabilitySet, *,
                 executors: Mapping[str, EffectExecutor], epochs: Any = None,
                 state_reader: Any = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._context = context
        self._authority = authority
        self._executors = dict(executors)
        self._epochs = epochs
        self._reader = state_reader
        self._clock = clock
        self._closed = False
        self._lock = threading.Lock()
        self._records: list[MediatedEffect] = []

    @property
    def context(self) -> ExecutionContext:
        return self._context

    @property
    def records(self) -> tuple[MediatedEffect, ...]:
        with self._lock:
            return tuple(self._records)

    def close(self) -> None:
        """End the execution: later requests refuse as ``capability_context_missing``."""
        with self._lock:
            self._closed = True

    def _refusal(self, capability: str, resource: str | None,
                 arguments: Any) -> tuple[CapabilityRefusal | None, str]:
        """Why this request may not run, and the resource as it will be recorded."""
        shown = resource if isinstance(resource, str) else ""
        if self._closed:
            return CapabilityRefusal.CONTEXT_MISSING, shown
        if self._authority.parent_digest != self._context.capability_digest:
            return CapabilityRefusal.DIGEST_MISMATCH, shown
        if resource is None or resource == "":
            return CapabilityRefusal.DEFAULT_UNRESOLVED, shown
        if not isinstance(arguments, Mapping) or "resource" in arguments:
            return CapabilityRefusal.ARGUMENT_MISMATCH, shown
        try:
            shown = canonical_resource(resource)
        except ResourceRefused:
            return CapabilityRefusal.RESOURCE_NOT_AUTHORIZED, shown
        refusal = self._authority.check(
            capability, principal_id=self._context.tool_name,
            tenant_id=self._context.tenant_id, environment=self._context.target_environment,
            now=self._clock())
        if refusal is None:
            refusal = self._authority.check_arguments(
                capability, {**arguments, "resource": shown}, self._reader)
        if refusal is None:
            from remora.capabilities.revocation import revocation_refusal

            refusal = revocation_refusal(self._authority, self._epochs)
        if refusal is None and capability not in self._executors:
            refusal = CapabilityRefusal.EXECUTOR_UNAVAILABLE
        return refusal, shown

    def invoke(self, capability: str, resource: str | None,
               arguments: Mapping[str, Any] | None = None) -> MediatedEffect:
        """Run one effect under this execution's authority, or refuse it."""
        arguments = {} if arguments is None else arguments
        with self._lock:
            refusal, shown = self._refusal(capability, resource, arguments)
            base = dict(execution_id=self._context.execution_id, capability=capability,
                        resource=shown, authority_digest=self._authority.digest,
                        arguments_hash=_arguments_hash(capability, shown, arguments))
            if refusal is not None:
                effect = MediatedEffect(state=EffectState.REFUSED, refusal=refusal.value, **base)
                self._records.append(effect)
                return effect
        # Outside the lock: an executor may take time, and it must not be able
        # to block close() or another request's refusal.
        try:
            result = self._executors[capability](shown, dict(arguments))
        except Exception:  # noqa: BLE001 - began and failed: the state is unknown
            effect = MediatedEffect(state=EffectState.UNKNOWN, refusal=None, **base)
        else:
            effect = MediatedEffect(state=EffectState.EXECUTED, refusal=None, result=result,
                                    **base)
        with self._lock:
            self._records.append(effect)
        return effect
