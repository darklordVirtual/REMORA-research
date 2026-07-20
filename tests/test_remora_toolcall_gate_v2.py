"""Leakage mutation tests for the v2 gate input contract.

2026-07 review finding #1: the gate previously read author-annotated oracle
flags (contains_prompt_injection, intent_arg_conflict, requires_human_approval,
fallback_contains_destructive, compliance_uncertain) plus task.severity and
task.tags — the benchmark answer key leaked into the system under test.

These tests FAIL if any of those inputs regain behavioral influence.
"""
from __future__ import annotations

import dataclasses

from remora.toolcall.benchmark_v2 import generate_benchmark_v2
from remora.toolcall.baselines import all_baselines
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.schema import ToolCallTask

ORACLE_CONTEXT_KEYS = (
    "contains_prompt_injection",
    "intent_arg_conflict",
    "requires_human_approval",
    "fallback_contains_destructive",
    "compliance_uncertain",
)


def _strip_oracle_signals(task: ToolCallTask) -> ToolCallTask:
    """Flip every oracle flag, randomize severity, and drop all tags."""
    ctx = dict(task.context or {})
    for key in ORACLE_CONTEXT_KEYS:
        if key in ctx:
            ctx[key] = not bool(ctx[key])
    flipped_severity = {"low": "critical", "medium": "high", "high": "medium", "critical": "low"}
    return dataclasses.replace(
        task,
        context=ctx,
        severity=flipped_severity[task.severity],  # type: ignore[arg-type]
        tags=(),
    )


def test_gate_ignores_oracle_flags_severity_and_tags() -> None:
    gate = RemoraToolCallGate()
    for task in generate_benchmark_v2(repeats=1):
        mutated = _strip_oracle_signals(task)
        assert gate.decide(task).action == gate.decide(mutated).action, (
            f"Gate decision for {task.task_id} depends on oracle flags, "
            "severity, or tags — label leakage re-introduced."
        )


def test_baselines_ignore_oracle_flags_severity_and_tags() -> None:
    for baseline in all_baselines():
        for task in generate_benchmark_v2(repeats=1):
            mutated = _strip_oracle_signals(task)
            assert baseline.decide(task).action == baseline.decide(mutated).action, (
                f"Baseline {baseline.name} decision for {task.task_id} depends "
                "on oracle flags, severity, or tags — label leakage."
            )


def test_gate_source_never_reads_severity_or_tags() -> None:
    """AST-adjacent guard: the v2 gate and baselines never access the fields."""
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    for rel in ("remora/toolcall/remora_gate.py", "remora/toolcall/baselines.py"):
        tree = ast.parse((repo / rel).read_text(encoding="utf-8"))
        offenders = [
            f"{rel}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in {"severity", "tags"}
        ]
        assert not offenders, f"severity/tags attribute access in gate layer: {offenders}"


def test_gate_blocks_safe_looking_dangerous_without_oracle_flags() -> None:
    tasks = [t for t in generate_benchmark_v2(repeats=1) if "safe_looking_dangerous" in t.tags]
    assert tasks
    gate = RemoraToolCallGate()
    for task in tasks:
        assert gate.decide(_strip_oracle_signals(task)).action != "EXECUTE"


def test_gate_derives_injection_conflict_and_fallback_from_surface() -> None:
    gate = RemoraToolCallGate()
    by_family = {
        "prompt_injection": "toolcall_derived_prompt_injection",
        "conflicting_intent": "toolcall_derived_intent_arg_conflict",
        "counterfactual_trap": "toolcall_derived_destructive_fallback",
    }
    for tag, _reason in by_family.items():
        tasks = [t for t in generate_benchmark_v2(repeats=1) if tag in t.tags]
        assert tasks, f"no benchmark tasks tagged {tag}"
        for task in tasks:
            decision = gate.decide(_strip_oracle_signals(task))
            assert decision.action == "ESCALATE", (
                f"{task.task_id} ({tag}): expected ESCALATE from surface-derived "
                f"detector, got {decision.action}"
            )


def test_gate_executes_safe_read_only_tasks() -> None:
    tasks = [t for t in generate_benchmark_v2(repeats=1) if "safe" in t.tags and "read_only" in t.tags]
    assert tasks
    gate = RemoraToolCallGate()
    for task in tasks:
        assert gate.decide(task).action == "EXECUTE", task.task_id
