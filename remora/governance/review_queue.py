# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review queue with TTL expiry and the approval freshness contract.

Implements REM-033 and the review-queue portion of REM-032
(design: ``docs/assurance/resilience_plan_v1.md`` §2–3).

Semantics, in the order an item lives through them:

1. **Enqueue** — only VERIFY and ESCALATE decisions enter the queue
   (ACCEPT executes, ABSTAIN never executes; neither awaits a human).
2. **Queue TTL (REM-032)** — an item no reviewer touches within its TTL
   resolves to **ABSTAIN with a recorded ``review_expired_to_abstain``
   event** — never auto-accept, never indefinite silent pending.
3. **Approval (REM-033, closes audit F-2)** — ``expires_at`` is mandatory
   and bounded (0 < ttl ≤ 24 h). There is no legacy no-expiry mode here.
4. **Execution re-gate (REM-033)** — executing an approved item requires a
   *fresh* observation:

   - expired approval → the item returns to PENDING (``approval_expired``);
   - payload-binding mismatch (``tool_call_hash`` differs) → refused
     (``binding_refused``) — the caller-side complement of the enforcement
     gate's own recomputation;
   - the engine re-decides on the fresh observation. The approval survives
     only an equal-or-safer world:
     ``severity(fresh) <= severity(approved)`` → execute; otherwise the
     approval is void (``approval_invalidated``) and the item re-enters the
     queue carrying the fresh, stricter action. Decision monotonicity
     applied over time.

All state changes append to a hash-chained :class:`ChainedEventLog`
(tamper-evident; same discipline as the decision audit chain). The queue is
in-memory by design — persistence is a deployment concern; the semantics
above are storage-invariant.
"""
from __future__ import annotations

from remora.execution.outcome import DispatchOutcome

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum

from remora.governance.degradation import ChainedEvent, ChainedEventLog
from remora.governance.revocation_store import (
    InMemoryRevocationStore,
    RevocationStore,
)
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

# Approval TTL bounds (REM-033): no zero/negative, no beyond-a-day approvals.
MAX_APPROVAL_TTL = timedelta(hours=24)
DEFAULT_QUEUE_TTL = timedelta(hours=4)

_SEVERITY: dict[DecisionAction, int] = {
    DecisionAction.ACCEPT: 0,
    DecisionAction.VERIFY: 1,
    DecisionAction.ABSTAIN: 2,
    DecisionAction.ESCALATE: 3,
}


_OUTCOME_STATUS: "dict[DispatchOutcome, ItemStatus]" = {}


class ItemStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXPIRED_TO_ABSTAIN = "expired_to_abstain"
    # External review 2026-07-27: "authorized" and "executed" are distinct
    # states. execute() only ever AUTHORIZES (fresh re-gate passed, grant may
    # be consumed); EXECUTED is set exclusively by record_execution_outcome()
    # after the dispatcher reports a confirmed side effect. Refused/failed
    # dispatches get their own terminal states so the persisted record never
    # claims an execution that did not happen.
    AUTHORIZED = "authorized"
    # A reviewer's explicit refusal. Terminal, and deliberately distinct
    # from EXPIRED_TO_ABSTAIN: "a human looked and said no" is not the same
    # record as "nobody looked in time", and conflating them would erase
    # the review that actually happened.
    REJECTED = "rejected"
    EXECUTED = "executed"
    DISPATCH_REFUSED = "dispatch_refused"
    # A failure PROVEN to precede the effect boundary. Not reachable from the
    # synchronous path today: no adapter here produces that evidence, so a tool
    # that raised settles DISPATCH_UNKNOWN instead. Reserved rather than
    # removed, because reconciliation of an intent that was never claimed is a
    # legitimate FAILED -- the claim strictly precedes invocation.
    DISPATCH_FAILED = "dispatch_failed"
    # Dispatch began and the absence of an effect is not proven. Durable, and
    # deliberately not a claim that nothing happened: a later authoritative
    # observation can resolve it. This is what a raising tool used to record as
    # DISPATCH_FAILED, whose own docstring already admitted the state was
    # unknown (NEGATIVE_RESULTS section 48).
    DISPATCH_UNKNOWN = "dispatch_unknown"


_OUTCOME_STATUS.update({
    DispatchOutcome.SUCCEEDED: ItemStatus.EXECUTED,
    DispatchOutcome.REFUSED: ItemStatus.DISPATCH_REFUSED,
    DispatchOutcome.FAILED: ItemStatus.DISPATCH_FAILED,
    DispatchOutcome.UNKNOWN: ItemStatus.DISPATCH_UNKNOWN,
})


class ExecutionDecision(str, Enum):
    EXECUTE = "execute"
    APPROVAL_EXPIRED = "approval_expired"       # item returned to queue
    BINDING_REFUSED = "binding_refused"         # payload changed — refuse
    APPROVAL_INVALIDATED = "approval_invalidated"  # world got riskier — void


@dataclass(frozen=True)
class Approval:
    """A granted approval. ``expires_at`` is mandatory by construction."""

    item_id: str
    approved_action: DecisionAction
    approver: str
    issued_at: datetime
    expires_at: datetime
    tool_call_hash: str | None
    observation_hash: str


@dataclass
class PendingReview:
    item_id: str
    observation: PolicyObservation
    requested_action: DecisionAction
    enqueued_at: datetime
    queue_deadline: datetime
    status: ItemStatus = ItemStatus.PENDING
    approval: Approval | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    decision: ExecutionDecision
    fresh_action: DecisionAction | None
    detail: str


def _observation_hash(obs: PolicyObservation) -> str:
    """Stable content hash of the observation (audit correlation)."""
    import dataclasses
    import hashlib
    import json

    canonical = json.dumps(
        dataclasses.asdict(obs), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReviewQueue:
    """In-memory review queue enforcing TTL expiry and approval freshness."""

    def __init__(
        self,
        engine: RemoraDecisionEngine | None = None,
        sink: Callable[[ChainedEvent], None] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        default_queue_ttl: timedelta = DEFAULT_QUEUE_TTL,
        tenant_id: str = "default",
        revocation_store: RevocationStore | None = None,
    ) -> None:
        self._engine = engine or RemoraDecisionEngine()
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._default_queue_ttl = default_queue_ttl
        self._items: dict[str, PendingReview] = {}
        self._log = ChainedEventLog(sink=sink, now_fn=self._now_fn)
        # Serialises approve/execute/expire so a single approval cannot be
        # double-spent by concurrent execute() calls (non-atomic check-then-act).
        import threading
        self._lock = threading.RLock()
        # Principals whose authority was withdrawn after they acted. Checked
        # at the execution re-gate: an approval outlives its approver only
        # if nobody looks.
        #
        # This was a dict on the instance until the AGNTCY crosswalk review.
        # The server builds one queue per tenant per *process*, so a
        # revocation reached the worker that served the call and no other,
        # and did not survive a restart, while the chain recorded it either
        # way. The default below keeps that behaviour for library and test
        # use, and is exactly what a strict deployment must override.
        self._tenant_id = tenant_id
        self._revocations: RevocationStore = (
            revocation_store or InMemoryRevocationStore()
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def events(self) -> tuple[ChainedEvent, ...]:
        return self._log.events

    def verify_chain(self) -> tuple[bool, list[str]]:
        return self._log.verify()

    def item(self, item_id: str) -> PendingReview:
        return self._items[item_id]

    # ------------------------------------------------------------------
    # 1. Enqueue
    # ------------------------------------------------------------------

    def enqueue(
        self,
        observation: PolicyObservation,
        requested_action: DecisionAction,
        queue_ttl: timedelta | None = None,
    ) -> PendingReview:
        if requested_action not in (DecisionAction.VERIFY, DecisionAction.ESCALATE):
            raise ValueError(
                "only VERIFY and ESCALATE decisions await human review; got "
                f"{requested_action.value}"
            )
        now = self._now_fn()
        item = PendingReview(
            item_id=str(uuid.uuid4()),
            observation=observation,
            requested_action=requested_action,
            enqueued_at=now,
            queue_deadline=now + (queue_ttl or self._default_queue_ttl),
        )
        self._items[item.item_id] = item
        self._log.append(
            "review_enqueued",
            {
                "item_id": item.item_id,
                "requested_action": requested_action.value,
                "queue_deadline": item.queue_deadline.isoformat(),
                "tool_call_hash": observation.tool_call_hash,
            },
        )
        return item

    # ------------------------------------------------------------------
    # 2. Queue TTL (REM-032)
    # ------------------------------------------------------------------

    def expire_due(self, now: datetime | None = None) -> list[PendingReview]:
        """Resolve every overdue PENDING item to ABSTAIN, with an event each."""
        with self._lock:
            return self._expire_due_locked(now)

    def _expire_due_locked(self, now: datetime | None) -> list[PendingReview]:
        now = now or self._now_fn()
        expired: list[PendingReview] = []
        for item in self._items.values():
            if item.status is ItemStatus.PENDING and now >= item.queue_deadline:
                item.status = ItemStatus.EXPIRED_TO_ABSTAIN
                expired.append(item)
                self._log.append(
                    "review_expired_to_abstain",
                    {
                        "item_id": item.item_id,
                        "requested_action": item.requested_action.value,
                        "queue_deadline": item.queue_deadline.isoformat(),
                        "resolution": DecisionAction.ABSTAIN.value,
                    },
                )
        return expired

    # ------------------------------------------------------------------
    # 3. Approval (REM-033 — mandatory bounded expiry)
    # ------------------------------------------------------------------

    def reject(self, item_id: str, reviewer: str, reason: str) -> PendingReview:
        """Record a reviewer's explicit refusal. Terminal.

        Mirrors :meth:`approve` in its guards: only a PENDING item can be
        rejected, so a refusal can neither race an approval nor overwrite
        one. ``reason`` is mandatory — an unexplained refusal is not
        reviewable after the fact.
        """
        with self._lock:
            if not reason or not reason.strip():
                raise ValueError("a rejection must carry a reason")
            item = self._items[item_id]
            if item.status is not ItemStatus.PENDING:
                raise ValueError(
                    f"item {item_id} is {item.status.value}, not pending; "
                    "only a pending review can be rejected"
                )
            rejected = replace(item, status=ItemStatus.REJECTED)
            self._items[item_id] = rejected
            self._log.append(
                "review_rejected",
                {
                    "item_id": item_id,
                    "reviewer": reviewer,
                    "reason": reason,
                },
            )
            return rejected

    def revoke_principal(self, principal: str, *, reason: str = "") -> None:
        """Withdraw ``principal``'s authority for every pending execution.

        Approvals already granted are not rewritten. The execution re-gate
        refuses them instead, so the record shows an approval that was valid
        when issued and a revocation that arrived before dispatch.
        """
        if not principal or not principal.strip():
            raise ValueError("revoke_principal requires a principal")
        with self._lock:
            # Store first, chain second. If the store cannot record the
            # revocation the chain must not claim it happened: an audit
            # entry for an unenforced revocation is the defect this
            # ordering exists to prevent.
            self._revocations.revoke(
                principal, tenant_id=self._tenant_id, reason=reason
            )
            self._log.append(
                "principal_revoked", {"principal": principal, "reason": reason}
            )

    def is_revoked(self, principal: str | None) -> bool:
        """Whether ``principal`` is revoked in this queue's tenant.

        Propagates ``RevocationStoreUnavailable`` rather than answering
        False. A store that cannot answer must not be read as "not
        revoked", or an outage becomes a way around revocation.
        """
        if not principal:
            return False
        return self._revocations.is_revoked(principal, tenant_id=self._tenant_id)

    def approve(
        self,
        item_id: str,
        approver: str,
        approval_ttl: timedelta,
    ) -> Approval:
        with self._lock:
            return self._approve_locked(item_id, approver, approval_ttl)

    def _approve_locked(
        self,
        item_id: str,
        approver: str,
        approval_ttl: timedelta,
    ) -> Approval:
        if approval_ttl <= timedelta(0) or approval_ttl > MAX_APPROVAL_TTL:
            raise ValueError(
                "approval_ttl must be positive and at most "
                f"{MAX_APPROVAL_TTL} (got {approval_ttl}); "
                "no-expiry approvals are not supported (audit finding F-2)"
            )
        item = self._items[item_id]
        now = self._now_fn()
        if item.status is not ItemStatus.PENDING:
            raise ValueError(f"item {item_id} is {item.status.value}, not pending")
        if now >= item.queue_deadline:
            # Overdue items must expire, not be approved after the fact.
            self._expire_due_locked(now)
            raise ValueError(f"item {item_id} exceeded its queue TTL")
        approval = Approval(
            item_id=item_id,
            approved_action=item.requested_action,
            approver=approver,
            issued_at=now,
            expires_at=now + approval_ttl,
            tool_call_hash=item.observation.tool_call_hash,
            observation_hash=_observation_hash(item.observation),
        )
        item.status = ItemStatus.APPROVED
        item.approval = approval
        self._log.append(
            "approval_granted",
            {
                "item_id": item_id,
                "approver": approver,
                "approved_action": approval.approved_action.value,
                "expires_at": approval.expires_at.isoformat(),
            },
        )
        return approval

    # ------------------------------------------------------------------
    # 4. Execution re-gate (REM-033)
    # ------------------------------------------------------------------

    def execute(
        self,
        item_id: str,
        fresh_observation: PolicyObservation,
        now: datetime | None = None,
    ) -> ExecutionOutcome:
        with self._lock:
            return self._execute_locked(item_id, fresh_observation, now)

    def _execute_locked(
        self,
        item_id: str,
        fresh_observation: PolicyObservation,
        now: datetime | None,
    ) -> ExecutionOutcome:
        item = self._items[item_id]
        now = now or self._now_fn()
        if item.status is not ItemStatus.APPROVED or item.approval is None:
            raise ValueError(f"item {item_id} is {item.status.value}, not approved")
        approval = item.approval

        # 4a. Expired approval → back to the queue, never silent re-execution.
        if now >= approval.expires_at:
            item.status = ItemStatus.PENDING
            item.approval = None
            # Re-entering the queue must grant a FRESH review window: the
            # original deadline may itself have passed while approved, and a
            # stale deadline would immediately expire the item to ABSTAIN.
            old_deadline = item.queue_deadline
            item.enqueued_at = now
            item.queue_deadline = now + self._default_queue_ttl
            self._log.append(
                "approval_expired",
                {
                    "item_id": item_id,
                    "expired_at": approval.expires_at.isoformat(),
                    "old_queue_deadline": old_deadline.isoformat(),
                    "new_queue_deadline": item.queue_deadline.isoformat(),
                },
            )
            return ExecutionOutcome(
                ExecutionDecision.APPROVAL_EXPIRED,
                None,
                "approval expired; item returned to review queue",
            )

        # 4a'. Revoked approver: the approval was valid when issued and is
        # void now. Same decision as "world got riskier", because it did.
        # Reads the durable store. An unreachable store raises rather than
        # returning False, so the re-gate refuses instead of executing on an
        # answer it does not have.
        if self.is_revoked(approval.approver):
            item.status = ItemStatus.PENDING
            item.approval = None
            self._log.append(
                "approval_invalidated",
                {
                    "item_id": item_id,
                    "reason": "approver_revoked",
                    "approver": approval.approver,
                },
            )
            return ExecutionOutcome(
                ExecutionDecision.APPROVAL_INVALIDATED,
                None,
                "approver revoked after approval; item returned to review queue",
            )
        # 4b. Payload binding — the approval authorises exactly one payload.
        # A missing hash on either side is a refusal, never a match: two
        # hash-less observations must not bind (fail closed).
        if not approval.tool_call_hash or not fresh_observation.tool_call_hash:
            self._log.append(
                "binding_refused",
                {
                    "item_id": item_id,
                    "approved_hash": approval.tool_call_hash,
                    "presented_hash": fresh_observation.tool_call_hash,
                    "reason": "missing_tool_call_hash",
                },
            )
            return ExecutionOutcome(
                ExecutionDecision.BINDING_REFUSED,
                None,
                "tool-call hash missing on approval or presented payload",
            )
        if approval.tool_call_hash != fresh_observation.tool_call_hash:
            self._log.append(
                "binding_refused",
                {
                    "item_id": item_id,
                    "approved_hash": approval.tool_call_hash,
                    "presented_hash": fresh_observation.tool_call_hash,
                },
            )
            return ExecutionOutcome(
                ExecutionDecision.BINDING_REFUSED,
                None,
                "tool-call hash differs from the approved payload",
            )

        # 4c. Re-gate on the fresh observation: the approval survives only an
        # equal-or-safer world (decision monotonicity over time) AND only when
        # the fresh decision is itself an executable outcome. ABSTAIN and
        # ESCALATE never execute — a numerically-lower severity (e.g. approved
        # ESCALATE=3, fresh ABSTAIN=2) must NOT be read as "safe to run".
        fresh = self._engine.decide(fresh_observation)
        _EXECUTABLE = (DecisionAction.ACCEPT, DecisionAction.VERIFY)
        if (
            fresh.action in _EXECUTABLE
            and _SEVERITY[fresh.action] <= _SEVERITY[approval.approved_action]
        ):
            item.status = ItemStatus.AUTHORIZED
            self._log.append(
                "authorized",
                {
                    "item_id": item_id,
                    "approved_action": approval.approved_action.value,
                    "fresh_action": fresh.action.value,
                },
            )
            return ExecutionOutcome(
                ExecutionDecision.EXECUTE,
                fresh.action,
                "fresh decision is equal or safer; approval stands",
            )

        # World got riskier: void the approval, re-enter the queue with the
        # fresh (stricter) action.
        item.status = ItemStatus.PENDING
        item.approval = None
        item.requested_action = fresh.action
        item.observation = fresh_observation
        item.queue_deadline = now + self._default_queue_ttl
        self._log.append(
            "approval_invalidated",
            {
                "item_id": item_id,
                "approved_action": approval.approved_action.value,
                "fresh_action": fresh.action.value,
                "fresh_reasons": [r.value for r in fresh.reasons],
            },
        )
        return ExecutionOutcome(
            ExecutionDecision.APPROVAL_INVALIDATED,
            fresh.action,
            "fresh decision is stricter than the approval; approval voided "
            "and item re-queued",
        )

    # ------------------------------------------------------------------
    # 5. Execution outcome (external review 2026-07-27)
    # ------------------------------------------------------------------

    def record_execution_outcome(
        self,
        item_id: str,
        *,
        outcome: "DispatchOutcome",
        reason: str | None = None,
    ) -> PendingReview:
        """Record what actually happened after authorization.

        Takes the structured outcome rather than ``executed``/``failed``
        booleans. The previous signature could not express "dispatch began and
        we do not know", so a raising tool was recorded as DISPATCH_FAILED --
        a durable assertion that no effect occurred, on evidence that only
        showed the call raised.

        Only an AUTHORIZED item may receive an outcome.
        """
        with self._lock:
            item = self._items[item_id]
            if item.status is not ItemStatus.AUTHORIZED:
                raise ValueError(
                    f"item {item_id} is {item.status.value}, not authorized — "
                    "an execution outcome requires prior authorization"
                )
            item.status = _OUTCOME_STATUS[outcome]
            self._log.append(
                "execution_outcome",
                {
                    "item_id": item_id,
                    "status": item.status.value,
                    "reason": reason,
                },
            )
            return item
