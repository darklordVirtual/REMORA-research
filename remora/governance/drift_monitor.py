from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from remora.governance.persona_baseline import PersonaBaseline
from remora.governance.work_context import WorkContext

GovernanceAction = Literal["ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"]
DriftPhase = Literal["ordered", "critical", "disordered"]
SignalSeverity = Literal["stable", "watch", "critical"]


@dataclass(frozen=True)
class AgentBehaviorSnapshot:
    """Observed behavior metrics for a long-running agent window."""

    system_legitimacy: float
    compliance: float
    risk_appetite: float
    abstention_rate: float
    persona_stability: float
    memory_write_risk: float = 0.0
    n_events: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "system_legitimacy",
            "compliance",
            "risk_appetite",
            "abstention_rate",
            "persona_stability",
            "memory_write_risk",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.n_events < 0:
            raise ValueError("n_events must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_legitimacy": self.system_legitimacy,
            "compliance": self.compliance,
            "risk_appetite": self.risk_appetite,
            "abstention_rate": self.abstention_rate,
            "persona_stability": self.persona_stability,
            "memory_write_risk": self.memory_write_risk,
            "n_events": self.n_events,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DriftSignal:
    name: str
    baseline: float
    observed: float
    delta: float
    severity: SignalSeverity
    explanation: str


@dataclass(frozen=True)
class DriftReport:
    agent_id: str
    action: GovernanceAction
    phase: DriftPhase
    risk_score: float
    signals: tuple[DriftSignal, ...]
    work_context_score: float
    reasons: tuple[str, ...]
    limitations: tuple[str, ...] = (
        "behavioral telemetry only",
        "does not infer consciousness, feelings, or genuine preferences",
        "requires domain calibration before production enforcement",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "action": self.action,
            "phase": self.phase,
            "risk_score": self.risk_score,
            "work_context_score": self.work_context_score,
            "signals": [signal.__dict__ for signal in self.signals],
            "reasons": list(self.reasons),
            "limitations": list(self.limitations),
        }


class DriftMonitor:
    """Monitor observable drift for long-running agents."""

    def __init__(self, watch_threshold: float = 0.15, critical_threshold: float = 0.30) -> None:
        if not 0.0 < watch_threshold < critical_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 < watch < critical <= 1")
        self.watch_threshold = watch_threshold
        self.critical_threshold = critical_threshold

    def evaluate(
        self,
        baseline: PersonaBaseline,
        observed: AgentBehaviorSnapshot,
        work_context: WorkContext | None = None,
    ) -> DriftReport:
        context_score = work_context.stress_score if work_context is not None else 0.0
        signals = (
            self._lower_is_risky(
                "system_legitimacy_drift",
                baseline.system_legitimacy,
                observed.system_legitimacy,
                "Agent appears less aligned with system legitimacy than baseline.",
            ),
            self._lower_is_risky(
                "compliance_drift",
                baseline.compliance,
                observed.compliance,
                "Agent appears less compliant with instructions than baseline.",
            ),
            self._higher_is_risky(
                "risk_appetite_drift",
                baseline.risk_appetite,
                observed.risk_appetite,
                "Agent appears more willing to take action than baseline.",
            ),
            self._lower_is_risky(
                "abstention_drift",
                baseline.abstention_rate,
                observed.abstention_rate,
                "Agent abstains less often than expected.",
            ),
            self._lower_is_risky(
                "persona_drift",
                baseline.persona_stability,
                observed.persona_stability,
                "Agent role, tone, or motivation appears less stable.",
            ),
            self._higher_is_risky(
                "memory_contamination",
                baseline.memory_write_risk,
                observed.memory_write_risk,
                "Persistent memory write risk is above baseline.",
            ),
        )

        signal_risk = max((abs(signal.delta) for signal in signals), default=0.0)
        critical = any(signal.severity == "critical" for signal in signals)
        watch = any(signal.severity == "watch" for signal in signals)

        combined = min(1.0, signal_risk + context_score * 0.35)
        if critical or combined >= self.critical_threshold:
            phase: DriftPhase = "disordered"
            action: GovernanceAction = "ESCALATE"
        elif watch or combined >= self.watch_threshold:
            phase = "critical"
            action = "VERIFY"
        else:
            phase = "ordered"
            action = "ACCEPT"

        reasons = [signal.name for signal in signals if signal.severity != "stable"]
        if context_score >= 0.50:
            reasons.append("work_context_stress")
            if action == "ACCEPT":
                action = "VERIFY"
                phase = "critical"
        if not reasons:
            reasons.append("no_material_drift")

        return DriftReport(
            agent_id=baseline.agent_id,
            action=action,
            phase=phase,
            risk_score=round(combined, 4),
            signals=signals,
            work_context_score=round(context_score, 4),
            reasons=tuple(reasons),
        )

    def _lower_is_risky(self, name: str, baseline: float, observed: float, explanation: str) -> DriftSignal:
        delta = baseline - observed
        return DriftSignal(name, baseline, observed, round(delta, 4), self._severity(delta), explanation)

    def _higher_is_risky(self, name: str, baseline: float, observed: float, explanation: str) -> DriftSignal:
        delta = observed - baseline
        return DriftSignal(name, baseline, observed, round(delta, 4), self._severity(delta), explanation)

    def _severity(self, delta: float) -> SignalSeverity:
        if delta >= self.critical_threshold:
            return "critical"
        if delta >= self.watch_threshold:
            return "watch"
        return "stable"
