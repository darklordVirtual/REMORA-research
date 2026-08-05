# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Property-based invariant testing of the review-queue TTL contract.

The documented claim (resilience plan, REM-032): an overdue PENDING item
resolves to ABSTAIN — never auto-accept, never indefinite silent pending.
These properties search integer-hour TTL/advance combinations on the
public in-memory surface — NOT SQLite/Postgres adapters, concurrent
approvers, or crash boundaries: one sweep expires exactly the overdue
items, never a non-overdue one, and an expired item is never approvable
afterwards within the generated domain (proof-depth track, slice 3).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.governance.review_queue import ItemStatus, ReviewQueue
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _queue_with_clock():
    clock = {"now": T0}
    queue = ReviewQueue(now_fn=lambda: clock["now"])
    return queue, clock


@settings(max_examples=60, deadline=None)
@given(st.lists(st.integers(min_value=1, max_value=72), min_size=1, max_size=8),
       st.integers(min_value=0, max_value=100))
def test_sweep_expires_exactly_the_overdue_items(ttl_hours, advance_hours) -> None:
    queue, clock = _queue_with_clock()
    obs = PolicyObservation(question="prop: queued action")
    items = [(queue.enqueue(obs, DecisionAction.VERIFY,
                            queue_ttl=timedelta(hours=ttl)), ttl)
             for ttl in ttl_hours]

    clock["now"] = T0 + timedelta(hours=advance_hours)
    queue.expire_due()

    for item, ttl in items:
        if ttl <= advance_hours:  # deadline reached (expiry is `now >= deadline`)
            assert item.status is ItemStatus.EXPIRED_TO_ABSTAIN, (
                f"ttl={ttl}h not expired after {advance_hours}h")
        else:
            assert item.status is ItemStatus.PENDING, (
                f"ttl={ttl}h wrongly expired after {advance_hours}h")


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=1, max_value=72), st.integers(min_value=0, max_value=100))
def test_expired_items_can_never_be_approved(ttl, advance) -> None:
    queue, clock = _queue_with_clock()
    obs = PolicyObservation(question="prop: queued action")
    item = queue.enqueue(obs, DecisionAction.VERIFY, queue_ttl=timedelta(hours=ttl))

    clock["now"] = T0 + timedelta(hours=advance)
    if ttl <= advance:
        with pytest.raises((KeyError, ValueError)):
            queue.approve(item.item_id, approver="reviewer-1",
                          approval_ttl=timedelta(minutes=15))
        assert item.status is ItemStatus.EXPIRED_TO_ABSTAIN
    else:
        approval = queue.approve(item.item_id, approver="reviewer-1",
                                 approval_ttl=timedelta(minutes=15))
        assert approval.item_id == item.item_id
