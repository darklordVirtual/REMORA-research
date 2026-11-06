# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A change meter's declared safe value: the move to it is never refused or charged.

The limits holdout (docs/assurance/ot_limits_holdout_plan_v1.md) found every
move of the OT pilot's delivery setpoint to zero refused, as any such move from
the normal band was, because a movement limit counts the move to a stop like
any other. A meter may now declare, per resource, the value that is safe. A
write whose new value is exactly that value is let through by every movement
limit, even a full one, and charges nothing, at reservation or after the fact.
The fence does not stop it either. Moving away from the safe value again is
charged as any move, so a restart is still metered.
"""
from __future__ import annotations

import sqlite3

import pytest

from remora.enforcement import cumulative_limits as cl
from tests.limits.test_limits_unit import (
    LIMITS,
    METERS,
    OBSERVED_METERS,
    PREV_METERS,
    SEEN_LIMIT,
    T0,
    policy,
    reserve,
)

#: Limit 2.0 degC per hour on the observed meter; 15.0 degC is declared safe on AHU-1.
SAFE_METER = dict(PREV_METERS["move_seen"][0], safe_values={"AHU-1": 15.0})


def _guard(tmp_path, plant, meter=SAFE_METER, name="safe.db"):
    def observe(tenant, quantity, resource):
        return plant[resource]
    return cl.LimitGuard(policy(meters={**METERS, "move_seen": [meter]},
                                limits=[*LIMITS, SEEN_LIMIT]),
                         cl.LimitLedger(tmp_path / name), observer=observe)


def _charges(path, op):
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute(
            "SELECT amount FROM limit_reservation WHERE operation_id=?", (op,))]


def _run(guard, plant, op, value, *, now=T0, previous=None):
    """Reserve, fence, begin, write and settle, as the dispatcher would; the refusal or None."""
    refusal = reserve(guard, "move_seen", op, now=now, unit="AHU-1", value=value)
    if refusal is None:
        refusal = guard.fence(op)
    if refusal is None:
        refusal = guard.begin(op)
    if refusal is not None:
        return refusal
    old = plant["AHU-1"]
    plant["AHU-1"] = value
    guard.settle(op, True, result={"previous": old if previous is None else previous}, now=now)
    return None


def test_the_move_to_the_safe_value_runs_on_a_full_counter_and_charges_nothing(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", 21.0) is None          # 2.0 of 2.0 used
    assert _run(guard, plant, "2", 21.1) == cl.EXCEEDED   # full
    assert _run(guard, plant, "3", 15.0) is None          # the stop: 6.0 degC, charged 0
    assert _charges(tmp_path / "safe.db", "3") == [0]
    assert plant["AHU-1"] == 15.0


def test_the_move_to_the_safe_value_runs_on_a_counter_charged_past_its_limit(tmp_path):
    """After-the-fact accounting can push a counter past its limit: reserved 1.5,
    but the controller reports it moved from 17.0, so 3.5 of 2.0 is charged. An
    ordinary move must refuse; the stop must still run."""
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", 20.5, previous=17.0) is None
    assert guard.ledger.charges("1#after")                # 2.0 charged after the fact
    assert _run(guard, plant, "2", 20.4) == cl.EXCEEDED
    assert _run(guard, plant, "3", 15.0) is None


def test_moving_away_from_the_safe_value_is_charged_as_any_move(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", 15.0) is None          # to safe, free
    assert _run(guard, plant, "2", 16.5) is None          # restart: 1.5 charged
    assert _charges(tmp_path / "safe.db", "2") == [15]
    assert _run(guard, plant, "3", 17.1) == cl.EXCEEDED   # 1.5 + 0.6 > 2.0


def test_a_value_near_the_safe_value_is_not_the_safe_value(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", 15.1) == cl.EXCEEDED   # 3.9 degC, not a stop


def test_no_after_the_fact_charge_for_a_move_to_the_safe_value(tmp_path):
    """The controller reports it moved from 25.0, so 10.0 degC happened; none
    of it is charged, and the next legitimate trim still has its whole budget."""
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant)
    assert _run(guard, plant, "1", 15.0, previous=25.0) is None
    assert guard.ledger.charges("1#after") == []
    assert _run(guard, plant, "2", 17.0) is None          # 2.0 of 2.0, allowed


def test_the_fence_does_not_stop_the_move_to_the_safe_value(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=15.0) is None
    plant["AHU-1"] = 19.4                                 # someone moved it meanwhile
    assert guard.fence("1") is None


def test_the_fence_still_stops_an_ordinary_move_after_the_plant_moved(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-1", value=19.5) is None
    plant["AHU-1"] = 19.4
    assert guard.fence("1") == cl.STATE_CHANGED


def test_another_resource_has_no_safe_value(tmp_path):
    plant = {"AHU-1": 19.0, "AHU-2": 19.0}
    guard = _guard(tmp_path, plant)
    assert reserve(guard, "move_seen", "1", unit="AHU-2", value=15.0) == cl.EXCEEDED


def test_a_tracked_change_meter_honours_its_safe_value(tmp_path):
    meter = dict(METERS["move"][0], safe_values={"AHU-1": 0.0})
    guard = cl.LimitGuard(policy(meters={**METERS, "move": [meter]}),
                          cl.LimitLedger(tmp_path / "tracked.db"))
    assert reserve(guard, "move", "1", unit="AHU-1", value=0.0) is None   # 19.0 -> 0, free
    guard.settle("1", True)
    assert _charges(tmp_path / "tracked.db", "1") == [0]
    assert reserve(guard, "move", "2", unit="AHU-1", value=2.1) == cl.EXCEEDED


def test_a_policy_without_safe_values_is_unchanged(tmp_path):
    plant = {"AHU-1": 19.0}
    guard = _guard(tmp_path, plant, meter=PREV_METERS["move_seen"][0], name="plain.db")
    assert _run(guard, plant, "1", 15.0) == cl.EXCEEDED


@pytest.mark.parametrize("raw, message", [
    ({"quantity": "q", "kind": "count", "unit": "u", "safe_values": {"r": 0}},
     "safe_values are for change meters only"),
    ({**OBSERVED_METERS["move_seen"][0], "safe_values": {}},
     "safe_values is a non-empty object of resource to value"),
    ({**OBSERVED_METERS["move_seen"][0], "safe_values": ["AHU-1"]},
     "safe_values is a non-empty object of resource to value"),
    ({**OBSERVED_METERS["move_seen"][0], "safe_values": {"AHU-1": 15.05}},
     "safe value for 'AHU-1' is not a number at scale 10"),
    ({**OBSERVED_METERS["move_seen"][0], "safe_values": {"AHU-1": True}},
     "safe value for 'AHU-1' is not a number at scale 10"),
    ({**OBSERVED_METERS["move_seen"][0], "safe_values": {"": 0}},
     "a safe_values key names a resource"),
    ({**OBSERVED_METERS["move_seen"][0], "safe_values": {"A\x1fB": 0}},
     "a safe_values key names a resource"),
])
def test_a_malformed_safe_value_refuses_the_policy(raw, message):
    with pytest.raises(cl.LimitPolicyError, match="^tool 'move_seen': " + message.replace("(", r"\(")):
        cl.Meter.from_dict("move_seen", raw)


def test_the_safe_value_is_scaled_like_the_argument():
    meter = cl.Meter.from_dict("move_seen", dict(SAFE_METER))
    assert dict(meter.safe_values) == {"AHU-1": 150}
