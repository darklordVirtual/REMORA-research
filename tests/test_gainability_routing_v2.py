"""Tests for gainability_routing v2 (joined features experiment)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

V2_OUTPUT = Path("results/gainability_routing_v2.json")

# ---------------------------------------------------------------------------
# Ensure the experiment has been run and produced the output file.
# We run it lazily once as a module-level fixture so tests are fast.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def run_v2_experiment():
    """Run gainability_routing.py --v2 before the test suite if output missing."""
    if not V2_OUTPUT.exists():
        result = subprocess.run(
            [sys.executable, "experiments/gainability_routing.py", "--v2"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"gainability_routing.py --v2 failed:\n{result.stdout}\n{result.stderr}"
        )


def _load() -> dict:
    return json.loads(V2_OUTPUT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Output file exists
# ---------------------------------------------------------------------------
def test_v2_output_file_exists():
    assert V2_OUTPUT.exists(), f"{V2_OUTPUT} not found"


# ---------------------------------------------------------------------------
# 2. Required keys present
# ---------------------------------------------------------------------------
def test_v2_has_required_keys():
    data = _load()
    required = {
        "n_gainable_train",
        "n_gainable_test",
        "precision",
        "recall",
        "net_lift",
        "conclusion",
    }
    missing = required - set(data.keys())
    assert not missing, f"Missing keys: {missing}"


# ---------------------------------------------------------------------------
# 3. conclusion contains "not_demonstrated" (honest result)
# ---------------------------------------------------------------------------
def test_v2_conclusion_not_demonstrated():
    data = _load()
    assert "not_demonstrated" in data["conclusion"], (
        f"Expected 'not_demonstrated' in conclusion, got: {data['conclusion']!r}"
    )


# ---------------------------------------------------------------------------
# 4. net_lift is a float (or int, both numeric)
# ---------------------------------------------------------------------------
def test_v2_net_lift_is_numeric():
    data = _load()
    assert isinstance(data["net_lift"], (int, float))


# ---------------------------------------------------------------------------
# 5. feature_coverage is a dict
# ---------------------------------------------------------------------------
def test_v2_feature_coverage_is_dict():
    data = _load()
    assert "feature_coverage" in data
    assert isinstance(data["feature_coverage"], dict)
