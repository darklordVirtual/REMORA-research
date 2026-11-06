# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A move towards a declared safe value is free (owner decision 2026-11-06).

Holdout v3 (docs/assurance/ot_limits_holdout_plan_v3.md) refused two FIC-220
restarts: only a write of exactly the safe value was free, so a ramp down to a
stop and the ramp back were both charged. An observed change meter may now
declare ``free_toward_safe``, a list of resources with a declared safe value. A
write whose target lies between the value the plant reports and the safe
value, both included, is charged nothing, and a full counter does not refuse
it. A move past the safe value or away from it is charged as any move. The
fence still applies. After the fact, nothing more is charged only when the
plant's actual move also went towards the safe value.
"""
from __future__ import annotations

import sqlite3

import pytest

from remora.enforcement import cumulative_limits as cl
from tests.limits.test_limits_unit import LIMITS, METERS, SEEN_LIMIT, T0, policy, reserve

#: Movement of "seen" at scale 10, 2.0 per hour per unit. PUMP = 0 and FAN = 0 are
#: safe; only PUMP is free towards it.
METER = {"quantity": "seen", "kind": "change", "argument": "value", "scale": 10,
         "unit": "degC", "resource_argument": "unit", "observed": True,
         "previous_field": "previous", "safe_values": {"PUMP": 0, "FAN": 0},
         "free_toward_safe": ["PUMP"]}


def _guard(tmp_path, plant, meter=METER, name="toward.db"):
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


def _run(guard, plant, op, unit, value, *, now=T0, previous=None, ended=None):
    refusal = reserve(guard, "move_seen", op, now=now, unit=unit, value=value)
    if refusal is None:
        refusal = guard.fence(op)
    if refusal is None:
        refusal = guard.begin(op)
    if refusal is not None:
        return refusal
    old = plant[unit]
    plant[unit] = value if ended is None else ended
    guard.settle(op, True, result={"previous": old if previous is None else previous}, now=now)
    return None


def test_a_ramp_down_to_the_safe_value_is_charged_nothing(tmp_path):
    plant = {"PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", 6.0) is None      # 6.0 down, of 2.0: free
    assert _run(guard, plant, "2", "PUMP", 3.0) is None
    assert _run(guard, plant, "3", "PUMP", 0.0) is None
    assert [_charges(tmp_path / "toward.db", op) for op in "123"] == [[0], [0], [0]]


def test_the_ramp_back_is_charged_and_meets_the_limit(tmp_path):
    plant = {"PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", 0.0) is None
    assert _run(guard, plant, "2", "PUMP", 1.5) is None      # 1.5 away from 0: charged
    assert _charges(tmp_path / "toward.db", "2") == [15]
    assert _run(guard, plant, "3", "PUMP", 2.5) == cl.EXCEEDED   # 1.5 + 1.0 > 2.0


def test_down_and_back_within_the_hour_costs_one_band(tmp_path):
    plant = {"PUMP": 2.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", 1.0) is None      # down: free
    assert _run(guard, plant, "2", "PUMP", 0.0) is None
    assert _run(guard, plant, "3", "PUMP", 1.0) is None      # back: 1.0
    assert _run(guard, plant, "4", "PUMP", 2.0) is None      # back: 2.0 in all
    assert _run(guard, plant, "5", "PUMP", 2.1) == cl.EXCEEDED


def test_a_full_counter_does_not_refuse_a_move_towards_the_safe_value(tmp_path):
    plant = {"PUMP": 0.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", 2.0) is None      # the whole band
    assert _run(guard, plant, "2", "PUMP", 2.1) == cl.EXCEEDED
    assert _run(guard, plant, "3", "PUMP", 1.0) is None      # towards 0: still allowed
    assert _charges(tmp_path / "toward.db", "3") == [0]


def test_free_move_and_charged_move_with_a_second_tier(tmp_path):
    plant = {"PUMP": 0.0}
    limits = [*LIMITS, {**SEEN_LIMIT, "dual_control_above": 10}]
    guard = cl.LimitGuard(policy(meters={**METERS, "move_seen": [METER]}, limits=limits),
                          cl.LimitLedger(tmp_path / "tier.db"),
                          observer=lambda tenant, quantity, resource: plant[resource])
    args = {"unit": "PUMP", "value": 1.5}
    assert guard.dual_control(tenant="t", principal="p", tool_name="move_seen",
                              arguments=args, now=T0) == (SEEN_LIMIT["limit_id"],)
    assert guard.reserve(tenant="t", principal="p", tool_name="move_seen", arguments=args,
                         operation_id="1", request_hash="h-1", now=T0,
                         approvers=2) is None
    assert guard.begin("1") is None
    plant["PUMP"] = 1.5
    guard.settle("1", True, result={"previous": 0.0}, now=T0)
    args["value"] = 0.5
    assert guard.dual_control(tenant="t", principal="p", tool_name="move_seen",
                              arguments=args, now=T0) == ()
    assert reserve(guard, "move_seen", "2", now=T0, **args) is None


def test_an_overfull_counter_does_not_refuse_a_move_towards_safe(tmp_path):
    plant = {"PUMP": 0.0}
    guard = _guard(tmp_path, plant)
    # The controller says it stood at -0.5, so 2.5 moved: 0.5 more than reserved.
    assert _run(guard, plant, "1", "PUMP", 2.0, previous=-0.5) is None
    assert sum(a for _, a in guard.ledger.charges("1#after")) == 5     # 25 of 20 used
    assert _run(guard, plant, "2", "PUMP", 2.0) is None      # staying put: no move away
    assert _run(guard, plant, "3", "PUMP", 1.0) is None      # towards 0, past a full counter
    assert _run(guard, plant, "4", "PUMP", 1.1) == cl.EXCEEDED


def test_a_move_away_from_the_safe_value_is_charged(tmp_path):
    plant = {"PUMP": 1.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", 3.5) == cl.EXCEEDED   # 2.5 away


def test_a_move_past_the_safe_value_is_charged_in_full(tmp_path):
    plant = {"PUMP": 1.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", -1.5) == cl.EXCEEDED  # 2.5 across 0
    assert _run(guard, plant, "2", "PUMP", -0.5) is None
    assert _charges(tmp_path / "toward.db", "2") == [15]


def test_a_resource_not_named_is_free_only_at_its_safe_value(tmp_path):
    plant = {"FAN": 3.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "FAN", 0.5) == cl.EXCEEDED    # 2.5 towards 0, charged
    assert _run(guard, plant, "2", "FAN", 0.0) is None           # exactly safe: free


def test_the_fence_still_stops_a_move_after_the_plant_moved(tmp_path):
    plant = {"PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="PUMP", value=6.0) is None
    plant["PUMP"] = 11.0
    assert guard.fence("1") == cl.STATE_CHANGED


def test_no_after_the_fact_charge_when_the_actual_move_went_towards_safe(tmp_path):
    plant = {"PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", "PUMP", 6.0, previous=15.0) is None
    assert guard.ledger.charges("1#after") == []


def test_an_actual_move_away_from_safe_is_charged_after_the_fact(tmp_path):
    plant = {"PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    # The controller says it stood at 3.0, so the write moved it 3.0 away from 0.
    assert _run(guard, plant, "1", "PUMP", 6.0, previous=3.0) is None
    assert sum(a for _, a in guard.ledger.charges("1#after")) == 30


def test_the_assess_preview_sees_the_same_rule(tmp_path):
    plant = {"PUMP": 12.0}
    guard = _guard(tmp_path, plant)
    assert guard.preview(tenant="t", principal="p", tool_name="move_seen",
                         arguments={"unit": "PUMP", "value": 6.0}, now=T0) is None
    assert guard.preview(tenant="t", principal="p", tool_name="move_seen",
                         arguments={"unit": "PUMP", "value": 14.5}, now=T0) == cl.EXCEEDED


@pytest.mark.parametrize("change, message", [
    ({"observed": False, "previous_field": None},
     "free_toward_safe is for observed change meters only"),
    ({"free_toward_safe": []}, "free_toward_safe is a non-empty list of resources"),
    ({"free_toward_safe": {"PUMP": 0}}, "free_toward_safe is a non-empty list of resources"),
    ({"free_toward_safe": ["PUMP", "PUMP"]}, "free_toward_safe is a non-empty list of resources"),
    ({"free_toward_safe": [""]},
     "a free_toward_safe entry names a resource with a declared safe value"),
    ({"free_toward_safe": ["OTHER"]},
     "a free_toward_safe entry names a resource with a declared safe value"),
])
def test_a_malformed_declaration_refuses_the_policy(change, message):
    raw = {k: v for k, v in {**METER, **change}.items() if v is not None}
    with pytest.raises(cl.LimitPolicyError, match="^tool 'move_seen': " + message):
        cl.Meter.from_dict("move_seen", raw)


def test_a_count_meter_cannot_declare_it():
    raw = {"quantity": "q", "kind": "count", "unit": "u", "free_toward_safe": ["a"]}
    with pytest.raises(cl.LimitPolicyError, match="free_toward_safe is for observed change"):
        cl.Meter.from_dict("t", raw)
