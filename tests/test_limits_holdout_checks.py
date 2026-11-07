# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Checks S1 to S3 of plan v4, on hand-made shifts only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import limits_holdout_checks as checks  # noqa: E402

ART = ROOT / "artifacts" / "ot-pilot"


def _policy(name, key):
    return checks.holdout.load_policy(ART / name, (ART / key).read_text().split())[0]


def _sp(t, loop, value):
    return {"t_min": t, "tool": "adjust_setpoint", "args": {"loop": loop, "value": value}}


SHIFT = {"shift_id": "s", "writes": [_sp(0, "FIC-220", 60.0), _sp(1, "FIC-220", 0.0),
                                     _sp(2, "PIC-101", 2.0), _sp(3, "FIC-220", 120.0)]}


def test_the_candidate_holds_every_check():
    out = checks.check([SHIFT], _policy("limits-v4/limits-candidate-v4.json",
                                        "limits-v4/limits-candidate-v4.trusted-key"))
    assert {k: (v["held"], v["writes"]) for k, v in out.items()} == \
        {"S1": (1, 1), "S2": (1, 1), "S3": (1, 1)}


def test_a_charged_ramp_down_fails_s3_under_v2():
    out = checks.check([SHIFT], _policy("limits-holdout-v2/limits-v2.json",
                                        "limits-holdout-v2/limits-v2.trusted-key"))
    assert out["S3"]["held"] == 0 and out["S3"]["failures"] == [{"shift_id": "s", "index": 0, "ok": False}]
    assert out["S1"]["held"] == 1
    assert out["S2"]["held"] == 0    # v2 has no exemption: PIC-101 is charged
