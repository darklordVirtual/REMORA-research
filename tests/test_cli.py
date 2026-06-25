"""Tests for remora CLI commands."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_remora_verify_exits_zero():
    """remora verify should run and exit 0 when all invariants pass."""
    result = subprocess.run(
        [sys.executable, "-m", "remora.cli", "verify"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_remora_verify_json_output():
    """remora verify --json should produce valid JSON with invariants_checked > 0."""
    result = subprocess.run(
        [sys.executable, "-m", "remora.cli", "verify", "--json"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "invariants_checked" in data or "total" in data
    checked = data.get("invariants_checked", data.get("total", 0))
    assert checked > 0
    failed = data.get("invariants_failed", data.get("total", 0) - data.get("passed", 0))
    assert failed == 0


def test_remora_maturity_exits_zero():
    """remora maturity should run without error."""
    result = subprocess.run(
        [sys.executable, "-m", "remora.cli", "maturity"],
        capture_output=True, text=True, cwd=ROOT,
    )
    # Exit code may be non-zero if many modules are unmarked, but should not crash
    assert result.returncode in {0, 1}, result.stderr
    assert "module" in result.stdout.lower() or "remora" in result.stdout.lower()
