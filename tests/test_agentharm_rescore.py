"""Tests for the AgentHarm rescoring with control protocols (P0-5)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "experiments" / "agentharm" / "rescore_with_protocols.py"
OUTPUT = Path(__file__).parent.parent / "artifacts" / "verify_protocols" / "agentharm_rescore_v1.json"


def test_rescore_script_exists():
    assert SCRIPT.exists(), f"Missing: {SCRIPT}"


def test_rescore_produces_valid_output():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, f"Exit {result.returncode}\n{result.stderr}"
    assert OUTPUT.exists()
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert data["schema"] == "agentharm_rescore_v1"
    assert data["n_harmful"] == 208
    assert data["n_benign"] == 208
    assert data["false_accept_rate"] == 0.0
    assert data["far_target_met"] is True
    assert "far_wilson_upper_95" in data
    assert "fbr_wilson_upper_95" in data


def test_rescore_fbr_target_not_met_is_honest():
    """The rescoring must honestly report that FBR target is not met
    without the resolution cascade introducing VERIFY before ESCALATE."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert data["fbr_target_met"] is False
    assert data["both_targets_met"] is False
    assert "negative result" in data["note"].lower()
