# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Typed ports for the execution TCB's injected collaborators (issue #282).

``service.py``, ``dispatch.py`` and ``review_service.py`` take their
collaborators as parameters -- that is what makes them extractable and lets
the tests drive them with fakes. Until now those parameters were ``Any``, so
"mypy clean" said nothing about the component boundaries of the trusted
computing base: a caller could wire a chain without ``append_once`` or a gate
whose ``check`` returned the wrong shape, and the type checker had no opinion.

These are ``Protocol``\\s, not base classes, for one load-bearing reason: the
extraction tests substitute plain fakes (``SimpleNamespace``, small local
classes), and the production implementations (``TenantAuditChain``,
``EnforcementGate``, ``DispatchOutbox``, ``ReviewQueue``) must satisfy the
same contract without inheriting anything. Structural typing checks both
sides; a registry of subclasses would check neither.

Each protocol declares ONLY what the execution modules actually call. A port
is a statement of dependency, and listing methods nothing depends on would
turn it into a second copy of the implementation's interface -- the thing
that drifts. Widening a port is a deliberate act: add the member in the same
change as the first caller.

Return types stay concrete (``ChainEntry``, ``OutboxRow``, ``PendingReview``,
``ExecutionOutcome``, ``EnforcementResult``): the ports abstract WHO does the
work, not what the work produces. The produced records are contracts of their
own with their own tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import sqlite3

    from remora.enforcement.gate import EnforcementResult
    from remora.enforcement.outbox import OutboxRow, OutboxState
    from remora.governance.review_queue import (Approval, DispatchOutcome,
                                                ExecutionOutcome,
                                                PendingReview)
    from remora.governance.tenant_chain import ChainEntry
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionAction

__all__ = [
    "AuditChainPort",
    "DispatchOutboxPort",
    "EnforcementGatePort",
    "PolicyDecisionTokenPort",
    "PolicyEnginePort",
    "ReviewQueuePort",
    "ToolCallPort",
    "ToolDispatcherPort",
    "TransactionalAppendPort",
    "appender",
    "audit_ref",
]


class ToolCallPort(Protocol):
    """The proposed call, as every execution entrypoint receives it.

    Attribute names match both the Pydantic request model and the test
    fakes; nothing here implies mutability or a constructor.
    """

    @property
    def tool_name(self) -> str: ...
    @property
    def arguments(self) -> dict[str, Any]: ...
    @property
    def target_environment(self) -> str: ...


class PolicyDecisionTokenPort(Protocol):
    """The single-use ACCEPT token as the redeem path reads it.

    Verification happens inside the gate; this port is what the service
    layer touches directly -- identity, binding hash and audit fields, plus
    the authorization-context check the redeem path runs before consuming
    (RMR-001), which must refuse without burning the grant.
    """

    def verify(
        self,
        observation_hash: str | None = None,
        now: str | None = None,
        context: Any = None,
    ) -> Any: ...


    @property
    def jti(self) -> str: ...
    @property
    def action(self) -> Any: ...
    @property
    def observation_hash(self) -> str: ...
    @property
    def request_id(self) -> str: ...
    def to_dict(self) -> dict[str, Any]: ...


class AuditChainPort(Protocol):
    """Tenant-scoped, hash-chained audit record store."""

    def append(self, tenant_id: str, payload: dict[str, Any]) -> "ChainEntry": ...

    def append_once(
        self, tenant_id: str, idempotency_key: str, payload: dict[str, Any]
    ) -> "ChainEntry | None": ...

    def entries(self, tenant_id: str) -> tuple["ChainEntry", ...]: ...


class TransactionalAppendPort(Protocol):
    """Append an audit event, joining the caller's state transaction if open.

    Distinct from ``AuditChainPort.append`` because the return type is the
    whole point: ``None`` means the event was enqueued on the open transaction
    and has no chain index yet. The route layer binds this to
    ``servers.execution_api.chain_append_transactional`` (REM-047).
    """

    def __call__(
        self, tenant: str, payload: dict[str, Any], *, key: str
    ) -> "ChainEntry | None": ...


def audit_ref(entry: Any, *, key: str) -> dict[str, Any]:
    """The response's ``audit`` block, for an entry that may not exist yet.

    Lives here rather than in one of the two service modules because both
    shape it and neither owns it. A deferred event is reported as deferred:
    the chain has no index for it, and returning an invented one would make
    the response the least trustworthy record in the system.
    """

    if entry is not None:
        return {
            "sequence_no": entry.sequence_no,
            "entry_hash": entry.entry_hash,
            "deferred": False,
        }
    return {
        "sequence_no": None,
        "entry_hash": None,
        "deferred": True,
        "idempotency_key": key,
    }


def appender(
    chain: "AuditChainPort",
    transactional_append: "TransactionalAppendPort | None",
) -> "TransactionalAppendPort":
    """The transactional append when the caller wired one, else the plain chain.

    The fallback is not a weakening. A caller that wires no transactional
    append has no state transaction for the event to join (library and
    research use, and every test that drives these functions with fakes), so
    there is nothing for it to be atomic with and the chain append is already
    the whole write. The route layer always wires the real one.
    """

    if transactional_append is not None:
        return transactional_append

    def _direct(tenant: str, payload: dict[str, Any], *, key: str) -> Any:
        return chain.append(tenant, payload)

    return _direct


class EnforcementGatePort(Protocol):
    """The PEP: verifies a decision token and consumes its one-time grant."""

    def check(
        self,
        token: Any,
        expected_observation_hash: str | None = None,
        consume: bool = False,
        now: str | None = None,
        context: Any = None,
    ) -> "EnforcementResult": ...


class PolicyEnginePort(Protocol):
    """The PDP as the assess path drives it: one observation in, one report out.

    The report's shape is the DecisionReport contract; ``Any`` here is the
    honest current state -- the report type lives behind a research-profile
    import boundary -- and narrowing it is a follow-up, not a blocker.
    """

    def decide(self, observation: "PolicyObservation") -> Any: ...


class ToolDispatcherPort(Protocol):
    """Lease-verifying dispatcher (the governed final hop)."""

    def dispatch(
        self,
        lease: Any,
        tool_name: str,
        arguments: Any,
        *,
        tenant_id: str = "",
        target_environment: str | None = None,
        now: str | None = None,
        actor_identity: str | None = None,
    ) -> Any: ...


class DispatchOutboxPort(Protocol):
    """Crash-consistent dispatch-intent store (F-02)."""

    def record_intent(
        self,
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
        tool_call_json: str | None = None,
        authorization_expires_at: datetime | None = None,
        requested_by: str | None = None,
    ) -> "OutboxRow": ...

    def claim(
        self, outbox_id: str, *, worker_id: str, now: datetime | None = None
    ) -> "OutboxRow | None": ...

    def record_intent_enlisted(
        self,
        connection: "sqlite3.Connection",
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
        tool_call_json: str | None = None,
        authorization_expires_at: datetime | None = None,
        requested_by: str | None = None,
    ) -> "OutboxRow": ...

    def settle(
        self,
        outbox_id: str,
        state: "OutboxState",
        *,
        detail: str | None = None,
        now: datetime | None = None,
        projection_json: str | None = None,
    ) -> "OutboxRow": ...

    def mark_projected(
        self, outbox_id: str, *, now: datetime | None = None
    ) -> "OutboxRow": ...

    def unprojected_terminal(self, tenant_id: str) -> list["OutboxRow"]: ...

    def rows_for_proposal(
        self, tenant_id: str, proposal_id: str
    ) -> list["OutboxRow"]: ...


class ReviewQueuePort(Protocol):
    """The pending-review state machine, as the services drive it."""

    def item(self, item_id: str) -> "PendingReview": ...

    def enqueue(
        self,
        observation: "PolicyObservation",
        requested_action: "DecisionAction",
        queue_ttl: timedelta | None = None,
    ) -> "PendingReview": ...

    def expire_due(self, now: datetime | None = None) -> list["PendingReview"]: ...

    def approve(
        self, item_id: str, approver: str, approval_ttl: timedelta
    ) -> "Approval": ...

    def reject(
        self, item_id: str, reviewer: str, reason: str
    ) -> "PendingReview": ...

    def execute(
        self,
        item_id: str,
        fresh_observation: "PolicyObservation",
        now: datetime | None = None,
    ) -> "ExecutionOutcome": ...

    def record_execution_outcome(
        self,
        item_id: str,
        *,
        outcome: "DispatchOutcome",
        reason: str | None = None,
    ) -> "PendingReview": ...
