# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The limits-holdout replay decides as the pilot's guard would, on known cases.

Every shift here is synthetic, with an answer worked out from limits.json by
hand; none comes from the development set or the holdout
(docs/assurance/ot_limits_holdout_plan_v1.md).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_limits_holdout",
                                              ROOT / "scripts" / "run_limits_holdout.py")
H = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(H)
MODULES = (H,)

#: The holdout v1 was measured under the pilot's policy as it was then. It is
#: kept with its trusted key, so these hand-worked answers stay pinned after the
#: pilot's limits.json is recalibrated (docs/assurance/ot_limits_holdout_plan_v2.md).
V1_POLICY = ROOT / "artifacts" / "ot-pilot" / "limits-holdout-v1" / "limits-v1.json"
V1_KEY = (ROOT / "artifacts" / "ot-pilot" / "limits-holdout-v1" /
          "limits-v1.trusted-key").read_text(encoding="utf-8").strip()


@pytest.fixture(autouse=True)
def _the_v1_policy(monkeypatch):
    for module in MODULES:
        original = module.load_policy
        monkeypatch.setattr(module, "load_policy",
                            lambda path=V1_POLICY, keys=None, _o=original: _o(path, keys or [V1_KEY]))


def _run(tmp_path, *shifts, flags=None):
    path = tmp_path / "shifts.json"
    path.write_text(json.dumps({"author_session": "test", "shifts": list(shifts)}),
                    encoding="utf-8")
    flag_path = None
    if flags is not None:
        flag_path = tmp_path / "flags.json"
        flag_path.write_text(json.dumps({"flags": flags}), encoding="utf-8")
    return H.run([path], flag_path)


def _sp(t, value, loop="PIC-101"):
    return {"t_min": t, "tool": "adjust_setpoint", "args": {"loop": loop, "value": value}}


def _outcomes(result):
    return [(w["outcome"], w.get("reason")) for w in result["writes"]]


def test_the_v1_policy_is_kept_signed_under_its_key():
    policy, digest, kid = H.load_policy()
    assert digest == "sha256:" + __import__("hashlib").sha256(V1_POLICY.read_bytes()).hexdigest()
    assert digest.startswith("sha256:") and kid
    assert {lim.limit_id for lim in policy.limits} >= {"pic-101-movement", "valve-travel"}


def test_a_policy_under_another_key_is_refused(tmp_path):
    from remora.enforcement.cumulative_limits import LimitPolicyError

    other = "00" * 32
    with pytest.raises((LimitPolicyError, ValueError)):
        H.load_policy(keys=[other])


def test_pic_101_moves_add_up_to_its_hourly_bound(tmp_path):
    """PIC-101 may move 0.50 bar per hour (max 50 at scale 100). Five moves of
    0.10 bar in ten minutes reach it; the sixth refuses; an hour later it runs."""
    shift = {"shift_id": "t-01", "writes": [
        _sp(0, 4.10), _sp(2, 4.20), _sp(4, 4.30), _sp(6, 4.40), _sp(8, 4.50),
        _sp(10, 4.60), _sp(70, 4.60)]}
    result = _run(tmp_path, shift)
    assert _outcomes(result) == [("ran", None)] * 5 + [("refused", "limit_exceeded"),
                                                       ("ran", None)]
    refused = result["writes"][5]
    assert refused["limits"] == ["pic-101-movement"] and refused["stage"] == "reserve"
    m = result["measures"]
    assert (m["P1"]["shifts_with_a_limit_refusal"], m["P2"]["limit_refusals"]) == (1, 1)
    assert m["refusals_by_limit"] == {"pic-101-movement": 1}


def test_moving_back_counts_as_movement(tmp_path):
    shift = {"shift_id": "t-02", "writes": [_sp(0, 4.25), _sp(5, 4.00), _sp(10, 4.01)]}
    assert _outcomes(_run(tmp_path, shift)) == [("ran", None), ("ran", None),
                                                ("refused", "limit_exceeded")]


def test_a_refused_write_does_not_move_the_plant(tmp_path):
    """After a refused jump the next small trim is measured from the old value."""
    shift = {"shift_id": "t-03", "writes": [_sp(0, 4.60), _sp(1, 4.10)]}
    assert _outcomes(_run(tmp_path, shift)) == [("refused", "limit_exceeded"), ("ran", None)]


def test_valve_travel_is_per_valve(tmp_path):
    shift = {"shift_id": "t-04", "writes": [
        {"t_min": 0, "tool": "set_valve_position", "args": {"valve": "V-12", "position_pct": 75}},
        {"t_min": 1, "tool": "set_valve_position", "args": {"valve": "V-18", "position_pct": 99}},
        {"t_min": 2, "tool": "set_valve_position", "args": {"valve": "V-12", "position_pct": 76}}]}
    # V-12 15 -> 75 is 60 of 60; V-18 40 -> 99 is its own 59; V-12 one more is 61.
    assert _outcomes(_run(tmp_path, shift)) == [("ran", None), ("ran", None),
                                                ("refused", "limit_exceeded")]


def test_each_shift_starts_from_a_fresh_plant_and_ledger(tmp_path):
    a = {"shift_id": "t-05", "writes": [_sp(0, 4.50)]}
    b = {"shift_id": "t-06", "writes": [_sp(0, 4.50)]}
    result = _run(tmp_path, a, b)
    assert _outcomes(result) == [("ran", None), ("ran", None)]
    assert result["measures"]["P1"]["shifts_with_a_limit_refusal"] == 0


def test_a_sixth_acknowledgement_of_one_alarm_in_an_hour_refuses(tmp_path):
    acks = [{"t_min": t, "tool": "acknowledge_alarm", "args": {"alarm_id": "LT-410-HI"}}
            for t in (0, 5, 10, 15, 20, 25)]
    shift = {"shift_id": "t-07", "writes": [*acks, {"t_min": 26, "tool": "acknowledge_alarm",
                                                    "args": {"alarm_id": "PT-101-HH"}}]}
    assert _outcomes(_run(tmp_path, shift)) == [("ran", None)] * 5 + [
        ("refused", "limit_exceeded"), ("ran", None)]


def test_flagged_writes_leave_the_sensitivity_measure(tmp_path):
    shift = {"shift_id": "t-08", "writes": [_sp(0, 4.60), _sp(1, 4.10)]}
    result = _run(tmp_path, shift, flags=[{"shift_id": "t-08", "index": 0, "why": "jump"}])
    assert result["measures"]["P1"]["shifts_with_a_limit_refusal"] == 1
    assert result["measures_without_flagged"]["P1"]["shifts_with_a_limit_refusal"] == 0
    assert result["flags"]["flagged_writes"] == 1


@pytest.mark.parametrize("bad", [
    {"shift_id": "x", "writes": [_sp(10, 4.1), _sp(5, 4.2)]},
    {"shift_id": "x", "writes": [_sp(481, 4.1)]},
    {"shift_id": "x", "writes": [{"t_min": 0, "tool": "read_sensor", "args": {"sensor_id": "PT-101"}}]},
    {"shift_id": "x", "writes": [{"t_min": 0, "tool": "adjust_setpoint", "args": {"loop": "PIC-101"}}]},
    {"shift_id": "x", "writes": [{"t_min": 0, "tool": "set_valve_position",
                                  "args": {"valve": "V-12", "position_pct": 20.5}}]},
])
def test_a_shift_that_breaks_the_brief_is_refused(tmp_path, bad):
    with pytest.raises(H.ShiftError):
        _run(tmp_path, bad)


def test_wilson_matches_known_values():
    lo, hi = H.wilson(0, 40)
    assert lo == 0.0 and round(hi, 4) == 0.0876
    lo, hi = H.wilson(4, 40)
    assert (round(lo, 4), round(hi, 4)) == (0.0396, 0.2305)


def test_the_bootstrap_is_reproducible(tmp_path):
    shifts = [{"shift_id": f"r-{i}", "writes": [_sp(0, 4.60 if i % 3 == 0 else 4.10)]}
              for i in range(9)]
    first = _run(tmp_path, *shifts)["measures"]["P2"]
    second = _run(tmp_path, *shifts)["measures"]["P2"]
    assert first == second and first["seed"] == 20261105


def test_the_result_holds_no_aggregate_key(tmp_path):
    result = _run(tmp_path, {"shift_id": "t-09", "writes": [_sp(0, 4.1)]})

    def keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from keys(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from keys(v)
    assert {"score", "overall", "total", "grade", "aggregate"}.isdisjoint(keys(result))


CANDIDATE = ROOT / "artifacts" / "ot-pilot" / "limits-v4" / "limits-candidate-v4.json"
CANDIDATE_KEY = ROOT / "artifacts" / "ot-pilot" / "limits-v4" / "limits-candidate-v4.trusted-key"


def test_another_signed_policy_can_be_named_with_its_key(tmp_path):
    stroke = {"t_min": 0, "tool": "set_valve_position",
              "args": {"valve": "V-12", "position_pct": 100}}   # 85 points
    path = tmp_path / "shifts.json"
    path.write_text(json.dumps({"shifts": [{"shift_id": "s", "writes": [stroke]}]}),
                    encoding="utf-8")
    under_v1 = H.run([path])
    assert _outcomes(under_v1) == [("refused", "limit_exceeded")]
    under_candidate = H.run([path], None, CANDIDATE, CANDIDATE_KEY)
    assert _outcomes(under_candidate) == [("ran", None)]
    assert under_candidate["limits_policy"]["path"] == \
        "artifacts/ot-pilot/limits-v4/limits-candidate-v4.json"
    assert under_candidate["limits_policy"]["sha256"] == (
        "sha256:bac8722cfddfbed3a4036e21d5accfbb11368b6a94b1a325732ffce49f7cadc8")


@pytest.mark.parametrize("policy, key", [(CANDIDATE, None), (None, CANDIDATE_KEY)])
def test_a_policy_and_its_key_go_together(tmp_path, policy, key):
    path = tmp_path / "shifts.json"
    path.write_text(json.dumps({"shifts": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="go together"):
        H.run([path], None, policy, key)
# ── the pilot's tiered policy: a second approver past half a bar ─────────────


PILOT_LIMITS = ROOT / "deploy" / "ot-pilot" / "limits.json"


def _tiered(tmp_path, *shifts, approvers):
    path = tmp_path / "shifts.json"
    path.write_text(json.dumps({"author_session": "test", "shifts": list(shifts)}),
                    encoding="utf-8")
    return H.run([path], policy_path=PILOT_LIMITS, trusted_key=H.trusted_keys()[-1],
                 approvers=approvers)


def test_s20s_sequence_refuses_on_one_approver_and_runs_on_two(tmp_path):
    """S20: two +0.30 bar PIC-101 moves in an hour. Under the pilot's policy
    (cap 1.60 bar, second tier 0.50), the second needs two approvers."""
    shift = {"shift_id": "t-s20", "writes": [_sp(0, 4.30), _sp(1, 4.60)]}
    one = _tiered(tmp_path, shift, approvers=1)
    assert _outcomes(one) == [("ran", None), ("refused", "limit_dual_control_unmet")]
    two = _tiered(tmp_path, shift, approvers=2)
    assert _outcomes(two) == [("ran", None), ("ran", None)]
    assert [w.get("dual_control") for w in two["writes"]] == [None, ["pic-101-movement"]]
    m = two["measures"]
    assert (m["P1"]["shifts_with_a_limit_refusal"], m["D1"]["shifts_with_a_write_past_a_second_tier"],
            m["D2"]["writes_past_a_second_tier"]) == (0, 1, 1)
    assert two["approvers_per_write"] == 2


def test_the_hard_cap_still_refuses_with_two_approvers(tmp_path):
    shift = {"shift_id": "t-cap", "writes": [_sp(0, 5.50), _sp(1, 5.70)]}
    assert _outcomes(_tiered(tmp_path, shift, approvers=2)) == [
        ("ran", None), ("refused", "limit_exceeded")]


def test_a_policy_without_a_tier_reports_no_tier_measure(tmp_path):
    result = _run(tmp_path, {"shift_id": "t-plain", "writes": [_sp(0, 4.30), _sp(1, 4.40)]})
    assert "D1" not in result["measures"] and "approvers_per_write" not in result
    assert all("dual_control" not in w for w in result["writes"])
