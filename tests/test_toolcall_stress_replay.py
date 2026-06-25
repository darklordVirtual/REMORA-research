from __future__ import annotations

from experiments.toolcall_stress_replay import build_stress_tasks, run_stress_evaluation


def test_build_stress_tasks_has_requested_volume_and_unique_ids() -> None:
    tasks = build_stress_tasks(n_calls=1500, seed=7)
    assert len(tasks) == 1500
    ids = {t.id for t in tasks}
    assert len(ids) == 1500


def test_run_stress_evaluation_returns_expected_structure() -> None:
    payload = run_stress_evaluation(n_calls=1200, seed=1)

    assert payload["n_calls"] == 1200
    assert "baselines" in payload
    assert "remora_full_policy_gate_v3" in payload["baselines"]
    assert "naive_tool_caller" in payload["baselines"]

    remora = payload["baselines"]["remora_full_policy_gate_v3"]
    assert "metrics" in remora
    assert "governance_metrics" in remora
    assert "performance" in remora

    assert "unsafe_execution_rate" in remora["metrics"]
    assert "human_review_burden_pct" in remora["governance_metrics"]
    assert "decisions_per_second" in remora["performance"]


def test_remora_unsafe_rate_not_worse_than_naive_on_stress_sample() -> None:
    payload = run_stress_evaluation(n_calls=1200, seed=3)
    remora_unsafe = payload["baselines"]["remora_full_policy_gate_v3"]["metrics"]["unsafe_execution_rate"]
    naive_unsafe = payload["baselines"]["naive_tool_caller"]["metrics"]["unsafe_execution_rate"]
    assert remora_unsafe <= naive_unsafe
