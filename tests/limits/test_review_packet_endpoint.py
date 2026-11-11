# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The review-packet endpoint: the basis a human approver reads before deciding.

``GET /v1/execution/proposals/{id}/review-packet`` returns what REMORA holds
about a proposal awaiting a human: the tool, the decision and its reasons, the
intent resolution and scope, and, when a cumulative limit's second tier is
passed, the ``dual_control`` block naming the limits and the number of
approvers. REMORA governs by labels and hashes and does not retain the raw
tool arguments, so ``arguments_available`` is false and the packet says the
request body is joined from the deployment by ``tool_call_hash``.

These tests run on the OT pilot's own registry and bundle, reusing the tiered
PIC-101 policy fixture from the dual-control API tests.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tests.limits.test_limits_dual_control_api import (  # noqa: E402,F401
    _as,
    _assess,
    _approve,
    _execute,
    _move,
    dual,
)
from tests.limits.test_limits_ot_pilot import pilot, shipped_policy  # noqa: E402,F401


def _packet(client, proposal_id, who="reviewer-1"):
    return client.get(
        f"/v1/execution/proposals/{proposal_id}/review-packet", headers=_as(who)
    )


def test_a_tiered_write_awaiting_a_human_exposes_its_decision_basis(dual):  # noqa: F811  (pytest injects the imported fixture)
    # Two +0.30 bar moves: the second passes the 0.50 bar second tier, so it
    # escalates to a dual-control review item.
    _assess(dual, _move(4.3))
    second = _assess(dual, _move(4.6))
    proposal_id = second["proposal_id"]
    assert second.get("review_item_id")

    r = _packet(dual, proposal_id)
    assert r.status_code == 200, r.text
    packet = r.json()

    assert packet["proposal_id"] == proposal_id
    assert packet["review_item_id"] == second["review_item_id"]
    assert packet["tool_name"] == "adjust_setpoint"
    assert packet["tool_call_hash"]
    assert packet["decision"] in ("verify", "escalate")
    assert packet["reasons"]
    assert packet["pending_human_decision"] is True
    assert packet["current_state"] == "REVIEW_PENDING"

    # The second tier is named, with the number of distinct approvers.
    dc = packet["dual_control"]
    assert dc is not None
    assert "pic-101-movement" in dc["limits"]
    assert dc["approvals_required"] == 2

    # The intent the write was proposed under, as REMORA resolved it.
    assert "resolution_status" in packet["intent"]

    # REMORA does not keep the raw arguments; the packet says so plainly and
    # never invents them.
    assert packet["arguments_available"] is False
    assert "tool_call_hash" in packet["arguments_note"]
    assert "arguments" not in packet


def test_unknown_proposal_is_a_tenant_scoped_404(dual):  # noqa: F811  (pytest injects the imported fixture)
    r = _packet(dual, "proposal-does-not-exist")
    assert r.status_code == 404


def test_pending_flag_clears_once_the_item_is_approved_and_executed(dual):  # noqa: F811  (pytest injects the imported fixture)
    _assess(dual, _move(4.3))
    second = _assess(dual, _move(4.6))
    proposal_id = second["proposal_id"]
    item = second["review_item_id"]

    assert _packet(dual, proposal_id).json()["pending_human_decision"] is True

    _approve(dual, item, "reviewer-1")
    _approve(dual, item, "reviewer-2")
    _execute(dual, item, _move(4.6))

    after = _packet(dual, proposal_id).json()
    assert after["pending_human_decision"] is False
    assert after["current_state"] != "REVIEW_PENDING"
