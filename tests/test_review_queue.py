# Author: Stian Skogbrott
# License: Apache-2.0
"""REM-033 acceptance tests: review-queue TTL → ABSTAIN (REM-032 §2) and the
approval freshness contract (mandatory bounded expiry, execution-time
re-gate with monotone severity, recorded invalidation events)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from remora.governance.review_queue import (
    MAX_APPROVAL_TTL,
    ExecutionDecision,
    ItemStatus,
    ReviewQueue,
)
from remora.policy.observation import PolicyObservation, canonical_tool_call_hash
from remora.policy.report import DecisionAction

T0 = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def _obs(**overrides) -> PolicyObservation:
    """A high-risk production write whose engine decision is VERIFY."""
    tool_args = overrides.pop("tool_args", {"order": "WO-1", "action": "reschedule"})
    defaults = dict(
        question="update_work_order(order=WO-1)",
        risk_tier="high",
        action_type="production_write",
        target_environment="prod",
        schema_valid=True,
        trust_score=0.86,
        phase="ordered",
        evidence_action="verify",
        evidence_confidence=0.8,
        rollback_available=True,
        tool_call_hash=canonical_tool_call_hash(
            name="update_work_order", arguments=tool_args, target="prod"
        ),
    )
    defaults.update(overrides)
    return PolicyObservation(**defaults)


def _queue() -> tuple[ReviewQueue, _Clock]:
    clock = _Clock()
    return ReviewQueue(now_fn=clock), clock


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def test_only_verify_and_escalate_enter_the_queue() -> None:
    queue, _ = _queue()
    queue.enqueue(_obs(), DecisionAction.VERIFY)
    queue.enqueue(_obs(), DecisionAction.ESCALATE)
    for action in (DecisionAction.ACCEPT, DecisionAction.ABSTAIN):
        with pytest.raises(ValueError):
            queue.enqueue(_obs(), action)


# ---------------------------------------------------------------------------
# Queue TTL (REM-032): unattended items expire to ABSTAIN, recorded
# ---------------------------------------------------------------------------

def test_unattended_item_expires_to_abstain_with_recorded_event() -> None:
    queue, clock = _queue()
    item = queue.enqueue(_obs(), DecisionAction.VERIFY, queue_ttl=timedelta(hours=1))
    assert queue.expire_due() == []          # not yet due
    clock.advance(hours=2)
    expired = queue.expire_due()
    assert [e.item_id for e in expired] == [item.item_id]
    assert item.status is ItemStatus.EXPIRED_TO_ABSTAIN
    kinds = [e.kind for e in queue.events]
    assert kinds == ["review_enqueued", "review_expired_to_abstain"]
    assert queue.events[-1].payload["resolution"] == "abstain"


def test_expired_item_cannot_be_approved() -> None:
    queue, clock = _queue()
    item = queue.enqueue(_obs(), DecisionAction.VERIFY, queue_ttl=timedelta(hours=1))
    clock.advance(hours=2)
    with pytest.raises(ValueError, match="queue TTL"):
        queue.approve(item.item_id, approver="ops@example", approval_ttl=timedelta(minutes=15))
    assert item.status is ItemStatus.EXPIRED_TO_ABSTAIN


# ---------------------------------------------------------------------------
# Approval (REM-033): expiry is mandatory and bounded — F-2 closed
# ---------------------------------------------------------------------------

def test_approval_ttl_is_mandatory_and_bounded() -> None:
    queue, _ = _queue()
    item = queue.enqueue(_obs(), DecisionAction.VERIFY)
    for bad_ttl in (timedelta(0), timedelta(seconds=-1), MAX_APPROVAL_TTL + timedelta(seconds=1)):
        with pytest.raises(ValueError, match="F-2"):
            queue.approve(item.item_id, approver="ops", approval_ttl=bad_ttl)
    approval = queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    assert approval.expires_at == T0 + timedelta(minutes=15)
    assert queue.events[-1].kind == "approval_granted"


# ---------------------------------------------------------------------------
# Execution re-gate (REM-033)
# ---------------------------------------------------------------------------

def test_fresh_equal_decision_executes() -> None:
    queue, _ = _queue()
    obs = _obs()
    item = queue.enqueue(obs, DecisionAction.VERIFY)
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    outcome = queue.execute(item.item_id, obs)   # unchanged world → VERIFY again
    assert outcome.decision is ExecutionDecision.EXECUTE
    assert item.status is ItemStatus.EXECUTED
    assert queue.events[-1].kind == "executed"


def test_fresh_stricter_decision_voids_the_approval() -> None:
    queue, _ = _queue()
    obs = _obs()
    item = queue.enqueue(obs, DecisionAction.VERIFY)
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    # World got riskier while pending: evidence now contradicts the plan.
    # Same payload (same tool_call_hash), new world state.
    riskier = _obs(evidence_contradictions=1, contradiction_cycles=1)
    outcome = queue.execute(item.item_id, riskier)
    assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED
    assert outcome.fresh_action is DecisionAction.ESCALATE
    assert item.status is ItemStatus.PENDING          # re-queued
    assert item.requested_action is DecisionAction.ESCALATE
    assert item.approval is None
    assert queue.events[-1].kind == "approval_invalidated"
    assert queue.events[-1].payload["fresh_action"] == "escalate"


def test_expired_approval_returns_item_to_queue() -> None:
    queue, clock = _queue()
    obs = _obs()
    item = queue.enqueue(obs, DecisionAction.VERIFY, queue_ttl=timedelta(hours=8))
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    clock.advance(minutes=30)
    outcome = queue.execute(item.item_id, obs)
    assert outcome.decision is ExecutionDecision.APPROVAL_EXPIRED
    assert item.status is ItemStatus.PENDING
    assert item.approval is None
    assert queue.events[-1].kind == "approval_expired"


def test_changed_payload_is_refused_by_binding() -> None:
    queue, _ = _queue()
    obs = _obs()
    item = queue.enqueue(obs, DecisionAction.VERIFY)
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    # Same tool, DIFFERENT arguments → different canonical hash.
    swapped = _obs(tool_args={"order": "WO-999", "action": "cancel"})
    outcome = queue.execute(item.item_id, swapped)
    assert outcome.decision is ExecutionDecision.BINDING_REFUSED
    assert queue.events[-1].kind == "binding_refused"
    # The approval itself still stands for the ORIGINAL payload.
    assert queue.execute(item.item_id, obs).decision is ExecutionDecision.EXECUTE


def test_missing_tool_call_hash_refuses_binding_fail_closed() -> None:
    """Two hashless observations must never satisfy the payload binding.

    Regression (2026-07-20 review): `approval.tool_call_hash ==
    fresh.tool_call_hash` held when BOTH were None, so an approval created
    from a hash-less observation would bind to ANY hash-less payload —
    a fail-open edge in an otherwise fail-closed contract.
    """
    queue, _ = _queue()
    item = queue.enqueue(_obs(tool_call_hash=None), DecisionAction.VERIFY)
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    outcome = queue.execute(item.item_id, _obs(tool_call_hash=None))
    assert outcome.decision is ExecutionDecision.BINDING_REFUSED
    assert queue.events[-1].kind == "binding_refused"
    assert queue.events[-1].payload.get("reason") == "missing_tool_call_hash"


def test_executing_unapproved_item_raises() -> None:
    queue, _ = _queue()
    item = queue.enqueue(_obs(), DecisionAction.VERIFY)
    with pytest.raises(ValueError, match="not approved"):
        queue.execute(item.item_id, _obs())


# ---------------------------------------------------------------------------
# Event log integrity
# ---------------------------------------------------------------------------

def test_full_lifecycle_event_chain_verifies() -> None:
    queue, clock = _queue()
    obs = _obs()
    item = queue.enqueue(obs, DecisionAction.VERIFY)
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    queue.execute(item.item_id, _obs(evidence_contradictions=1, contradiction_cycles=1))
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    clock.advance(minutes=30)
    queue.execute(item.item_id, obs)
    ok, problems = queue.verify_chain()
    assert ok, problems
    assert [e.kind for e in queue.events] == [
        "review_enqueued",
        "approval_granted",
        "approval_invalidated",
        "approval_granted",
        "approval_expired",
    ]


def test_approved_escalate_with_fresh_abstain_does_not_execute() -> None:
    """Review finding (fail-open): approved ESCALATE + fresh ABSTAIN has
    severity 2<=3 but ABSTAIN must NEVER execute."""
    queue, _ = _queue()
    # Enqueue an ESCALATE item (contradiction forces ESCALATE).
    obs = _obs(evidence_contradictions=1, contradiction_cycles=1)
    item = queue.enqueue(obs, DecisionAction.ESCALATE)
    queue.approve(item.item_id, approver="senior", approval_ttl=timedelta(minutes=15))
    # Fresh world: contradiction resolved but only to ABSTAIN (not executable).
    fresh_abstain = _obs(evidence_contradictions=2)  # ABSTAIN, no cycles
    outcome = queue.execute(item.item_id, fresh_abstain)
    assert outcome.decision is not ExecutionDecision.EXECUTE
    assert item.status is not ItemStatus.EXECUTED


def test_concurrent_execute_double_spend_is_prevented() -> None:
    """Review finding: one approval must not yield two execution grants."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    queue, _ = _queue()
    obs = _obs()
    item = queue.enqueue(obs, DecisionAction.VERIFY)
    queue.approve(item.item_id, approver="ops", approval_ttl=timedelta(minutes=15))
    barrier = threading.Barrier(8)
    outcomes = []

    def race() -> None:
        barrier.wait(timeout=10)
        try:
            outcomes.append(queue.execute(item.item_id, obs).decision)
        except ValueError:
            outcomes.append("not_approved")  # lost the race → already executed

    with ThreadPoolExecutor(max_workers=8) as pool:
        for f in [pool.submit(race) for _ in range(8)]:
            f.result(timeout=30)
    executes = [o for o in outcomes if o is ExecutionDecision.EXECUTE]
    assert len(executes) == 1  # exactly one grant, never two
