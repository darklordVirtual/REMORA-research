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


def test_disambiguated_metric_denominators() -> None:
    """Research audit P0-4: every rate must name its denominator. The legacy
    all-tasks false_accept_rate stays for artifact compatibility, but the
    harmful-conditioned FAR, safe-EXECUTE block rate and benign review
    friction are reported explicitly and must agree with first principles."""
    tasks = generate_benchmark()
    n = len(tasks)
    n_harmful = sum(1 for t in tasks if t.is_unsafe_if_executed)
    n_benign = n - n_harmful
    n_safe_execute = sum(
        1 for t in tasks
        if t.ground_truth_action == "EXECUTE"
        and t.is_useful_if_executed and not t.is_unsafe_if_executed
    )

    all_exec = [simulate(t, ToolCallDecision(action="EXECUTE", confidence=0.8)) for t in tasks]
    m = aggregate_metrics(tasks, all_exec)
    assert m["n_harmful"] == n_harmful
    assert m["n_benign"] == n_benign
    # Legacy rate is per all tasks; harmful-conditioned rate per harmful only.
    assert m["false_accept_rate"] == m["false_accept_count"] / n
    assert m["false_accept_rate_harmful"] == m["false_accept_count"] / n_harmful
    # Everything executed: zero benign task is routed to review.
    assert m["review_friction_benign"] == 0.0
    assert m["safe_execute_block_rate"] == 0.0

    all_esc = [simulate(t, ToolCallDecision(action="ESCALATE", confidence=0.8)) for t in tasks]
    m2 = aggregate_metrics(tasks, all_esc)
    assert m2["false_accept_rate_harmful"] == 0.0
    # Everything escalated: every benign task is friction, every safe
    # useful EXECUTE task is blocked.
    assert m2["review_friction_benign"] == 1.0
    assert m2["safe_execute_block_rate"] == 1.0
    assert m2["n_safe_execute"] == n_safe_execute


def test_regulatory_domain_metrics_exist() -> None:
    tasks = generate_benchmark()
    outcomes = [simulate(t, ToolCallDecision(action=t.ground_truth_action, confidence=0.8)) for t in tasks]
    metrics = aggregate_metrics(tasks, outcomes)
    assert "utility_by_regulatory_domain" in metrics
    assert "unsafe_execution_by_regulatory_domain" in metrics
    assert metrics["utility_by_regulatory_domain"]
