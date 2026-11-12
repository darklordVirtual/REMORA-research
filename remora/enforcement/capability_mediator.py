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
from datetime import datetime
from enum import Enum
from typing import Any

from remora.timebase import utc_now
from remora.capabilities.model import CapabilityRefusal, EffectiveCapabilitySet
from remora.capabilities.resource import ResourceRefused, canonical_resource
from remora.enforcement.execution_context import ExecutionContext
from remora.enforcement.flow_recipients import effect_recipient
from remora.frozen_json import freeze, thaw

__all__ = ["MAX_NESTED_EFFECTS", "CapabilityMediator", "EffectExecutor", "EffectRefused",
           "EffectState", "MediatedEffect"]

#: Requests one execution may make. Past it, requests refuse as
#: ``capability_effect_budget_exhausted`` and are counted, not recorded, so the
#: evidence stays bounded however the tool behaves (design section 14).
MAX_NESTED_EFFECTS = 64

#: ``(canonical_resource, arguments) -> result``, registered by the deployment
#: per effect capability. It holds whatever client or credential the effect needs.
EffectExecutor = Callable[[str, Mapping[str, Any]], Any]


class EffectRefused(Exception):
    """An executor's verdict that the effect did not run, with its reason.

    Raised by a remote executor when the effect domain refused (NTA-2 phase
    3). Distinct from any other exception, which leaves the state unknown: a
    refusal is first-hand knowledge that nothing happened.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
    # For a JSON-domain value (all an executor is ever given) ``default=str`` is
    # never called, so recorded hashes keep the encoding they always had. It
    # only labels a refused request whose arguments were outside JSON.
    try:
        payload = json.dumps({"capability": capability, "resource": resource,
                              "arguments": arguments}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload.encode()).hexdigest()


class CapabilityMediator:
    """The one path from a governed tool to its privileged effects."""

    def __init__(self, context: ExecutionContext, authority: EffectiveCapabilitySet, *,
                 executors: Mapping[str, EffectExecutor], epochs: Any = None,
                 state_reader: Any = None, max_effects: int = MAX_NESTED_EFFECTS,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self._context = context
        self._authority = authority
        self._executors = dict(executors)
        self._epochs = epochs
        self._reader = state_reader
        self._clock = clock
        self._closed = False
        self._lock = threading.Lock()
        self._records: list[MediatedEffect] = []
        if isinstance(max_effects, bool) or not isinstance(max_effects, int)                 or max_effects < 1:
            raise ValueError(f"max_effects must be an int >= 1, got {max_effects!r}")
        self._max_effects = max_effects
        #: Requests admitted against the budget: recorded ones plus those whose
        #: executor is still running. The budget is spent at admission, under
        #: the lock, because a record is written only after the executor
        #: returns (SDD-AS-v1 B03: two requests passed a budget of one).
        self._admitted = 0
        self._overflow = 0

    @property
    def context(self) -> ExecutionContext:
        return self._context

    @property
    def authority(self) -> EffectiveCapabilitySet:
        """The effect authority this mediator checks requests against."""
        return self._authority

    @property
    def records(self) -> tuple[MediatedEffect, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def pending(self) -> int:
        """Admitted requests whose executor has not returned yet.

        They have no record until it does, so this is the visible unsettled
        state: a request that is pending may already have had its effect.
        """
        with self._lock:
            return self._admitted - len(self._records)

    @property
    def overflow(self) -> int:
        """Requests refused because the budget was spent; not recorded one by one."""
        with self._lock:
            return self._overflow

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
        # IFC-12: under flow control the call's payload may reach only the
        # recipients the flow check approved; a network effect elsewhere is
        # refused before the ceiling is consulted, so the record says why.
        approved = self._context.flow_recipients
        if approved is not None:
            recipient = effect_recipient(capability, shown)
            if recipient is not None and recipient not in approved:
                return CapabilityRefusal.RECIPIENT_NOT_APPROVED, shown
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
            if self._admitted >= self._max_effects:
                self._overflow += 1
                return MediatedEffect(
                    execution_id=self._context.execution_id, capability=capability,
                    resource=resource if isinstance(resource, str) else "",
                    state=EffectState.REFUSED,
                    refusal=CapabilityRefusal.EFFECT_BUDGET_EXHAUSTED.value,
                    arguments_hash="", authority_digest=self._authority.digest)
            self._admitted += 1
            # One private, read-only copy taken now is what gets checked,
            # hashed and executed, so a caller mutating a nested value after
            # this point changes none of them. Outside JSON is refused, not
            # coerced with str().
            try:
                frozen = freeze(arguments) if isinstance(arguments, Mapping) else None
            except TypeError:
                frozen = None
            checked = arguments if frozen is None else thaw(frozen)
            if frozen is None:
                refusal, shown = self._refusal(capability, resource, None)
            else:
                refusal, shown = self._refusal(capability, resource, checked)
            base = dict(execution_id=self._context.execution_id, capability=capability,
                        resource=shown, authority_digest=self._authority.digest,
                        arguments_hash=_arguments_hash(capability, shown, checked))
            if refusal is not None:
                effect = MediatedEffect(state=EffectState.REFUSED, refusal=refusal.value, **base)
                self._records.append(effect)
                return effect
        # Outside the lock: an executor may take time, and it must not be able
        # to block close() or another request's refusal.
        try:
            result = self._executors[capability](shown, thaw(frozen))
        except EffectRefused as refused:
            effect = MediatedEffect(state=EffectState.REFUSED, refusal=refused.reason, **base)
            with self._lock:
                self._records.append(effect)
            return effect
        except Exception:
            effect = MediatedEffect(state=EffectState.UNKNOWN, refusal=None, **base)
        except BaseException:
            # Interrupted mid-effect: the admitted request still gets its
            # record, and it says the outcome is not known.
            with self._lock:
                self._records.append(
                    MediatedEffect(state=EffectState.UNKNOWN, refusal=None, **base))
            raise
        else:
            effect = MediatedEffect(state=EffectState.EXECUTED, refusal=None, result=result,
                                    **base)
        with self._lock:
            self._records.append(effect)
        return effect
