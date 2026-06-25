from __future__ import annotations

from experiments.evaluate_toolcall_benchmark import run


def test_result_json_includes_all_baselines() -> None:
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


def test_result_json_includes_limitations() -> None:
    result = run()
    assert "limitations" in result
    assert any("no live LLM" in item for item in result["limitations"])
