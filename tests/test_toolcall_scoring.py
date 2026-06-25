from __future__ import annotations

from remora.toolcall.benchmark import generate_benchmark
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.schema import ToolCallDecision
from remora.toolcall.simulators import simulate


def test_scoring_metrics_sum_correctly() -> None:
    tasks = generate_benchmark()
    outcomes = [simulate(t, ToolCallDecision(action=t.ground_truth_action, confidence=0.8)) for t in tasks]
    metrics = aggregate_metrics(tasks, outcomes)
    assert metrics["n_tasks"] == len(tasks)
    assert metrics["accuracy"] == 1.0
    assert metrics["unsafe_execution_count"] == 0


def test_action_confusion_matrix_is_valid() -> None:
    tasks = generate_benchmark()
    outcomes = [simulate(t, ToolCallDecision(action=t.ground_truth_action, confidence=0.8)) for t in tasks]
    matrix = aggregate_metrics(tasks, outcomes)["action_confusion_matrix"]
    assert set(matrix) == {"EXECUTE", "VERIFY", "ABSTAIN", "ESCALATE"}
    assert sum(sum(row.values()) for row in matrix.values()) == len(tasks)


def test_regulatory_domain_metrics_exist() -> None:
    tasks = generate_benchmark()
    outcomes = [simulate(t, ToolCallDecision(action=t.ground_truth_action, confidence=0.8)) for t in tasks]
    metrics = aggregate_metrics(tasks, outcomes)
    assert "utility_by_regulatory_domain" in metrics
    assert "unsafe_execution_by_regulatory_domain" in metrics
    assert metrics["utility_by_regulatory_domain"]
