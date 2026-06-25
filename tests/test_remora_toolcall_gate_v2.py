from __future__ import annotations

from remora.toolcall.benchmark_v2 import generate_benchmark_v2
from remora.toolcall.remora_gate import RemoraToolCallGate


def test_context_overrides_block_safe_looking_dangerous_executes() -> None:
    task = next(t for t in generate_benchmark_v2() if "safe_looking_dangerous" in t.tags)
    with_context = RemoraToolCallGate(use_context_overrides=True).decide(task)
    without_context = RemoraToolCallGate(use_context_overrides=False).decide(task)
    assert with_context.action in {"VERIFY", "ABSTAIN", "ESCALATE"}
    assert with_context.action != "EXECUTE"
    assert without_context.action == "EXECUTE"
