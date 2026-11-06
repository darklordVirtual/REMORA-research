# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A resource exempt while another is at its safe value (owner decision 2026-11-06).

Holdout v2 (docs/assurance/ot_limits_holdout_plan_v2.md) left the OT pilot's
PIC-101 refused around stops: with delivery parked at FIC-220 = 0, operators
lower the pressure setpoint for the restart and raise it again, and the
movement limit counts all of it. An observed change meter may now declare
``exempt_while_safe``: while the plant reports the named other resource at its
declared safe value, a move of this resource is charged nothing, before or after
the fact. Once the other resource leaves its safe value every move is charged
again. The fence still applies, and an unreadable plant is not a safe one.
"""
from __future__ import annotations

import sqlite3

import pytest

from remora.enforcement import cumulative_limits as cl
from tests.limits.test_limits_unit import LIMITS, METERS, SEEN_LIMIT, T0, policy, reserve

#: Movement of "seen" in degC at scale 10, 2.0 per hour per unit. PUMP = 0 is safe,
#: and AHU-1 is exempt while PUMP is there.
METER = {"quantity": "seen", "kind": "change", "argument": "value", "scale": 10,
         "unit": "degC", "resource_argument": "unit", "observed": True,
         "previous_field": "previous", "safe_values": {"PUMP": 0},
         "exempt_while_safe": {"AHU-1": "PUMP"}}


def _guard(tmp_path, plant, meter=METER, name="exempt.db"):
    def observe(tenant, quantity, resource):
        value = plant[resource]
        if isinstance(value, Exception):
            raise value
        return value
    return cl.LimitGuard(policy(meters={**METERS, "move_seen": [meter]},
                                limits=[*LIMITS, SEEN_LIMIT]),
                         cl.LimitLedger(tmp_path / name), observer=observe)


def _charges(path, op):
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute(
            "SELECT amount FROM limit_reservation WHERE operation_id=?", (op,))]


def _run(guard, plant, op, unit, value, *, now=T0, previous=None):
    refusal = reserve(guard, "move_seen", op, now=now, unit=unit, value=value)
    if refusal is None:
        refusal = guard.fence(op)
    if refusal is None:
        refusal = guard.begin(op)
    if refusal is not None:
        return refusal
    old = plant[unit]
    plant[unit] = value
    guard.settle(op, True, result={"previous": old if previous is None else previous}, now=now)
    return None


def test_while_the_pump_runs_the_resource_is_metered(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "AHU-1", 22.0) == cl.EXCEEDED   # 3.0 of 2.0


def test_while_the_pump_is_at_its_safe_value_moves_are_charged_nothing(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", 0.0) is None            # the stop, free
    assert _run(guard, plant, "2", "AHU-1", 15.0) is None          # 4.0 down, exempt
    assert _run(guard, plant, "3", "AHU-1", 22.0) is None          # 7.0 up, exempt
    assert _charges(tmp_path / "exempt.db", "2") == [0]
    assert _charges(tmp_path / "exempt.db", "3") == [0]


def test_after_the_restart_every_move_is_charged_again(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": 0.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "AHU-1", 15.0) is None          # exempt while stopped
    assert _run(guard, plant, "2", "PUMP", 1.0) is None            # restart: 1.0 charged
    assert _run(guard, plant, "3", "AHU-1", 16.5) is None          # 1.5 charged
    assert _charges(tmp_path / "exempt.db", "3") == [15]
    assert _run(guard, plant, "4", "AHU-1", 17.1) == cl.EXCEEDED   # 1.5 + 0.6 > 2.0


def test_no_after_the_fact_charge_for_a_move_made_while_stopped(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": 0.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "AHU-1", 15.0, previous=30.0) is None
    assert guard.ledger.charges("1#after") == []


def test_an_unreadable_pump_is_not_a_stopped_one(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": OSError("sensor gone")}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "AHU-1", 22.0) == cl.EXCEEDED


def test_a_pump_near_but_not_at_its_safe_value_does_not_exempt(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": 0.1}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "AHU-1", 22.0) == cl.EXCEEDED


def test_the_fence_still_stops_an_exempt_move_after_the_plant_moved(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": 0.0}
    guard = _guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=15.0) is None
    plant["AHU-1"] = 18.0
    assert guard.fence("1") == cl.STATE_CHANGED


def test_only_the_named_resource_is_exempt(tmp_path):
    plant = {"AHU-1": 19.0, "AHU-2": 19.0, "PUMP": 0.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "AHU-2", 22.0) == cl.EXCEEDED


def test_the_assess_preview_sees_the_same_exemption(tmp_path):
    plant = {"AHU-1": 19.0, "PUMP": 0.0}
    guard = _guard(tmp_path, plant)
    assert guard.preview(tenant="t", principal="p", tool_name="move_seen",
                         arguments={"unit": "AHU-1", "value": 22.0}, now=T0) is None
    plant["PUMP"] = 3.0
    assert guard.preview(tenant="t", principal="p", tool_name="move_seen",
                         arguments={"unit": "AHU-1", "value": 22.0}, now=T0) == cl.EXCEEDED


@pytest.mark.parametrize("change, message", [
    ({"observed": False, "previous_field": None},
     "exempt_while_safe is for observed change meters only"),
    ({"exempt_while_safe": {}},
     "exempt_while_safe is a non-empty object of resource to resource"),
    ({"exempt_while_safe": ["AHU-1"]},
     "exempt_while_safe is a non-empty object of resource to resource"),
    ({"exempt_while_safe": {"": "PUMP"}}, "an exempt_while_safe key names a resource"),
    ({"exempt_while_safe": {"AHU-1": "OTHER"}},
     "exempt_while_safe for 'AHU-1' must name another resource with a declared safe value"),
    ({"exempt_while_safe": {"PUMP": "PUMP"}},
     "exempt_while_safe for 'PUMP' must name another resource with a declared safe value"),
])
def test_a_malformed_exemption_refuses_the_policy(change, message):
    raw = {k: v for k, v in {**METER, **change}.items() if v is not None}
    with pytest.raises(cl.LimitPolicyError, match="^tool 'move_seen': " + message):
        cl.Meter.from_dict("move_seen", raw)


def test_a_count_meter_cannot_declare_an_exemption():
    raw = {"quantity": "q", "kind": "count", "unit": "u", "exempt_while_safe": {"a": "b"}}
    with pytest.raises(cl.LimitPolicyError, match="exempt_while_safe is for observed change"):
        cl.Meter.from_dict("t", raw)
