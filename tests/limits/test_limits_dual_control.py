# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A limit's second tier: past ``dual_control_above``, a call needs two approvers.

The independent scenario S20 makes two +0.30 bar moves on the OT pilot's
PIC-101 within an hour. Each move is inside the hourly cap and approvable on
its own. A per-call check sees only 0.30 bar each time. Legitimate shifts make
the same sequence when delivery rises, so a hard cap low enough to refuse S20
also refuses them (NEGATIVE_RESULTS section 97). The tier keeps the hard cap
(``max``) and adds this rule: a call that takes the window's total past
``dual_control_above`` runs only on the authority of two distinct approvers.
The reservation at dispatch checks the tier in the same transaction as the
charge, against the approver count the signed lease carries.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from remora.enforcement import cumulative_limits as cl
from tests.limits.test_limits_unit import LIMITS, METERS, T0, policy

#: "move" is 2.0 degC per hour at scale 10; the tier is 1.0 degC.
DUAL_LIMITS = [dict(lim, dual_control_above=10) if lim["limit_id"] == "move" else lim
               for lim in LIMITS]


def _guard(tmp_path, *, limits=DUAL_LIMITS, meters=METERS, name="dual.db"):
    return cl.LimitGuard(policy(limits=limits, meters=meters), cl.LimitLedger(tmp_path / name))


def _reserve(guard, op, value, *, approvers=0, now=T0):
    return guard.reserve(tenant="t", principal="p", tool_name="move",
                         arguments={"unit": "AHU-1", "value": value}, operation_id=op,
                         request_hash=f"h-{op}", now=now, approvers=approvers)


def _move(guard, op, value, *, approvers=0, now=T0):
    """Reserve, begin and settle a move as the dispatcher would; the refusal or None."""
    refusal = _reserve(guard, op, value, approvers=approvers, now=now)
    if refusal is None:
        refusal = guard.begin(op)
    if refusal is None:
        guard.settle(op, True)
    return refusal


def _dual(guard, value, *, now=T0):
    return guard.dual_control(tenant="t", principal="p", tool_name="move",
                              arguments={"unit": "AHU-1", "value": value}, now=now)


# ── the policy ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [20, 21, -1, 1.5, "10", True])
def test_a_tier_at_or_above_max_or_not_a_whole_number_is_refused(bad):
    limits = [dict(LIMITS[1], dual_control_above=bad)]
    with pytest.raises(cl.LimitPolicyError):
        policy(limits=limits)


def test_the_tier_is_not_a_term_of_the_binding():
    """The tier decides who approves a charge, not what is charged."""
    plain = policy().limits[1]
    tiered = policy(limits=DUAL_LIMITS).limits[1]
    assert plain.dual_control_above is None and tiered.dual_control_above == 10
    import hashlib
    terms = "\x1f".join((cl.SCHEMA, "move", "t", "movement", "degC", "20", "3600", "*", "*"))
    assert plain.binding == tiered.binding == hashlib.sha256(terms.encode("utf-8")).hexdigest()


def test_adding_the_tier_keeps_the_ledgers_history_counting(tmp_path):
    """Adversarial review 2026-11-06: with the tier in the binding, a pilot with
    ledger history refused every later charge as limit_changed. The history
    under the untiered policy now counts under the tiered one."""
    before = _guard(tmp_path, limits=LIMITS, name="shared.db")
    assert _move(before, "1", 19.6) is None                      # 0.6 under the old policy
    after = _guard(tmp_path, name="shared.db")
    assert _reserve(after, "2", 20.2) == cl.DUAL_CONTROL_UNMET    # 1.2 counted, not changed
    assert _move(after, "2", 20.2, approvers=2) is None
    assert _reserve(after, "3", 21.2, approvers=2) == cl.EXCEEDED


# ── the reservation ──────────────────────────────────────────────────────────


def test_s20_shape_the_second_half_move_needs_two_approvers(tmp_path):
    guard = _guard(tmp_path)
    assert _move(guard, "1", 19.6) is None                       # 0.6 of 1.0: one approver
    assert _reserve(guard, "2", 20.2) == cl.DUAL_CONTROL_UNMET   # 1.2 > 1.0
    assert _reserve(guard, "2", 20.2, approvers=1) == cl.DUAL_CONTROL_UNMET
    assert _move(guard, "2", 20.2, approvers=2) is None          # two approvers: it runs
    # The hard cap still refuses, whatever the approvals.
    assert _reserve(guard, "3", 21.2, approvers=5) == cl.EXCEEDED


def test_a_total_exactly_at_the_tier_needs_no_second_approver(tmp_path):
    guard = _guard(tmp_path)
    assert _move(guard, "1", 19.5) is None
    assert _move(guard, "2", 20.0) is None                       # exactly 1.0


def test_a_single_move_past_the_tier_needs_two_approvers_too(tmp_path):
    guard = _guard(tmp_path)
    assert _reserve(guard, "1", 20.5) == cl.DUAL_CONTROL_UNMET   # 1.5 in one move
    assert _move(guard, "1", 20.5, approvers=2) is None


def test_every_further_move_while_the_window_is_past_the_tier_needs_two(tmp_path):
    guard = _guard(tmp_path)
    assert _move(guard, "1", 20.5, approvers=2) is None
    assert _reserve(guard, "2", 20.6) == cl.DUAL_CONTROL_UNMET
    # An hour later the first move has left the window.
    assert _move(guard, "2", 20.6, now=T0 + 3601) is None


def test_a_refusal_for_the_tier_reserves_nothing_and_leaves_the_resource_open(tmp_path):
    guard = _guard(tmp_path)
    assert _reserve(guard, "1", 20.5) == cl.DUAL_CONTROL_UNMET
    with sqlite3.connect(tmp_path / "dual.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM limit_reservation").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM limit_operation").fetchone() == (0,)
    # Not RESOURCE_BUSY: nothing was left pending.
    assert _move(guard, "2", 19.4) is None


def test_a_move_to_a_safe_value_needs_no_second_approver_past_the_tier(tmp_path):
    meters = {**METERS, "move": [dict(METERS["move"][0], safe_values={"AHU-1": 15.0})]}
    guard = _guard(tmp_path, meters=meters)
    assert _move(guard, "1", 20.5, approvers=2) is None          # 1.5 of 2.0, past the tier
    assert _move(guard, "2", 15.0) is None                       # the stop: charged 0


def test_a_retry_of_a_reserved_operation_is_not_checked_again(tmp_path):
    guard = _guard(tmp_path)
    assert _reserve(guard, "1", 20.5, approvers=2) is None
    # The same lease after a crash between reservation and nonce use.
    assert _reserve(guard, "1", 20.5, approvers=2) is None


def test_a_policy_without_the_tier_ignores_approvers(tmp_path):
    guard = _guard(tmp_path, limits=LIMITS)
    assert _move(guard, "1", 20.5) is None
    assert _dual(guard, 20.6) == ()


# ── the preview at assess ────────────────────────────────────────────────────


def test_the_preview_does_not_refuse_for_the_tier_and_dual_control_names_the_limit(tmp_path):
    guard = _guard(tmp_path)
    assert _move(guard, "1", 19.6) is None
    args = {"unit": "AHU-1", "value": 20.2}
    assert guard.preview(tenant="t", principal="p", tool_name="move", arguments=args,
                         now=T0) is None
    assert _dual(guard, 20.2) == ("move",)
    assert _dual(guard, 19.9) == ()
    # A call refused for another reason names no tier: the preview names the refusal.
    assert _dual(guard, 22.0) == ()
    assert guard.preview(tenant="t", principal="p", tool_name="move",
                         arguments={"unit": "AHU-1", "value": 22.0}, now=T0) == cl.EXCEEDED


def test_the_preview_reserves_nothing(tmp_path):
    guard = _guard(tmp_path)
    for _ in range(3):
        assert _dual(guard, 20.5) == ("move",)
    assert _move(guard, "1", 20.5, approvers=2) is None


# ── the dispatcher passes the count the signed lease carries ─────────────────


def _dispatcher(guard):
    from remora.enforcement.lease import GovernedToolDispatcher

    d = GovernedToolDispatcher(expected_policy_bundle_hash="b" * 64)
    d.bind_limit_guard(guard)
    return d


def _lease(nonce, approver_count=0, signed=True):
    return SimpleNamespace(tenant_id="t", actor_identity="p", nonce=nonce, expires_at=None,
                           tool_args_hash="h" * 64, proposal_id="prop",
                           approver_count=approver_count, is_signed=signed)


def test_the_dispatcher_reserves_with_the_leases_approver_count(tmp_path):
    guard = _guard(tmp_path)
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 20.5}
    assert d._limit_refusal(_lease("n1"), "move", args, args, None) == cl.DUAL_CONTROL_UNMET
    assert d._limit_refusal(_lease("n2", 2), "move", args, args, None) is None


def test_an_unsigned_lease_counts_no_approvers(tmp_path):
    guard = _guard(tmp_path)
    d = _dispatcher(guard)
    args = {"unit": "AHU-1", "value": 20.5}
    assert d._limit_refusal(_lease("n1", 2, signed=False), "move", args, args,
                            None) == cl.DUAL_CONTROL_UNMET


@pytest.fixture()
def signing(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "dual-control-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _issue(approver_count=0):
    from remora.enforcement.lease import ExecutionLease

    return ExecutionLease.issue(
        decision="accept", tenant_id="t", actor_identity="p", tool_name="move",
        arguments={"unit": "AHU-1", "value": 20.5}, target_environment="prod",
        policy_bundle_hash="b1", issued_at="2027-01-15T10:00:00+00:00",
        expires_at="2027-01-15T10:05:00+00:00", proposal_id="prop", grant_jti="jti",
        approver_count=approver_count)


def _verify(lease):
    return lease.verify(tool_name="move", arguments={"unit": "AHU-1", "value": 20.5},
                        tenant_id="t", target_environment="prod", actor_identity="p",
                        now="2027-01-15T10:01:00+00:00")


def test_the_count_is_signed_and_a_changed_count_fails_the_signature(signing):
    from dataclasses import replace

    lease = _issue(approver_count=2)
    assert lease.approver_count == 2 and "approver_count" in lease.to_dict()
    assert _verify(lease).verified
    assert not _verify(replace(lease, approver_count=3)).verified
    # Added to a lease issued for one approver, it is not covered either.
    assert not _verify(replace(_issue(), approver_count=2)).verified


def test_one_approver_is_not_signed_and_a_count_of_one_is_refused(signing):
    from dataclasses import replace

    one = _issue(approver_count=1)
    assert one.approver_count == 0 and "approver_count" not in one.to_dict()
    assert _verify(one).verified
    # The signature does not cover the added count, so it fails there first.
    assert not _verify(replace(one, approver_count=1)).verified
    # Signed with a count of one, which issue() never does: malformed.
    from tests.test_lease_verification_completeness import _resigned

    assert _verify(_resigned(one, approver_count=1)).reason == "approver_count_malformed"


@pytest.mark.parametrize("bad", [-1, True, 2.0])
def test_a_count_that_is_not_a_whole_number_is_not_issued(signing, bad):
    with pytest.raises(ValueError):
        _issue(approver_count=bad)


def test_a_dual_control_lease_round_trips_through_its_dict(signing):
    from remora.enforcement.lease import ExecutionLease

    lease = _issue(approver_count=2)
    again = ExecutionLease.from_dict(lease.to_dict())
    assert again.approver_count == 2 and _verify(again).verified
