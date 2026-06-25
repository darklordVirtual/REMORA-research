from __future__ import annotations

import pytest

from experiments.evaluate_toolcall_benchmark_v2_live_exec import run


pytestmark = pytest.mark.live_replay_heavy


def test_live_exec_result_includes_execution_metrics_and_limitations() -> None:
    result = run(mode="replay")
    assert result["evaluation"] == "sandbox_live_execution"
    assert result["n_tasks"] >= 500
    assert "limitations" in result
    assert any("Sandbox execution" in item for item in result["limitations"])

    for metrics in result["baselines"].values():
        assert "execution_sandbox" in metrics
        sx = metrics["execution_sandbox"]
        assert "unsafe_effect_rate" in sx
        assert "execution_success_rate" in sx


def test_live_exec_remora_has_lower_unsafe_effect_than_majority_replay() -> None:
    result = run(mode="replay")
    remora = result["baselines"]["REMORA_full_policy_gate"]["execution_sandbox"]["unsafe_effect_rate"]
    majority = result["baselines"]["majority_vote_3_models"]["execution_sandbox"]["unsafe_effect_rate"]
    assert remora < majority
