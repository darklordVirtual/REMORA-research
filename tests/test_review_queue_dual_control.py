# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Dual control in the review queue: an item that needs two distinct approvers.

A call past a cumulative limit's ``dual_control_above`` is enqueued with
``required_approvers=2``. The item is APPROVED only once two different people
approved it, each inside their own approval's lifetime. The standing approval
expires with the first of them. A revocation of either voids it. Execution of
an item still awaiting its second approver is refused by name. Whatever voids
the approval also clears the approvals towards the quorum, so a later
approval starts over.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from remora.governance.review_queue import (
    DUAL_CONTROL_PENDING,
    ApproverAlreadyApproved,
    DualControlPending,
    ExecutionDecision,
    ItemStatus,
    PendingReview,
    approver_count,
)
from remora.persistence.execution_state import from_dict, to_dict
from remora.policy.report import DecisionAction
from tests.test_review_queue import _obs, _queue

TTL = timedelta(minutes=10)


def _dual(queue):
    return queue.enqueue(_obs(), DecisionAction.VERIFY, required_approvers=2)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_required_approvers_is_a_positive_whole_number(bad):
    queue, _ = _queue()
    with pytest.raises(ValueError):
        queue.enqueue(_obs(), DecisionAction.VERIFY, required_approvers=bad)


def test_one_approval_is_recorded_and_the_item_stays_pending():
    queue, _ = _queue()
    item = _dual(queue)
    queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    assert item.status is ItemStatus.PENDING and item.approval is None
    assert [a.approver for a in item.approvals] == ["a"]
    assert approver_count(item) == 0
    event = queue.events[-1]
    assert event.kind == "approval_recorded"
    assert (event.payload["approvals_received"], event.payload["approvals_required"]) == (1, 2)


def test_the_same_approver_twice_is_not_two_approvers():
    queue, _ = _queue()
    item = _dual(queue)
    queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    with pytest.raises(ApproverAlreadyApproved):
        queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    assert item.status is ItemStatus.PENDING and len(item.approvals) == 1


def test_a_second_distinct_approver_approves_and_the_first_expiry_bounds_it():
    queue, clock = _queue()
    item = _dual(queue)
    first = queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    clock.advance(minutes=3)
    queue.approve(item.item_id, approver="b", approval_ttl=TTL)
    assert item.status is ItemStatus.APPROVED
    assert item.approval.expires_at == first.expires_at        # the earlier of the two
    assert approver_count(item) == 2
    granted = queue.events[-1]
    assert granted.kind == "approval_granted" and granted.payload["approvers"] == ["a", "b"]


def test_a_lapsed_first_approval_does_not_count_towards_the_quorum():
    queue, clock = _queue()
    item = _dual(queue)
    queue.approve(item.item_id, approver="a", approval_ttl=timedelta(minutes=1))
    clock.advance(minutes=2)
    queue.approve(item.item_id, approver="b", approval_ttl=TTL)
    assert item.status is ItemStatus.PENDING
    assert [a.approver for a in item.approvals] == ["b"]
    # The lapsed approver may approve again; with b's it makes two.
    queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    assert item.status is ItemStatus.APPROVED


def test_executing_an_item_awaiting_its_second_approver_is_refused_by_name():
    queue, _ = _queue()
    item = _dual(queue)
    queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    with pytest.raises(DualControlPending) as raised:
        queue.execute(item.item_id, _obs())
    assert raised.value.reason == DUAL_CONTROL_PENDING
    assert item.status is ItemStatus.PENDING


def test_two_approvals_execute():
    queue, _ = _queue()
    item = _dual(queue)
    for who in ("a", "b"):
        queue.approve(item.item_id, approver=who, approval_ttl=TTL)
    assert queue.execute(item.item_id, _obs()).decision is ExecutionDecision.EXECUTE
    assert item.status is ItemStatus.AUTHORIZED and approver_count(item) == 2


@pytest.mark.parametrize("revoked", ["a", "b"])
def test_revoking_either_approver_voids_the_approval_and_clears_the_quorum(revoked):
    queue, _ = _queue()
    item = _dual(queue)
    for who in ("a", "b"):
        queue.approve(item.item_id, approver=who, approval_ttl=TTL)
    queue.revoke_principal(revoked)
    outcome = queue.execute(item.item_id, _obs())
    assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED
    assert item.status is ItemStatus.PENDING and item.approvals == ()
    assert queue.events[-1].payload["approver"] == revoked


def test_revoking_either_approver_after_authorisation_stops_the_async_dispatch():
    queue, _ = _queue()
    item = _dual(queue)
    for who in ("a", "b"):
        queue.approve(item.item_id, approver=who, approval_ttl=TTL)
    assert queue.execute(item.item_id, _obs()).decision is ExecutionDecision.EXECUTE
    queue.revoke_principal("a")
    assert queue.regate_authorized(item.item_id, _obs()).decision is \
        ExecutionDecision.APPROVAL_INVALIDATED


def test_an_expired_quorum_returns_the_item_with_no_approvals_left():
    queue, clock = _queue()
    item = _dual(queue)
    for who in ("a", "b"):
        queue.approve(item.item_id, approver=who, approval_ttl=TTL)
    clock.advance(minutes=11)
    assert queue.execute(item.item_id, _obs()).decision is ExecutionDecision.APPROVAL_EXPIRED
    assert item.status is ItemStatus.PENDING and item.approvals == ()
    queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    assert item.status is ItemStatus.PENDING                    # starts over: one of two


def test_a_single_approver_item_is_unchanged():
    queue, _ = _queue()
    item = queue.enqueue(_obs(), DecisionAction.VERIFY)
    assert item.required_approvers == 1
    queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    assert item.status is ItemStatus.APPROVED and item.approvals == ()
    assert approver_count(item) == 1
    assert "approvers" not in queue.events[-1].payload
    assert "required_approvers" not in queue.events[0].payload


def test_the_quorum_survives_persistence():
    queue, _ = _queue()
    item = _dual(queue)
    queue.approve(item.item_id, approver="a", approval_ttl=TTL)
    again = from_dict(to_dict(item), PendingReview)
    assert again.required_approvers == 2
    assert again.approvals == item.approvals
    queue.approve(item.item_id, approver="b", approval_ttl=TTL)
    again = from_dict(to_dict(item), PendingReview)
    assert again.status is ItemStatus.APPROVED and approver_count(again) == 2
    # An item persisted before dual control existed loads as single-approver.
    legacy = to_dict(queue.enqueue(_obs(), DecisionAction.VERIFY))
    legacy.pop("required_approvers")
    legacy.pop("approvals")
    old = from_dict(legacy, PendingReview)
    assert (old.required_approvers, old.approvals) == (1, ())


def test_approvals_under_different_approval_policies_do_not_make_a_quorum():
    """Adversarial review 2026-11-06: an approval admitted under an older
    requirement counted towards the two."""
    queue, _ = _queue()
    item = _dual(queue)
    queue.approve(item.item_id, approver="a", approval_ttl=TTL, approval_policy_hash="P_OLD")
    queue.approve(item.item_id, approver="b", approval_ttl=TTL, approval_policy_hash="P_NEW")
    assert item.status is ItemStatus.PENDING
    assert [a.approver for a in item.approvals] == ["b"]


def test_every_approval_in_the_quorum_is_checked_against_the_policy_in_force():
    queue, _ = _queue()
    item = _dual(queue)
    for who in ("a", "b"):
        queue.approve(item.item_id, approver=who, approval_ttl=TTL, approval_policy_hash="P_OLD")
    # Only the first approval carries a stale requirement here; it still voids.
    item.approvals = (item.approvals[0], replace(item.approvals[1], approval_policy_hash="P_NEW"))
    item.approval = replace(item.approval, approval_policy_hash="P_NEW")
    outcome = queue.execute(item.item_id, _obs(), approval_policy_hash="P_NEW")
    assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED
    assert item.approvals == ()
