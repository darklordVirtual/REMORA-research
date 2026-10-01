# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The pre-registered capability-mediation study reproduces (NTA-2, EXP-CAPABILITY-MEDIATION-01)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "results" / "authority_preserving_capability_mediation_v1.json"


def test_the_committed_study_reproduces():
    result = subprocess.run(
        [sys.executable, str(ROOT / "experiments" / "authority_preserving_capability_mediation.py"),
         "--check"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_the_recorded_outcome_matches_the_negative_result():
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert data["predictions_met"] == {f"P{n}": n != 6 for n in range(1, 9)}
    assert data["arms"]["C"]["unauthorized_effect_rate"] == 0.0
    assert data["arms"]["C"]["tool_process_separate"] is True
    assert data["arms"]["C"]["ambient_effect_authority_surface"] == 0
    assert data["arms"]["B"]["stopped_by_class"]["direct_sdk_access"] == "0/4"
    assert "§63" in (ROOT / "NEGATIVE_RESULTS.md").read_text(encoding="utf-8")


def test_arm_c_is_not_an_in_process_simulation():
    """The registration forbids substituting a simulation for arm C."""
    source = (ROOT / "experiments" / "authority_preserving_capability_mediation.py").read_text(encoding="utf-8")
    assert "subprocess.Popen" in source and "--worker" in source and "--effect-domain" in source
