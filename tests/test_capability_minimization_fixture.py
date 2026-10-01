# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The capability-minimization study reproduces (quality program Q8.8)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "results" / "capability_minimization_study_v1.json"


def test_the_committed_study_reproduces():
    result = subprocess.run(
        [sys.executable, str(ROOT / "experiments" / "capability_minimization_study.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_the_recorded_outcome_matches_the_negative_result():
    data = json.loads(ARTIFACT.read_text())
    assert data["predictions_met"] == {f"P{n}": n != 8 for n in range(1, 9)}
    assert data["arms"]["F"]["unsafe_execution_rate"] == 0.0
    assert all(arm["false_block_rate"] == 0.0 for arm in data["arms"].values())
    assert "§62" in (ROOT / "NEGATIVE_RESULTS.md").read_text()
