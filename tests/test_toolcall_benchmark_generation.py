from __future__ import annotations

from remora.toolcall.benchmark import benchmark_to_json, generate_benchmark
from remora.toolcall.schema import VALID_ACTIONS, VALID_DOMAINS


def test_benchmark_generation_is_deterministic() -> None:
    first = benchmark_to_json(generate_benchmark())
    second = benchmark_to_json(generate_benchmark())
    assert first == second


def test_benchmark_has_at_least_200_tasks() -> None:
    tasks = generate_benchmark()
    assert len(tasks) >= 200


def test_every_task_has_valid_action_and_domain() -> None:
    for task in generate_benchmark():
        assert task.ground_truth_action in VALID_ACTIONS
        assert task.domain in VALID_DOMAINS
        task.validate()
