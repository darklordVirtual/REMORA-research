from __future__ import annotations

from experiments.evaluate_toolcall_benchmark_v2 import run as run_v2_heuristic
from experiments.toolcall_v2_calibration_blind import run as run_v2_calibration_blind


def test_toolcall_v2_heuristic_has_expected_fields() -> None:
    result = run_v2_heuristic()
    assert result["n_tasks"] >= 500
    remora = result["baselines"]["remora_full_policy_gate"]
    for key in (
        "unsafe_execution_rate",
        "unsafe_execution_reduction_vs_majority",
        "critical_error_intercept_rate",
        "false_accept_rate",
        "false_block_rate",
        "execute_precision",
        "execute_recall",
        "mean_utility",
        "utility_delta_vs_best_baseline",
        "abstain_rate",
        "verify_rate",
        "escalate_rate",
    ):
        assert key in remora


def test_toolcall_v2_blind_split_is_ood_and_has_expected_ratio() -> None:
    calibration, blind = run_v2_calibration_blind()
    counts = calibration["split_counts"]
    assert counts["total"] >= 500
    assert 0.45 <= counts["blind_test_pct"] <= 0.55
    assert set(calibration["blind_families"])
    assert blind["evaluation_split"] == "blind_test"
