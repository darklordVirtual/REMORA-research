from __future__ import annotations

from experiments.toolcall_v2_significance import run


def test_toolcall_v2_significance_contains_all_baselines() -> None:
    result = run()
    expected = {
        "single_model_heuristic",
        "majority_vote_heuristic",
        "self_consistency_heuristic",
        "verifier_heuristic",
        "remora_temperature_gate_heuristic",
    }
    assert set(result["comparisons"]) == expected


def test_toolcall_v2_significance_shows_positive_unsafe_delta_vs_single() -> None:
    result = run()
    single = result["comparisons"]["single_model_heuristic"]
    assert single["unsafe_execution_rate_delta_baseline_minus_remora"] > 0.0
    assert single["unsafe_rate_delta_ci95"][0] > 0.0
