# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The post-hoc sensitivity replay differs from the plan's only in a refusal.

Under the plan a refused write leaves the plant where it was. Under the
sensitivity reading it is made by hand outside REMORA: the plant moves and the
ledger charges nothing, and the next governed write is measured from there.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


S = _load("limits_holdout_sensitivity")
H = _load("run_limits_holdout")
MODULES = (H, S.H)

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


def _sp(t, value):
    return {"t_min": t, "tool": "adjust_setpoint", "args": {"loop": "PIC-101", "value": value}}


def _write(tmp_path, *shifts):
    path = tmp_path / "shifts.json"
    path.write_text(json.dumps({"shifts": list(shifts)}), encoding="utf-8")
    return path


def test_a_refused_move_made_by_hand_moves_the_plant_and_charges_nothing(tmp_path):
    """4.00 -> 4.60 is 0.60 bar, past PIC-101's 0.50 per hour, and refuses in both.
    Plan: the plant stays at 4.00, so 4.65 a minute later is 0.65 and refuses.
    By hand: the plant is at 4.60, so 4.65 is 0.05 and runs, and 4.60 was never
    charged, so 0.45 of budget is left."""
    shift = {"shift_id": "s-01", "writes": [_sp(0, 4.60), _sp(1, 4.65), _sp(2, 5.10)]}
    path = _write(tmp_path, shift)
    plan = [(w["outcome"], w.get("reason")) for w in H.run([path])["writes"]]
    hand = [(w["outcome"], w.get("reason")) for w in S.run([path])["writes"]]
    assert plan == [("refused", "limit_exceeded"), ("refused", "limit_exceeded"),
                    ("refused", "limit_exceeded")]
    assert hand == [("refused", "limit_exceeded"), ("ran", None), ("ran", None)]


def test_the_first_refusal_in_a_shift_is_the_same_under_both_readings(tmp_path):
    shifts = [{"shift_id": f"s-{i}", "writes": [_sp(0, 4.10), _sp(5, 4.20 + 0.2 * i),
                                                _sp(9, 4.0)]} for i in range(4)]
    path = _write(tmp_path, *shifts)
    first = {}
    for name, result in (("plan", H.run([path])), ("hand", S.run([path]))):
        first[name] = {w["shift_id"]: w["index"] for w in reversed(result["writes"])
                       if w["outcome"] == "refused"}
    assert first["plan"] == first["hand"]
