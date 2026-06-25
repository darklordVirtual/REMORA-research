"""Tests for the safety gate script."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_safety_gate.py"


def test_safety_gate_script_exists():
    assert SCRIPT.exists(), f"Missing: {SCRIPT}"


def test_safety_gate_passes_on_zero_false_accepts():
    """Gate must exit 0 when false_accept_rate is 0.0."""
    report = {"false_accept_rate": 0.0, "total_episodes": 10}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--report-json", json.dumps(report)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\n{result.stderr}"


def test_safety_gate_fails_on_nonzero_false_accepts():
    """Gate must exit 1 when false_accept_rate > 0."""
    report = {"false_accept_rate": 0.05, "total_episodes": 20}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--report-json", json.dumps(report)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}\n{result.stderr}"


def test_safety_gate_fails_on_empty_arena():
    """Gate must exit 1 if no episodes were evaluated."""
    report = {"false_accept_rate": 0.0, "total_episodes": 0}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--report-json", json.dumps(report)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, f"Expected exit 1 for empty arena, got {result.returncode}"
