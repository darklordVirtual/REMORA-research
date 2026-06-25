from __future__ import annotations

from remora.toolcall.benchmark import generate_benchmark
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.schema import ToolCallTask


def test_remora_toolcall_gate_never_executes_critical_destructive_tasks() -> None:
    gate = RemoraToolCallGate()
    critical = [
        t for t in generate_benchmark()
        if t.severity == "critical" and t.is_unsafe_if_executed
    ]
    assert critical
    for task in critical:
        assert gate.decide(task).action != "EXECUTE"


def test_remora_toolcall_gate_executes_safe_readonly_task() -> None:
    task = next(t for t in generate_benchmark() if t.ground_truth_action == "EXECUTE")
    decision = RemoraToolCallGate().decide(task)
    assert decision.action == "EXECUTE"


def test_gate_does_not_depend_on_ground_truth_action() -> None:
    template = next(t for t in generate_benchmark() if "legal" in t.tags and t.severity == "high")
    a = template
    b = ToolCallTask(
        task_id=f"{template.task_id}_alt",
        domain=template.domain,
        user_request=template.user_request,
        proposed_tool_name=template.proposed_tool_name,
        proposed_tool_args=dict(template.proposed_tool_args),
        context=dict(template.context),
        ground_truth_action="ABSTAIN",
        is_unsafe_if_executed=template.is_unsafe_if_executed,
        is_useful_if_executed=template.is_useful_if_executed,
        expected_failure_mode=template.expected_failure_mode,
        explanation=template.explanation,
        severity=template.severity,
        tags=template.tags,
    )
    gate = RemoraToolCallGate()
    assert gate.decide(a).action == gate.decide(b).action
