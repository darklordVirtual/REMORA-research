# Author: Stian Skogbrott
# License: Apache-2.0
"""Mutation tests for M1 label leakage absence.

These tests FAIL if evaluation-only fields re-enter the runtime gate.
Implements intern_forbedring.txt §2: 'Add negative mutation tests for leakage.'

Three invariants:
  1. Gate observation is identical regardless of is_unsafe_if_executed value.
  2. Gate observation is identical regardless of use_contradiction_flags value.
  3. AST scan of runtime packages detects zero evaluation field references.
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path


from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.schema import ToolCallTask

REPO_ROOT = Path(__file__).resolve().parents[1]


def _task_pair(base_task: ToolCallTask) -> tuple[ToolCallTask, ToolCallTask]:
    """Return (task with is_unsafe=False, task with is_unsafe=True), all else equal."""
    d = dataclasses.asdict(base_task)
    safe = dataclasses.replace(base_task, **{k: v for k, v in d.items()})
    safe = dataclasses.replace(safe, is_unsafe_if_executed=False)
    unsafe = dataclasses.replace(base_task, is_unsafe_if_executed=True)
    return safe, unsafe


class TestM1LeakageAbsent:
    """Invariant: gate observation must not depend on is_unsafe_if_executed."""

    def _obs_dict(self, task: ToolCallTask, gate: RemoraToolCallGate) -> dict:
        obs = gate.to_observation(task)
        return dataclasses.asdict(obs)

    def test_unsafe_flag_does_not_change_observation_default_gate(self):
        """Main M1 mutation: flipping is_unsafe_if_executed must not affect observation."""
        gate = RemoraToolCallGate()
        tasks = load_benchmark_v2()[:20]
        for task in tasks:
            safe, unsafe = _task_pair(task)
            obs_safe = self._obs_dict(safe, gate)
            obs_unsafe = self._obs_dict(unsafe, gate)
            assert obs_safe == obs_unsafe, (
                f"Gate observation differs for task '{task.name}' based on "
                f"is_unsafe_if_executed — M1 leakage re-introduced. "
                f"Diff keys: {[k for k in obs_safe if obs_safe[k] != obs_unsafe.get(k)]}"
            )

    def test_unsafe_flag_does_not_change_observation_contradiction_flags_off(self):
        """Leakage must also be absent when use_contradiction_flags=False."""
        gate = RemoraToolCallGate(use_contradiction_flags=False)
        tasks = load_benchmark_v2()[:20]
        for task in tasks:
            safe, unsafe = _task_pair(task)
            assert self._obs_dict(safe, gate) == self._obs_dict(unsafe, gate)

    def test_contradiction_flags_toggle_has_no_observable_effect(self):
        """use_contradiction_flags must be a no-op (it was removed in M1 fix).

        If this test fails, it means use_contradiction_flags still has a
        behavioral effect in the gate — which is only possible if the
        is_unsafe_if_executed branch was re-introduced.
        """
        gate_on = RemoraToolCallGate(use_contradiction_flags=True)
        gate_off = RemoraToolCallGate(use_contradiction_flags=False)
        tasks = load_benchmark_v2()[:30]
        for task in tasks:
            obs_on = dataclasses.asdict(gate_on.to_observation(task))
            obs_off = dataclasses.asdict(gate_off.to_observation(task))
            assert obs_on == obs_off, (
                f"use_contradiction_flags changes gate observation for '{task.name}' — "
                f"M1 leakage re-introduced. Diff: {[k for k in obs_on if obs_on[k] != obs_off.get(k)]}"
            )


class TestM1ASTLeakageAbsent:
    """AST-level invariant: runtime packages must not import evaluation fields."""

    def test_ast_leakage_detector_passes(self):
        """The CI leakage detector must return exit code 0.

        If this fails, an evaluation-only field has been re-introduced into
        a runtime package. Run `python scripts/check_no_evaluation_leakage.py`
        for the exact location.
        """
        script = REPO_ROOT / "scripts" / "check_no_evaluation_leakage.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"AST leakage detector found evaluation field(s) in runtime code:\n"
            f"{result.stdout}\n{result.stderr}"
        )
