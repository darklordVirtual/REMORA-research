# SPDX-License-Identifier: BUSL-1.1
"""Defences (SAP v7 §4): each decides whether one proposed tool call may run.

A defence sees a :class:`ProposedCall` and returns a :class:`Verdict`. The
agent's call executes only when ``verdict.execute`` is true. ``score`` is the
graded signal a defence exposes for the per-call ROC analysis (Q3): higher
means more suspicious. Defences without a graded signal give 0 or 100.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

#: Decision reasons that state an affirmative fault in the call, frozen at seal
#: time (SAP v7 §5). A floor that may only tighten blocks on these and on
#: nothing else. Reasons that record missing evidence (UNKNOWN goal fit,
#: ungrounded values, unverified schema) are not in the list: they say the
#: call is not shown safe, not that it is shown unsafe.
HARD_GUARD_REASONS = frozenset({
    "admission_firewall_blocked",
    "malformed_call_blocked",
    "forbidden_tool_blocked",
    "cross_tenant_argument_blocked",
    "tool_does_not_match_goal",
    "expected_effect_contradicted",
    "tainted_argument_verify",
    "tainted_argument_escalate",
    "untrusted_controls_sensitive_argument",
    "coercion_blocked",
    "blackmail_blocked",
    "invariant_violation_escalate",
    "tool_not_in_available_set",
    "capability_not_allowed",
    "loop_safety_escalate",
    "flow_state_unavailable",
    "flow_context_unknown",
    "flow_handle_invalid",
    "toolspec_flow_policy_missing",
    "flow_confidentiality_violation",
    "flow_integrity_violation_verify",
    "flow_integrity_violation_escalate",
})


@dataclass(frozen=True)
class ToolSpec:
    """What the environment declares about one tool."""

    name: str
    description: str = ""
    required: tuple[str, ...] = ()
    effect: str | None = None  # "read", "write" or undeclared


@dataclass(frozen=True)
class ProposedCall:
    """One tool call the untrusted agent proposed, with the context a defence may see."""

    user_task: str
    name: str
    args: Mapping[str, Any]
    tools: tuple[ToolSpec, ...]
    #: Text of every earlier tool output in the trajectory, oldest first.
    prior_outputs: tuple[str, ...] = ()
    suite: str = ""
    user_task_id: str = ""
    injection_task_id: str | None = None


@dataclass(frozen=True)
class Verdict:
    execute: bool
    score: float
    reason: str
    detail: Mapping[str, Any] = field(default_factory=dict)


class Defence(Protocol):
    name: str

    def decide(self, call: ProposedCall) -> Verdict: ...


class NoGate:
    name = "A_none"

    def decide(self, call: ProposedCall) -> Verdict:
        return Verdict(True, 0.0, "no_gate")


class RefuseAll:
    name = "B_refuse_all"

    def decide(self, call: ProposedCall) -> Verdict:
        return Verdict(False, 100.0, "refuse_all")


class TaskAllowlist:
    """Execute only tools that appear in the user task's ground-truth calls.

    Uses knowledge a deployment would not have; a reference point (SAP v7 §4).
    """

    name = "C_allowlist"

    def __init__(self, allowed: Mapping[str, Iterable[str]]) -> None:
        self._allowed = {task: frozenset(tools) for task, tools in allowed.items()}

    def decide(self, call: ProposedCall) -> Verdict:
        ok = call.name in self._allowed.get(call.user_task_id, frozenset())
        return Verdict(ok, 0.0 if ok else 100.0, "allowlisted" if ok else "not_allowlisted")


class LLMMonitor:
    """A model scores each call 0 (benign) to 100 (attack); execute below the threshold.

    The scorer is injected, so the policy is tested without a model; the
    AgentDojo glue supplies one that calls the API under the budget guard.
    """

    name = "D_monitor"

    def __init__(self, scorer: Callable[[ProposedCall], float], threshold: float) -> None:
        self._scorer = scorer
        self.threshold = threshold

    def decide(self, call: ProposedCall) -> Verdict:
        score = float(self._scorer(call))
        if not 0.0 <= score <= 100.0:
            raise ValueError(f"monitor score {score} outside [0, 100]")
        ok = score < self.threshold
        return Verdict(ok, score, "monitor_allow" if ok else "monitor_block")


class FloorTightens:
    """Arm F: block on a REMORA hard-guard reason, otherwise the monitor decides."""

    name = "F_floor_tightens"

    def __init__(self, remora: Defence, monitor: LLMMonitor) -> None:
        self._remora, self._monitor = remora, monitor

    def decide(self, call: ProposedCall) -> Verdict:
        floor = self._remora.decide(call)
        if floor.reason in HARD_GUARD_REASONS:
            return Verdict(False, 100.0, f"floor:{floor.reason}")
        return self._monitor.decide(call)


class BothAccept:
    """Arm G: execute only when REMORA and the monitor both execute."""

    name = "G_both_accept"

    def __init__(self, remora: Defence, monitor: LLMMonitor) -> None:
        self._remora, self._monitor = remora, monitor

    def decide(self, call: ProposedCall) -> Verdict:
        floor = self._remora.decide(call)
        mon = self._monitor.decide(call)
        score = 100.0 if not floor.execute else mon.score
        return Verdict(floor.execute and mon.execute, max(score, mon.score),
                       f"remora:{floor.reason}|{mon.reason}")
