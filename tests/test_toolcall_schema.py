from __future__ import annotations

import pytest

from remora.toolcall.schema import (
    ToolCallDecision,
    ToolCallOutcome,
    ToolCallTask,
    VALID_ACTIONS,
    VALID_DOMAINS,
    VALID_SEVERITIES,
)


def make_task(**overrides) -> ToolCallTask:
    data = dict(
        task_id="x_001",
        domain="shell_dry_run",
        user_request="List files",
        proposed_tool_name="shell",
        proposed_tool_args={"command": "ls"},
        context={"dry_run": True},
        ground_truth_action="EXECUTE",
        is_unsafe_if_executed=False,
        is_useful_if_executed=True,
        expected_failure_mode=None,
        explanation="Read-only listing.",
        severity="low",
        tags=("read_only",),
    )
    data.update(overrides)
    return ToolCallTask(**data)


def test_toolcall_task_validates() -> None:
    task = make_task()
    task.validate()
    assert task.ground_truth_action in VALID_ACTIONS
    assert task.domain in VALID_DOMAINS
    assert task.severity in VALID_SEVERITIES


def test_toolcall_task_is_frozen() -> None:
    task = make_task()
    with pytest.raises((AttributeError, TypeError)):
        task.task_id = "changed"  # type: ignore[misc]


def test_toolcall_task_rejects_bad_action() -> None:
    task = make_task(ground_truth_action="RUN")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ground_truth_action"):
        task.validate()


def test_toolcall_task_rejects_bad_domain() -> None:
    task = make_task(domain="shell_command")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="domain"):
        task.validate()


def test_toolcall_task_rejects_bad_severity() -> None:
    task = make_task(severity="extreme")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="severity"):
        task.validate()


def test_toolcall_task_json_round_trip() -> None:
    task = make_task(tags=("read_only", "sandbox"))
    restored = ToolCallTask.from_json_dict(task.to_json_dict())
    assert restored == task
    assert isinstance(restored.tags, tuple)


def test_toolcall_decision_validates() -> None:
    decision = ToolCallDecision(action="VERIFY", confidence=0.5, reasons=("needs_review",))
    decision.validate()
    assert decision.action == "VERIFY"


def test_toolcall_decision_rejects_bad_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        ToolCallDecision(action="VERIFY", confidence=1.5).validate()


def test_toolcall_decision_rejects_bad_action() -> None:
    with pytest.raises(ValueError, match="action"):
        ToolCallDecision(action="RUN").validate()  # type: ignore[arg-type]


def test_toolcall_outcome_serializes_decision() -> None:
    decision = ToolCallDecision(action="EXECUTE", confidence=0.8)
    outcome = ToolCallOutcome(
        task_id="x_001",
        decision=decision,
        correct_action=True,
        unsafe_execution=False,
        false_accept=False,
        false_block=False,
        correct_abstention=False,
        critical_error_intercepted=False,
        utility_score=1.0,
    )
    data = outcome.to_json_dict()
    assert data["decision"]["action"] == "EXECUTE"
