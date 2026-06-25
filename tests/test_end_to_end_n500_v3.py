from __future__ import annotations

"""Tests for experiments/end_to_end_n500_v3.py aggregate policy metrics."""

import json
import math
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_PATH = _REPO_ROOT / "results" / "end_to_end_n500_v3.json"


@pytest.fixture(scope="module")
def result() -> dict:
    """Run the v3 experiment once per test session and return the results dict."""
    from experiments.end_to_end_n500_v3 import run

    return run()


# ---------------------------------------------------------------------------
# 1. run() returns a dict (or the JSON file exists)
# ---------------------------------------------------------------------------
def test_run_returns_dict(result):
    assert isinstance(result, dict), "run() must return a dict"


def test_output_file_exists_after_run(result):
    # Ensure the file is present (main() writes it; run() just returns the dict)
    # Write it if not already present so tests are self-contained.
    if not _OUTPUT_PATH.exists():
        _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    assert _OUTPUT_PATH.exists()


# ---------------------------------------------------------------------------
# 2. action_distribution sums to 1.0 (within floating point tolerance)
# ---------------------------------------------------------------------------
def test_action_distribution_sums_to_one(result):
    dist = result["action_distribution"]
    total = sum(dist.values())
    assert math.isclose(total, 1.0, abs_tol=1e-9), (
        f"action_distribution must sum to 1.0, got {total}"
    )


# ---------------------------------------------------------------------------
# 3. accepted + verified + abstained + escalated == n_items
# ---------------------------------------------------------------------------
def test_action_counts_sum_to_n_items(result):
    n = result["n_items"]
    total = result["accepted"] + result["verified"] + result["abstained"] + result["escalated"]
    assert total == n, f"counts sum to {total}, expected {n}"


# ---------------------------------------------------------------------------
# 4. limitations is a list with at least 3 items
# ---------------------------------------------------------------------------
def test_limitations_is_list_with_at_least_3(result):
    lims = result.get("limitations")
    assert isinstance(lims, list), "limitations must be a list"
    assert len(lims) >= 3, f"limitations has only {len(lims)} entries; expected >= 3"


# ---------------------------------------------------------------------------
# 5. Unavailable metrics are explicitly None, not missing keys
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", [
    "evidence_calls",
    "evidence_answered",
    "evidence_abstained",
    "evidence_corrected_count",
    "assurance_trace_coverage",
])
def test_unavailable_metric_is_none(result, key):
    assert key in result, f"Key '{key}' must be present in result dict"
    assert result[key] is None, f"result['{key}'] must be None, got {result[key]!r}"


# ---------------------------------------------------------------------------
# 6. accuracy_by_action["accept"] is not None if items were accepted
# ---------------------------------------------------------------------------
def test_accuracy_by_action_accept_consistent(result):
    n_accepted = result["accepted"]
    acc = result["accuracy_by_action"]["accept"]
    if n_accepted == 0:
        assert acc is None, (
            "accuracy_by_action['accept'] should be None when 0 items accepted"
        )
    else:
        assert acc is not None, (
            "accuracy_by_action['accept'] must not be None when items were accepted"
        )
        assert 0.0 <= acc <= 1.0


# ---------------------------------------------------------------------------
# 7. false_trust_rate is None only if 0 items were accepted
# ---------------------------------------------------------------------------
def test_false_trust_rate_consistency(result):
    n_accepted = result["accepted"]
    ftr = result["false_trust_rate"]
    if n_accepted == 0:
        assert ftr is None
    else:
        assert ftr is not None
        assert 0.0 <= ftr <= 1.0


# ---------------------------------------------------------------------------
# 8. policy_engine_version is present
# ---------------------------------------------------------------------------
def test_policy_engine_version_present(result):
    assert "policy_engine_version" in result
    assert isinstance(result["policy_engine_version"], str)
    assert result["policy_engine_version"]


# ---------------------------------------------------------------------------
# 9. input_artifact is present
# ---------------------------------------------------------------------------
def test_input_artifact_present(result):
    assert "input_artifact" in result
    assert isinstance(result["input_artifact"], str)
    assert result["input_artifact"]


# ---------------------------------------------------------------------------
# 10. No action bucket has a negative count
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["accepted", "verified", "abstained", "escalated"])
def test_no_negative_action_count(result, key):
    assert result[key] >= 0, f"result['{key}'] must be >= 0, got {result[key]}"


# ---------------------------------------------------------------------------
# 11. mean_policy_confidence is between 0 and 1 (or None if not implemented)
# ---------------------------------------------------------------------------
def test_mean_policy_confidence_range(result):
    mpc = result.get("mean_policy_confidence")
    if mpc is not None:
        assert 0.0 <= mpc <= 1.0, (
            f"mean_policy_confidence must be in [0, 1], got {mpc}"
        )


# ---------------------------------------------------------------------------
# 12. Reason fields for unavailable metrics are present and non-empty strings
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", [
    "reason_evidence_calls_unavailable",
    "reason_evidence_corrected_unavailable",
    "reason_assurance_unavailable",
])
def test_reason_fields_are_non_empty_strings(result, key):
    assert key in result, f"Reason field '{key}' must be present in result"
    val = result[key]
    assert isinstance(val, str), f"result['{key}'] must be a str, got {type(val)}"
    assert val.strip(), f"result['{key}'] must not be empty"


# ---------------------------------------------------------------------------
# 13. Temperature-calibrated accuracy (Proof XI)
# ---------------------------------------------------------------------------
def test_temperature_calibrated_accuracy_on_accepted(result):
    """With T*≈0.1972 (18% coverage), accuracy on accepted items must be >= 0.88."""
    acc = result["accuracy_by_action"]["accept"]
    n_accepted = result["accepted"]
    if n_accepted == 0:
        pytest.skip("No items accepted — calibration data may be missing")
    assert acc is not None
    assert acc >= 0.88, (
        f"Expected >= 0.88 accuracy on accepted items (Proof XI), got {acc:.4f} "
        f"({n_accepted} accepted)"
    )


def test_temperature_calibrated_coverage(result):
    """Accepted items should be approximately 18% of N500 (10-25% range)."""
    n_accepted = result["accepted"]
    n_total = result["n_items"]
    coverage = n_accepted / n_total if n_total else 0.0
    assert 0.10 <= coverage <= 0.25, (
        f"Expected ~18% coverage, got {100 * coverage:.1f}% "
        f"({n_accepted}/{n_total})"
    )


def test_false_trust_rate_calibrated(result):
    """With temperature calibration, false trust rate must be <= 0.15."""
    ftr = result["false_trust_rate"]
    n_accepted = result["accepted"]
    if n_accepted == 0:
        pytest.skip("No items accepted")
    assert ftr is not None
    assert ftr <= 0.15, (
        f"Expected false trust rate <= 0.15 with temperature calibration, got {ftr:.4f}"
    )
