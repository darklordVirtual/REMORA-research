from __future__ import annotations

from remora.toolcall.benchmark_v2 import benchmark_to_json_v2, generate_benchmark_v2
from remora.toolcall.schema import VALID_ACTIONS, VALID_DOMAINS


def test_benchmark_v2_generation_is_deterministic() -> None:
    first = benchmark_to_json_v2(generate_benchmark_v2())
    second = benchmark_to_json_v2(generate_benchmark_v2())
    assert first == second


def test_benchmark_v2_has_at_least_400_tasks() -> None:
    tasks = generate_benchmark_v2()
    assert len(tasks) >= 400


def test_benchmark_v2_every_task_has_valid_action_and_domain() -> None:
    for task in generate_benchmark_v2():
        assert task.ground_truth_action in VALID_ACTIONS
        assert task.domain in VALID_DOMAINS
        task.validate()
