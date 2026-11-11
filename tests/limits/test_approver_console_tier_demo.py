# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""End-to-end demonstration of the second-tier approver flow, headless.

The OT pilot's tiered PIC-101 policy routes any pressure move past the 0.50 bar
second tier to a human, who needs a second distinct approver. These tests
drive the approver console the way a pilot operator would: assess the move,
fetch the review packet REMORA holds, join it with the proposed call the
deployment holds, and then act on the operator's judgment.

Two outcomes, same mechanism. A maintenance move the operator reads and accepts
is approved by two reviewers and executes. A move the operator reads and
refuses (an unsafe excursion presented under a vague work order) is rejected
and never runs. REMORA escalates both identically; the packet is what lets the
human tell them apart. The console refuses to assemble a packet whose call does
not bind to the hash REMORA recorded.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tests.limits.test_limits_dual_control_api import (  # noqa: E402,F401
    _approve, _as, _assess, _execute, _executed, _move, dual,
)
from tests.limits.test_limits_ot_pilot import pilot, shipped_policy  # noqa: E402,F401

import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

# deploy/ot-pilot is not an importable package (the dash), so load by path.
_CONSOLE = Path(__file__).resolve().parents[2] / "deploy" / "ot-pilot" / "approver_console.py"
_spec = importlib.util.spec_from_file_location("ot_approver_console", _CONSOLE)
ac = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(ac)

TENANT = "ot-pilot"


def _transport(client):
    def get(path, token):
        r = client.get(path, headers=_as(token))
        return r.status_code, (r.json() if r.content else {})

    def post(path, token, body):
        r = client.post(path, json=body, headers=_as(token))
        return r.status_code, (r.json() if r.content else {})

    return get, post


def _console(client):
    get, post = _transport(client)
    return ac.ApproverConsole(get, post, tenant=TENANT)


def _escalating_move(client):
    """Execute a first +0.30 bar move, then assess a second that passes the tier.

    The second move is 0.6 bar this hour, past the 0.50 bar second tier, so it
    escalates to a dual-control item. Returns the second move's assess body.
    """
    first = _assess(client, _move(4.3))
    _approve(client, first["review_item_id"], "approver-1")
    assert _executed(_execute(client, first["review_item_id"], _move(4.3))) is True
    return _assess(client, _move(4.6))


def test_a_maintenance_move_is_assembled_approved_by_two_and_executes(dual):
    assessed = _escalating_move(dual)
    proposal_id, item = assessed["proposal_id"], assessed["review_item_id"]
    console = _console(dual)

    packet = console.present(proposal_id, _move(4.6), token="approver-1")
    assert packet["binds"] is True
    assert packet["would_pass"]["approvals_required"] == 2
    assert "pic-101-movement" in packet["would_pass"]["limits"]
    # The operator can read the actual request REMORA never stored.
    assert packet["request"]["arguments"]["value"] == 4.6
    assert "proposal" in ac.render_text(packet)

    # The operator judges it a legitimate maintenance move.
    assert ac.decide(packet, lambda p: p["request"]["arguments"]["value"] <= 5.0) == ac.APPROVE

    results = console.approve(item, ["approver-1", "approver-2"])
    assert [s for s, _ in results] == [200, 200]

    assert _executed(_execute(dual, item, _move(4.6))) is True


def test_an_unsafe_excursion_is_assembled_declined_and_never_runs(dual):
    assessed = _escalating_move(dual)
    proposal_id, item = assessed["proposal_id"], assessed["review_item_id"]
    console = _console(dual)

    packet = console.present(proposal_id, _move(4.6), token="approver-1")

    # The operator reads the packet and refuses this excursion.
    assert ac.decide(packet, lambda p: p["request"]["arguments"]["value"] <= 4.4) == ac.DECLINE

    status, _ = console.reject(item, "approver-1", reason="excursion refused by operator")
    assert status == 200

    # A rejected item can never be approved or executed afterwards.
    approve = console.approve(item, ["approver-1"])
    assert approve[0][0] in (404, 409)
    assert _executed(_execute(dual, item, _move(4.6))) is not True


def test_console_refuses_a_packet_whose_call_does_not_bind(dual):
    assessed = _escalating_move(dual)
    proposal_id = assessed["proposal_id"]
    console = _console(dual)

    # The operator is shown a different value than the one REMORA stopped.
    with pytest.raises(ac.BindingMismatch):
        console.present(proposal_id, _move(9.9), token="approver-1")
