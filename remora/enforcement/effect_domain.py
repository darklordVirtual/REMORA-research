# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The effect domain: mediated effects in a strict deployment (NTA-2 phase 3).

In the three-domain custody split the authority mints leases, the executor
runs tool code, and the effect domain holds the effect credentials and runs
the primitives mediated effects need. A tool in the executor reaches its
effects only by asking this domain, through ``RemoteEffectClient``.

The domain trusts nothing the worker says beyond the lease it presents:

1. The lease's signature, decision and validity window are verified here
   (``ExecutionLease.verify_authenticity``), with verification material only.
2. The lease must have been dispatched: ``execution_started(lease)``, which a
   deployment answers from the durable nonce store the executor consumed it
   in. A lease that was minted and never dispatched has no execution for
   effects to belong to. A check that cannot answer refuses.
3. The capability set presented must be the one the lease is bound to.
4. The effect authority is derived here, from that set and this domain's own
   copy of the tool's ceiling. Anything the worker sends about ceilings or
   authority is ignored, so a worker cannot widen what it may reach.
5. The per-execution budget and closure are kept here, keyed by the lease's
   digest. A closed execution stays closed; its lease cannot reopen it. With a
   ``ledger`` (the durable nonce store) both survive a restart: closure is the
   key ``effects-closed:<digest>`` and each effect that runs first claims a
   slot ``effect:<digest>:<i>`` below the budget.

The first effect of an execution must arrive while its lease is valid. The
execution then lasts as long as its effect authority, which is derived at the
first effect with the default lifetime of ``derive_effect_authority`` and never
outlives the caller's capability set.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from remora.capabilities.ceiling import DownstreamCeiling
from remora.capabilities.delegation import DelegationDenied
from remora.capabilities.model import CapabilityRefusal, EffectiveCapabilitySet, _parse
from remora.enforcement.capability_mediator import (
    MAX_NESTED_EFFECTS,
    CapabilityMediator,
    EffectRefused,
    MediatedEffect,
)
from remora.enforcement.effect_capability import derive_effect_authority
from remora.enforcement.execution_context import ExecutionContext
from remora.enforcement.lease import ExecutionLease

__all__ = ["EffectDomain", "effect_to_wire"]


def effect_to_wire(effect: MediatedEffect) -> dict[str, Any]:
    return {
        "state": effect.state.value,
        "refusal": effect.refusal,
        "resource": effect.resource,
        "arguments_hash": effect.arguments_hash,
        "authority_digest": effect.authority_digest,
        "execution_id": effect.execution_id,
        "result": effect.result,
    }


def _refused(reason: str) -> dict[str, Any]:
    return {"state": "REFUSED", "refusal": reason, "result": None}


class EffectDomain:
    """Serves mediated effects for dispatched executions. One per effect process."""

    def __init__(self, *, ceilings: Callable[[str], DownstreamCeiling | None],
                 executors: Mapping[str, Callable[[str, Mapping[str, Any]], Any]],
                 execution_started: Callable[[ExecutionLease], bool],
                 epochs: Any = None, state_reader: Any = None, ledger: Any = None,
                 max_effects: int = MAX_NESTED_EFFECTS,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._ledger = ledger
        self._max_effects = max_effects
        self._next_slot: dict[str, int] = {}
        self._ceilings = ceilings
        self._executors = dict(executors)
        self._execution_started = execution_started
        self._epochs = epochs
        self._reader = state_reader
        self._clock = clock
        self._lock = threading.Lock()
        self._open: dict[str, CapabilityMediator] = {}
        #: Closed lease digests, until their effect authority would have
        #: expired anyway; after that the lease itself can no longer open one.
        self._closed: dict[str, datetime] = {}

    def _evict(self, now: datetime) -> None:
        for digest in [d for d, until in self._closed.items() if until <= now]:
            del self._closed[digest]
        for digest, mediator in list(self._open.items()):
            if _parse(mediator.authority.expires_at) <= now:
                self._closed[digest] = _parse(mediator.authority.expires_at)
                del self._open[digest]

    def _claim_slot(self, digest: str, tenant_id: str) -> None:
        """Claim the next durable effect slot, or refuse the effect."""
        if self._ledger is None:
            return
        start = self._next_slot.get(digest, 0)
        for index in range(start, self._max_effects):
            try:
                claimed = self._ledger.try_consume(f"effect:{digest}:{index}",
                                                   tenant_id=tenant_id)
            except Exception as exc:  # noqa: BLE001 - unknown is not a free slot
                raise EffectRefused("execution_state_unverifiable") from exc
            if claimed:
                self._next_slot[digest] = index + 1
                return
        raise EffectRefused(CapabilityRefusal.EFFECT_BUDGET_EXHAUSTED.value)

    def _slotted(self, digest: str, tenant_id: str) -> dict[str, Callable[..., Any]]:
        def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            def run(resource: str, arguments: Mapping[str, Any]) -> Any:
                self._claim_slot(digest, tenant_id)
                return fn(resource, arguments)
            return run
        return {name: wrap(fn) for name, fn in self._executors.items()}

    def _open_execution(self, lease: ExecutionLease, request: Mapping[str, Any],
                        now: datetime) -> CapabilityMediator | str:
        verdict = lease.verify_authenticity(now=now.isoformat())
        if not verdict.verified:
            return verdict.reason
        if self._ledger is not None:
            try:
                closed = self._ledger.consumed(f"effects-closed:{lease.digest()}",
                                               tenant_id=lease.tenant_id)
            except Exception:  # noqa: BLE001 - unknown is not open
                return "execution_state_unverifiable"
            if closed:
                return CapabilityRefusal.CONTEXT_MISSING.value
        try:
            started = self._execution_started(lease)
        except Exception:  # noqa: BLE001 - an unknown answer is not a yes
            return "execution_state_unverifiable"
        if not started:
            return "execution_not_started"
        try:
            capability_set = EffectiveCapabilitySet.from_dict(dict(request["capability_set"]))
        except (KeyError, TypeError, ValueError):
            return CapabilityRefusal.DIGEST_MISMATCH.value
        if not lease.capability_digest or capability_set.digest != lease.capability_digest:
            return CapabilityRefusal.DIGEST_MISMATCH.value
        try:
            ceiling = self._ceilings(lease.tool_name)
        except Exception:  # noqa: BLE001 - an unreadable ceiling is not an empty one
            return "downstream_ceiling_unavailable"
        if ceiling is None:
            ceiling = DownstreamCeiling(tool=lease.tool_name, capabilities=())
        try:
            authority = derive_effect_authority(capability_set, tool_name=lease.tool_name,
                                                ceiling=ceiling, now=now)
        except DelegationDenied:
            return CapabilityRefusal.DELEGATION_DENIED.value
        context = ExecutionContext.for_dispatch(
            tool_name=lease.tool_name, capability_set=capability_set,
            proposal_id=lease.proposal_id, policy_bundle_hash=lease.policy_bundle_hash,
            toolspec_hash=lease.toolspec_hash, lease_digest=lease.digest(),
            context_id=lease.context_id, task_id=lease.task_id)
        return CapabilityMediator(context, authority,
                                  executors=self._slotted(lease.digest(), lease.tenant_id),
                                  epochs=self._epochs, state_reader=self._reader,
                                  max_effects=self._max_effects, clock=self._clock)

    def serve(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """One effect request from a tool worker; always an answer, never a raise."""
        try:
            lease = ExecutionLease.from_dict(dict(request["lease"]))
            capability = request["capability"]
            arguments = request.get("arguments") or {}
            if not isinstance(capability, str) or not isinstance(arguments, Mapping):
                raise TypeError("capability is a string and arguments a mapping")
        except (KeyError, TypeError, ValueError):
            return _refused("request_malformed")
        now = self._clock()
        digest = lease.digest()
        with self._lock:
            self._evict(now)
            if digest in self._closed:
                return _refused(CapabilityRefusal.CONTEXT_MISSING.value)
            mediator = self._open.get(digest)
            if mediator is None:
                opened = self._open_execution(lease, request, now)
                if isinstance(opened, str):
                    return _refused(opened)
                mediator = self._open[digest] = opened
        return effect_to_wire(mediator.invoke(capability, request.get("resource"), arguments))

    def close(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """End an execution. Anyone holding the lease may close it early; that
        only removes authority, so it needs no more proof than the lease."""
        try:
            lease = ExecutionLease.from_dict(dict(request["lease"]))
        except (KeyError, TypeError, ValueError):
            return {"closed": False, "refusal": "request_malformed"}
        if not lease.verify_authenticity(now=self._clock().isoformat()).verified and \
                lease.digest() not in self._open:
            return {"closed": False, "refusal": "lease_not_authentic"}
        digest = lease.digest()
        with self._lock:
            mediator = self._open.pop(digest, None)
            until = (_parse(mediator.authority.expires_at) if mediator is not None
                     else _parse(lease.expires_at))
            self._closed[digest] = max(until, self._clock())
        if mediator is not None:
            mediator.close()
        durable = self._ledger is None
        if self._ledger is not None:
            try:
                self._ledger.try_consume(f"effects-closed:{digest}", tenant_id=lease.tenant_id)
                durable = True
            except Exception:  # noqa: BLE001 - closed here; the lease's expiry bounds the rest
                durable = False
        return {"closed": True, "durable": durable,
                "effects": len(mediator.records) if mediator else 0}
