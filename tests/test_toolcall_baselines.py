from __future__ import annotations

from remora.toolcall.baselines import all_baselines
from remora.toolcall.benchmark import generate_benchmark
from remora.toolcall.schema import VALID_ACTIONS


def test_all_baselines_are_deterministic() -> None:
    task = generate_benchmark()[0]
    for baseline in all_baselines():
        assert baseline.decide(task) == baseline.decide(task)


def test_all_baselines_emit_valid_actions() -> None:
    tasks = generate_benchmark()[:20]
    for baseline in all_baselines():
        for task in tasks:
            assert baseline.decide(task).action in VALID_ACTIONS
