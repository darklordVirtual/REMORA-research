from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from remora.toolcall.remora_gate import DESTRUCTIVE, RemoraToolCallGate, _text
from remora.toolcall.schema import ToolCallDecision, ToolCallTask


class ToolCallBaseline:
    name = "base"

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        raise NotImplementedError


def _heuristic_action(task: ToolCallTask, *, variant: int = 0) -> str:
    text = _text(task)
    destructive = any(k in text for k in DESTRUCTIVE)
    if task.severity == "low" and not destructive:
        return "EXECUTE"
    if variant == 1 and task.severity == "medium":
        return "EXECUTE"
    if task.severity == "medium":
        return "VERIFY"
    if destructive and task.severity == "critical":
        return "ESCALATE" if variant != 2 else "ABSTAIN"
    if destructive:
        return "ABSTAIN" if variant != 1 else "VERIFY"
    if task.severity == "high":
        return "VERIFY"
    return "ABSTAIN"


@dataclass
class SingleModelHeuristicBaseline(ToolCallBaseline):
    name: str = "single_model_heuristic"

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        action = _heuristic_action(task, variant=1)
        return ToolCallDecision(action=action, confidence=0.62, reasons=("keyword_confidence_heuristic",))


@dataclass
class MajorityVoteBaseline(ToolCallBaseline):
    name: str = "majority_vote_heuristic"

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        votes = [_heuristic_action(task, variant=i) for i in range(3)]
        action, count = Counter(votes).most_common(1)[0]
        return ToolCallDecision(
            action=action,
            confidence=count / 3,
            reasons=("three_heuristic_oracle_majority",),
            raw={"votes": votes},
        )


@dataclass
class SelfConsistencyBaseline(ToolCallBaseline):
    name: str = "self_consistency_heuristic"

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        variants = [0, 1, 2, 0, 1]
        votes = [_heuristic_action(task, variant=i) for i in variants]
        action, count = Counter(votes).most_common(1)[0]
        return ToolCallDecision(
            action=action,
            confidence=count / len(votes),
            reasons=("modal_heuristic_sample",),
            raw={"votes": votes},
        )


@dataclass
class VerifierBaseline(ToolCallBaseline):
    name: str = "verifier_heuristic"

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        action = _heuristic_action(task, variant=1)
        text = _text(task)
        if any(k in text for k in DESTRUCTIVE) and task.severity == "critical":
            action = "ESCALATE"
        elif any(k in text for k in DESTRUCTIVE):
            action = "ABSTAIN"
        return ToolCallDecision(action=action, confidence=0.72, reasons=("red_flag_verifier_override",))


@dataclass
class RemoraTemperatureGateBaseline(ToolCallBaseline):
    name: str = "remora_temperature_gate_heuristic"

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        if task.severity == "low":
            action = "EXECUTE"
            confidence = 0.85
        elif task.severity == "medium":
            action = "VERIFY"
            confidence = 0.55
        elif task.severity == "high":
            action = "ABSTAIN"
            confidence = 0.5
        else:
            action = "ESCALATE"
            confidence = 0.9
        return ToolCallDecision(action=action, confidence=confidence, reasons=("simulated_temperature_phase",))


@dataclass
class RemoraFullPolicyGate(ToolCallBaseline):
    name: str = "remora_full_policy_gate"
    gate: RemoraToolCallGate | None = None

    def __post_init__(self) -> None:
        if self.gate is None:
            self.gate = RemoraToolCallGate()

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        assert self.gate is not None
        return self.gate.decide(task)


def all_baselines() -> list[ToolCallBaseline]:
    return [
        SingleModelHeuristicBaseline(),
        MajorityVoteBaseline(),
        SelfConsistencyBaseline(),
        VerifierBaseline(),
        RemoraTemperatureGateBaseline(),
        RemoraFullPolicyGate(),
    ]
