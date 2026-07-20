from __future__ import annotations

import pytest

from experiments.toolcall_v2_significance import run


@pytest.fixture(scope="module")
def result() -> dict:
    return run()


def test_toolcall_v2_significance_contains_all_baselines(result: dict) -> None:
    expected = {
        "single_model_heuristic",
        "majority_vote_heuristic",
        "self_consistency_heuristic",
        "verifier_heuristic",
        "remora_temperature_gate_heuristic",
    }
    assert set(result["comparisons"]) == expected


def test_toolcall_v2_significance_uses_cluster_level_inference(result: dict) -> None:
    """REM-038: inference must run over template clusters, not duplicated tasks."""
    assert result["n_template_clusters"] == 70
    assert result["n_tasks"] == 700
    assert result["method"]["cluster_definition"].startswith("domain x scenario_family")


def test_toolcall_v2_unsafe_delta_reported_honestly(result: dict) -> None:
    """The unsafe-rate delta vs baselines is small and NOT significant (p=0.50).

    This test pins the honest post-REM-038 state. If the delta becomes
    significant again, that is a real finding — update this test together with
    README/claim register, never silently.
    """
    single = result["comparisons"]["single_model_heuristic"]
    assert single["unsafe_execution_rate_delta_baseline_minus_remora"] >= 0.0
    assert single["unsafe_rate_delta_ci95"][0] >= 0.0
    assert single["unsafe_rate_delta_pvalue_one_sided"] > 0.05  # not significant
    # The utility delta IS the statistically supported advantage.
    assert single["utility_delta_remora_minus_baseline"] > 0.3
    assert single["utility_delta_pvalue_one_sided"] < 0.001


def test_toolcall_v2_remora_unsafe_rate_zero_with_cluster_ci(result: dict) -> None:
    unsafe = result["remora_unsafe_rate"]
    assert unsafe["task_level_point_estimate"] == 0.0
    assert unsafe["unsafe_template_clusters"] == 0
    lo, hi = unsafe["cluster_level_wilson_ci95"]
    assert lo == 0.0
    assert 0.04 < hi < 0.07  # ~5.2% at n=70; task-level 0.55% would fail here
