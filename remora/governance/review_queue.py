# Author: Stian Skogbrott
# License: Apache-2.0
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

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable

from remora.governance.degradation import ChainedEvent, ChainedEventLog
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


class ItemStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXPIRED_TO_ABSTAIN = "expired_to_abstain"
    EXECUTED = "executed"


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
    ) -> None:
        self._engine = engine or RemoraDecisionEngine()
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._default_queue_ttl = default_queue_ttl
        self._items: dict[str, PendingReview] = {}
        self._log = ChainedEventLog(sink=sink, now_fn=self._now_fn)

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

    def approve(
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
            self.expire_due(now)
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
        item = self._items[item_id]
        now = now or self._now_fn()
        if item.status is not ItemStatus.APPROVED or item.approval is None:
            raise ValueError(f"item {item_id} is {item.status.value}, not approved")
        approval = item.approval

        # 4a. Expired approval → back to the queue, never silent re-execution.
        if now >= approval.expires_at:
            item.status = ItemStatus.PENDING
            item.approval = None
            self._log.append(
                "approval_expired",
                {"item_id": item_id, "expired_at": approval.expires_at.isoformat()},
            )
            return ExecutionOutcome(
                ExecutionDecision.APPROVAL_EXPIRED,
                None,
                "approval expired; item returned to review queue",
            )

        # 4b. Payload binding — the approval authorises exactly one payload.
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
        # equal-or-safer world (decision monotonicity over time).
        fresh = self._engine.decide(fresh_observation)
        if _SEVERITY[fresh.action] <= _SEVERITY[approval.approved_action]:
            item.status = ItemStatus.EXECUTED
            self._log.append(
                "executed",
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
