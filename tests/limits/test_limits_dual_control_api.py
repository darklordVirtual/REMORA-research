# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Dual control through the execution API, on the OT pilot's own registry and bundle.

The pilot's PIC-101 limit is 1.60 bar per hour, with a second tier at 0.50 bar
(``dual_control_above``). These tests run S20's sequence through
assess, approve and execute. Each of the two +0.30 bar moves is approvable.
The second takes the hour past the tier, so it needs two distinct approvers:
with one, it does not run; with two, it does. The tier is checked again at
dispatch, in the reservation's transaction, so a total that grew between
approval and dispatch refuses an item approved by one person.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tests.limits.test_limits_ot_pilot import payload, pilot, shipped_policy  # noqa: E402,F401

PIC = "pic-101-movement"


def _tiered_policy():
    body = shipped_policy()
    for lim in body["limits"]:
        if lim["limit_id"] == PIC:
            lim["dual_control_above"] = 50
    return body


@pytest.fixture()
def dual(pilot, monkeypatch):  # noqa: F811 - the imported fixture
    from remora.crypto import SignatureDomain, SigningKey
    from remora.enforcement.cumulative_limits import sign_policy

    key = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    client = pilot(sign_policy(_tiered_policy(), key, "2026-11-06T00:00:00Z"),
                   trusted_key=key.verification_key().public_bytes.hex())
    import servers.api as api_mod

    # Who acts comes from a header here, so two approvers can be told apart.
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: request.headers.get("x-test-principal", "agent-1"))
    return client


def _as(name):
    return {"x-test-principal": name}


def _assess(client, p):
    r = client.post("/v1/execution/assess", json=p, headers=_as("agent-1"))
    assert r.status_code == 200, r.text
    return r.json()


def _approve(client, item, who):
    return client.post("/v1/execution/approve", headers=_as(who),
                       json={"item_id": item, "approval_ttl_seconds": 600})


def _execute(client, item, p):
    return client.post("/v1/execution/execute", headers=_as("agent-1"),
                       json={"item_id": item, "tool_call": p})


def _executed(response):
    return (response.json().get("tool_execution") or {}).get("executed")


def _move(value):
    return payload("adjust_setpoint", "WO-1201", loop="PIC-101", value=value)


def _setpoint():
    import ot_registry

    return ot_registry.PLANT["loops"]["PIC-101"]["setpoint"]


def _events(name):
    import servers.execution_api as exec_mod

    return [e.payload for e in exec_mod._CHAIN.entries("ot-pilot")
            if e.payload.get("event") == name]


def test_s20_the_second_half_move_needs_a_second_approver_and_then_runs(dual):
    first = _assess(dual, _move(4.3))
    assert "approvals_required" not in first and "dual_control" not in first
    assert _approve(dual, first["review_item_id"], "approver-1").json()["status"] == "approved"
    assert _executed(_execute(dual, first["review_item_id"], _move(4.3))) is True

    second = _assess(dual, _move(4.6))                     # 0.6 bar this hour, past 0.5
    assert second["decision"] == "verify"
    assert second["approvals_required"] == 2
    assert second["dual_control"] == {"reason": "limit_dual_control_required", "limits": [PIC]}
    item = second["review_item_id"]

    one = _approve(dual, item, "approver-1").json()
    assert (one["status"], one["approvals_received"], one["approvals_required"]) == (
        "approval_recorded", 1, 2)
    refused = _execute(dual, item, _move(4.6))
    assert (refused.status_code, refused.json()["detail"]) == (
        409, "dual_control_second_approval_required")
    assert _setpoint() == 4.3

    again = _approve(dual, item, "approver-1")
    assert (again.status_code, again.json()["detail"]) == (409, "approver_already_approved")

    two = _approve(dual, item, "approver-2").json()
    assert (two["status"], two["approvals_received"]) == ("approved", 2)
    assert _executed(_execute(dual, item, _move(4.6))) is True
    assert _setpoint() == 4.6

    [assessed] = [e for e in _events("assessed") if e.get("review_item_id") == item]
    assert assessed["dual_control"] == {"reason": "limit_dual_control_required",
                                        "limits": [PIC], "approvals_required": 2}
    [recorded] = [e for e in _events("approval_recorded") if e["item_id"] == item]
    assert (recorded["actor"], recorded["approvals_received"]) == ("approver-1", 1)
    [approved] = [e for e in _events("approved") if e["item_id"] == item]
    assert approved["approvers"] == ["approver-1", "approver-2"]


def test_with_one_approver_the_second_half_move_never_runs(dual):
    """S20 as the scenario runs it: one approver role, so no second approval."""
    first = _assess(dual, _move(4.3))
    _approve(dual, first["review_item_id"], "approver-1")
    assert _executed(_execute(dual, first["review_item_id"], _move(4.3))) is True
    second = _assess(dual, _move(4.6))
    _approve(dual, second["review_item_id"], "approver-1")
    refused = _execute(dual, second["review_item_id"], _move(4.6))
    assert (refused.status_code, refused.json()["detail"]) == (
        409, "dual_control_second_approval_required")
    assert _setpoint() == 4.3


def test_the_proposer_is_never_one_of_the_two(dual):
    """Adversarial review 2026-11-06: outside production the proposer could
    approve its own call, so one human and the agent made two."""
    first = _assess(dual, _move(4.8))
    item = first["review_item_id"]
    own = _approve(dual, item, "agent-1")
    assert (own.status_code, own.json()["detail"]) == (403, "approver_is_proposer")
    assert _approve(dual, item, "approver-1").json()["status"] == "approval_recorded"
    assert _execute(dual, item, _move(4.8)).status_code == 409


def test_the_hard_cap_still_refuses_at_assess_whatever_the_approvals(dual):
    first = _assess(dual, _move(5.4))                      # 1.4 bar: tier, under the cap
    for who in ("approver-1", "approver-2"):
        _approve(dual, first["review_item_id"], who)
    assert _executed(_execute(dual, first["review_item_id"], _move(5.4))) is True
    r = dual.post("/v1/execution/assess", json=_move(5.7), headers=_as("agent-1"))
    assert (r.status_code, r.json()["detail"]) == (409, "limit_exceeded")   # 1.7 > 1.6


def test_a_total_that_grew_after_one_approval_refuses_at_dispatch(dual):
    """Approved by one person while under the tier; by dispatch another move
    took the hour past it. The reservation reads the total it charges, and
    the signed lease names one approver, so the call does not run."""
    late = _assess(dual, _move(4.3))                       # 0.3 from 4.0: one approver
    assert "approvals_required" not in late
    assert _approve(dual, late["review_item_id"], "approver-1").json()["status"] == "approved"
    early = _assess(dual, _move(3.7))                      # 0.3 the other way
    _approve(dual, early["review_item_id"], "approver-1")
    assert _executed(_execute(dual, early["review_item_id"], _move(3.7))) is True
    # 3.7 -> 4.3 is 0.6 more: 0.9 this hour, past the tier, on one approval.
    e = _execute(dual, late["review_item_id"], _move(4.3)).json()
    assert e["tool_execution"] == {**e["tool_execution"], "executed": False,
                                   "refusal_reason": "limit_dual_control_unmet"}
    assert _setpoint() == 3.7


def test_a_move_that_stays_under_the_tier_needs_one_approver(dual):
    first = _assess(dual, _move(4.2))
    assert "approvals_required" not in first
    _approve(dual, first["review_item_id"], "approver-1")
    assert _executed(_execute(dual, first["review_item_id"], _move(4.2))) is True
    second = _assess(dual, _move(4.5))                     # exactly 0.5 this hour
    assert "approvals_required" not in second


def test_an_accept_past_the_tier_becomes_a_review_for_two(dual, monkeypatch):
    """No grant is issued for a call that needs two approvers: redeemed without
    review it would carry none, and the reservation would refuse it."""
    import dataclasses

    import servers.execution_api as exec_mod
    from remora.policy.report import DecisionAction

    real = exec_mod._ENGINE.decide
    monkeypatch.setattr(exec_mod._ENGINE, "decide", lambda obs: dataclasses.replace(
        real(obs), action=DecisionAction.ACCEPT, reasons=()))
    under = _assess(dual, _move(4.2))
    assert under["decision"] == "accept" and "execution_token" in under
    past = _assess(dual, _move(4.8))                       # 0.8 from the plant's 4.0
    assert past["decision"] == "escalate" and "execution_token" not in past
    assert past["approvals_required"] == 2
    item = past["review_item_id"]
    for who in ("approver-1", "approver-2"):
        _approve(dual, item, who)
    assert _executed(_execute(dual, item, _move(4.8))) is True
