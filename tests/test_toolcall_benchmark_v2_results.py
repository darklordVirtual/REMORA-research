from __future__ import annotations

from experiments.evaluate_toolcall_benchmark_v2 import run


def test_toolcall_v2_result_includes_all_baselines() -> None:
    result = run()
    expected = {
        "single_model_heuristic",
        "majority_vote_heuristic",
        "self_consistency_heuristic",
        "verifier_heuristic",
        "remora_temperature_gate_heuristic",
        "remora_full_policy_gate",
    }
    assert set(result["baselines"]) == expected


def test_toolcall_v2_has_nonzero_unsafe_for_at_least_one_baseline() -> None:
    result = run()
    unsafe_rates = [m["unsafe_execution_rate"] for m in result["baselines"].values()]
    assert any(rate > 0.0 for rate in unsafe_rates)


def test_toolcall_v2_remora_reduces_unsafe_vs_single_model() -> None:
    result = run()
    remora = result["baselines"]["remora_full_policy_gate"]["unsafe_execution_rate"]
    single = result["baselines"]["single_model_heuristic"]["unsafe_execution_rate"]
    assert remora < single
