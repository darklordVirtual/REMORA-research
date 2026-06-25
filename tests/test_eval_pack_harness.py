"""Tests that the eval_pack validation harness runs correctly."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_validation_exits_zero():
    """eval_pack/run_validation.py --dry-run should exit 0."""
    result = subprocess.run(
        [sys.executable, "eval_pack/run_validation.py", "--dry-run"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_run_validation_dry_run_produces_json():
    result = subprocess.run(
        [sys.executable, "eval_pack/run_validation.py", "--dry-run", "--json"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "passed" in data
    assert "total" in data
    assert data["total"] > 0


def test_run_validation_all_scenarios_pass():
    result = subprocess.run(
        [sys.executable, "eval_pack/run_validation.py", "--json"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["passed"] == data["total"], (
        f"Some scenarios failed: {[r for r in data['results'] if not r['passed']]}"
    )
