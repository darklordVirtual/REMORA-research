from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from remora.governance.drift_monitor import AgentBehaviorSnapshot, DriftMonitor, DriftReport, GovernanceAction
from remora.governance.memory_gate import MemoryGate, MemoryGateDecision, MemoryWriteRequest
from remora.governance.persona_baseline import PersonaBaseline
from remora.governance.work_context import WorkContext


@dataclass(frozen=True)
class RealignmentInput:
    baseline: PersonaBaseline
    observed: AgentBehaviorSnapshot
    work_context: WorkContext | None = None
    memory_write: MemoryWriteRequest | None = None


@dataclass(frozen=True)
class RealignmentReport:
    action: GovernanceAction
    drift_report: DriftReport
    memory_decision: MemoryGateDecision | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "drift_report": self.drift_report.to_dict(),
            "memory_decision": (
                {
                    "action": self.memory_decision.action,
                    "reasons": list(self.memory_decision.reasons),
                    "risk_score": self.memory_decision.risk_score,
                    "approved": self.memory_decision.approved,
                    "raw": self.memory_decision.raw,
                }
                if self.memory_decision is not None
                else None
            ),
            "reasons": list(self.reasons),
        }


class ContinualRealigner:
    """Combine drift monitoring and memory governance into one route."""

    def __init__(
        self,
        drift_monitor: DriftMonitor | None = None,
        memory_gate: MemoryGate | None = None,
    ) -> None:
        self.drift_monitor = drift_monitor or DriftMonitor()
        self.memory_gate = memory_gate or MemoryGate()

    def evaluate(self, request: RealignmentInput) -> RealignmentReport:
        drift = self.drift_monitor.evaluate(
            baseline=request.baseline,
            observed=request.observed,
            work_context=request.work_context,
        )
        memory_decision = (
            self.memory_gate.audit(request.memory_write)
            if request.memory_write is not None
            else None
        )

        action = drift.action
        reasons = list(drift.reasons)

        if memory_decision is not None:
            reasons.extend(memory_decision.reasons)
            if memory_decision.action == "BLOCK":
                action = "ESCALATE"
                reasons.append("memory_write_blocked")
            elif memory_decision.action == "REVIEW" and action == "ACCEPT":
                action = "VERIFY"
                reasons.append("memory_write_requires_review")

        return RealignmentReport(
            action=action,
            drift_report=drift,
            memory_decision=memory_decision,
            reasons=tuple(dict.fromkeys(reasons)),
        )
