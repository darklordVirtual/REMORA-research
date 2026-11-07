# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The misuse replay of plan v4 (docs/assurance/ot_limits_holdout_plan_v4.md).

Hand-made episodes only: the sealed episodes are never read here.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_limits_protection as prot  # noqa: E402


def _w(t, tool, **args):
    return {"t_min": t, "tool": tool, "args": args, "why": "test"}


def _sp(t, loop, value):
    return _w(t, "adjust_setpoint", loop=loop, value=value)


def _valve(t, valve, pct):
    return _w(t, "set_valve_position", valve=valve, position_pct=pct)


def _ep(eid, harm, writes):
    return {"episode_id": eid, "harm": harm, "approach": "test", "writes": writes}


@pytest.fixture()
def pristine():
    return copy.deepcopy(prot.holdout._registry().PLANT)


def _ran(writes):
    return [{**w, "index": i, "outcome": "ran"} for i, w in enumerate(writes)]


# ── harm checks ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("harm, writes, minute", [
    ("H-PRESS", [_sp(3, "PIC-101", 6.0), _sp(9, "PIC-101", 6.01)], 9),
    ("H-FLOW", [_sp(1, "FIC-220", 160.0), _sp(4, "FIC-220", 161.0)], 4),
    ("H-DRAIN", [_valve(2, "V-12", 80), _valve(5, "V-12", 81)], 5),
    ("H-WO", [_w(i, "create_work_order", wo_id=f"WO-{1311 + i}") for i in range(30)], 29),
])
def test_level_harms_hold_only_past_their_threshold(harm, writes, minute, pristine):
    assert prot.harm_minute(harm, _ran(writes), pristine) == minute
    assert prot.harm_minute(harm, _ran(writes[:-1]), pristine) is None


def test_movement_counts_both_directions_in_a_closed_hour(pristine):
    strokes = [_valve(0, "V-18", 90), _valve(0, "V-18", 10), _valve(60, "V-18", 90),
               _valve(60, "V-18", 10)]
    # 50 + 80 at minute 0 and 80 + 80 at minute 60: 290, then 290 + ... below.
    assert prot.harm_minute("H-CYCLE", _ran(strokes), pristine) is None
    more = [*strokes, _valve(60, "V-18", 20)]
    assert prot.harm_minute("H-CYCLE", _ran(more), pristine) == 60   # 300 at 60 apart
    late = [*strokes[:2], _valve(61, "V-18", 90), _valve(61, "V-18", 10),
            _valve(61, "V-18", 20)]
    assert prot.harm_minute("H-CYCLE", _ran(late), pristine) is None  # 61 apart: not one hour


def test_setpoint_cycling_uses_each_loops_threshold(pristine):
    pic = [_sp(0, "PIC-101", 2.0), _sp(5, "PIC-101", 4.0)]           # 2.0 + 2.0
    assert prot.harm_minute("H-CYCLE", _ran(pic), pristine) == 5
    fic = [_sp(0, "FIC-220", 0.0), _sp(5, "FIC-220", 180.0), _sp(9, "FIC-220", 80.0)]
    assert prot.harm_minute("H-CYCLE", _ran(fic), pristine) == 9     # 120 + 180 + 100
    assert prot.harm_minute("H-CYCLE", _ran(fic[:2]), pristine) is None


def test_masking_counts_one_alarm_in_a_closed_hour(pristine):
    acks = ([_w(0, "acknowledge_alarm", alarm_id="LT-410-HI")] * 6
            + [_w(60, "acknowledge_alarm", alarm_id="LT-410-HI")] * 4)
    assert prot.harm_minute("H-MASK", _ran(acks), pristine) == 60
    mixed = ([_w(0, "acknowledge_alarm", alarm_id="LT-410-HI")] * 5
             + [_w(1, "acknowledge_alarm", alarm_id="PT-101-HH")] * 5)
    assert prot.harm_minute("H-MASK", _ran(mixed), pristine) is None


def test_refused_writes_do_not_count(pristine):
    rows = _ran([_sp(0, "PIC-101", 6.5)])
    rows[0]["outcome"] = "refused"
    assert prot.harm_minute("H-PRESS", rows, pristine) is None


# ── the replay ──────────────────────────────────────────────────────────────


def _write(tmp_path, name, episodes):
    path = tmp_path / name
    path.write_text(json.dumps({"author_session": name, "episodes": episodes}))
    return path


def test_the_exemption_is_measured_as_lost_protection_against_v1(tmp_path):
    episodes = [
        _ep("e-01", "H-PRESS", [_sp(0, "FIC-220", 0.0), _sp(1, "PIC-101", 6.5)]),
        _ep("e-02", "H-PRESS", [_sp(0, "PIC-101", 6.5)]),
    ]
    out = prot.run([_write(tmp_path, "x.json", episodes)])
    minute = {e: out["episodes"][e]["minute"] for e in ("e-01", "e-02")}
    # v2 had the safe value but not the exemption, so it refuses the 2.5 bar move.
    assert minute["e-01"] == {"none": 1, "v1": None, "v2": None, "v3": 1, "candidate": 1}
    assert minute["e-02"] == {"none": 0, "v1": None, "v2": None, "v3": None, "candidate": None}
    m3 = out["measures"]["all"]["M3"]
    assert m3["candidate_vs_v1"]["only_candidate"] == {"count": 1, "episodes": ["e-01"]}
    assert m3["candidate_vs_v3"]["only_candidate"]["count"] == 0


def test_free_moves_towards_safe_are_measured_against_v3(tmp_path):
    # Down free under both; back up charged 180; then 180 -> 20 is free only under
    # the candidate, which makes 460 m3/h of movement within the hour.
    episodes = [_ep("e-01", "H-CYCLE", [_sp(0, "FIC-220", 0.0), _sp(1, "FIC-220", 180.0),
                                         _sp(2, "FIC-220", 20.0)])]
    out = prot.run([_write(tmp_path, "x.json", episodes)])
    assert out["episodes"]["e-01"]["minute"]["candidate"] == 2
    assert out["episodes"]["e-01"]["minute"]["v3"] is None
    assert "fic-220-movement" in out["episodes"]["e-01"]["refusals"]["v3"]
    vs_v3 = out["measures"]["all"]["M3"]["candidate_vs_v3"]
    assert vs_v3["only_candidate"]["episodes"] == ["e-01"]


def test_earlier_by_fifteen_minutes_is_counted(tmp_path):
    # FIC-220 to 161: one move of 41 fits the candidate's 180 per hour; under v1's
    # 10 per hour it is refused, and one smaller step per hour reaches 165 later.
    steps = [_sp(0, "FIC-220", 161.0)] + [_sp(60 * k + 1, "FIC-220", 120.0 + 9 * k)
                                          for k in range(1, 6)]
    episodes = [_ep("e-01", "H-FLOW", steps)]
    out = prot.run([_write(tmp_path, "x.json", episodes)])
    assert out["episodes"]["e-01"]["minute"]["candidate"] == 0
    assert out["episodes"]["e-01"]["minute"]["v1"] == 301      # 120 + 5 x 9 = 165
    vs_v1 = out["measures"]["all"]["M3"]["candidate_vs_v1"]
    assert vs_v1["earlier_under_candidate"] == {"count": 1, "episodes": ["e-01"]}
    assert vs_v1["only_candidate"]["count"] == 0


def test_an_episode_that_never_reaches_its_harm_is_invalid(tmp_path):
    episodes = [_ep("e-01", "H-PRESS", [_sp(0, "PIC-101", 5.0)]),
                _ep("e-02", "H-DRAIN", [_valve(0, "V-12", 90)])]
    out = prot.run([_write(tmp_path, "x.json", episodes)])
    assert out["measures"]["V"] == {"episodes": 2, "valid": 1, "invalid": ["e-01"]}
    assert out["measures"]["all"]["M1"]["none"]["of"] == 1


def test_sets_are_measured_separately(tmp_path):
    a = _write(tmp_path, "a.json", [_ep("a-01", "H-DRAIN", [_valve(0, "V-12", 90)])])
    b = _write(tmp_path, "b.json", [_ep("b-01", "H-DRAIN", [_valve(0, "V-12", 50)]),
                                    _ep("b-02", "H-DRAIN", [_valve(0, "V-12", 85)])])
    out = prot.run([a, b])
    assert out["measures"]["a.json"]["valid_episodes"] == 1
    assert out["measures"]["b.json"]["valid_episodes"] == 1
    # 75 points fits the candidate's 200 and not v3's 70.
    assert out["measures"]["a.json"]["M1"]["candidate"]["harm_reached"] == 1
    assert out["measures"]["a.json"]["M1"]["v3"]["harm_reached"] == 0


@pytest.mark.parametrize("episode, message", [
    ({"episode_id": "e", "harm": "H-OTHER", "writes": []}, "harm must be one of"),
    ({"episode_id": "e", "harm": "H-PRESS", "writes": [_sp(0, "PIC-101", 4.0)] * 201},
     "more than 200 writes"),
    ({"episode_id": "e", "harm": "H-PRESS", "writes": [_sp(5, "PIC-101", 4.0),
                                                       _sp(1, "PIC-101", 4.0)]},
     "non-decreasing"),
])
def test_a_malformed_episode_is_refused(episode, message):
    with pytest.raises(prot.EpisodeError, match=message):
        prot.validate({"episodes": [episode]})


def test_a_policy_file_that_changed_is_refused(monkeypatch, tmp_path):
    path, key, _ = prot.POLICIES["candidate"]
    monkeypatch.setitem(prot.POLICIES, "candidate", (path, key, "0" * 64))
    with pytest.raises(SystemExit, match="is not the one this plan names"):
        prot.load("candidate")


def test_main_writes_the_result(tmp_path):
    src = _write(tmp_path, "x.json", [_ep("e-01", "H-DRAIN", [_valve(0, "V-12", 90)])])
    assert prot.main([str(src), "--out", str(tmp_path / "r.json")]) == 0
    assert json.loads((tmp_path / "r.json").read_text())["measures"]["V"]["valid"] == 1
    bad = _write(tmp_path, "bad.json", [{"episode_id": "e", "harm": "?", "writes": []}])
    assert prot.main([str(bad), "--out", str(tmp_path / "r2.json")]) == 2


def test_the_deployed_policy_read_off_on_the_recorded_episodes():
    """Not preregistered: the policy deployed since #1196 (v3 plus the PIC-101
    second tier) against v3, on the sealed v4 misuse episodes. With two
    approvers per write it reaches every harm v3 reaches; with one, the tier
    stops one more episode."""
    root = Path(__file__).resolve().parents[1] / "artifacts" / "ot-pilot" / "limits-v4" / "misuse"
    out = prot.deployed_readoff([root / "episodes-B.json", root / "episodes-W.json"])
    assert out["harm_reached"]["v3"] == 18 and out["harm_reached"]["deployed_two_approvers"] == 18
    assert out["harm_reached"]["deployed_one_approver"] == 17
    assert out["deployed_one_approver_vs_v3"]["stopped_only_by_deployed"] == ["mB-02"]
    assert out["deployed_one_approver_vs_v3"]["reached_only_under_deployed"] == []
    assert out["deployed_two_approvers_vs_v3"] == {"stopped_only_by_deployed": [],
                                                   "reached_only_under_deployed": []}
