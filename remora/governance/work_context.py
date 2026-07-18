from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FeedbackQuality = Literal["unknown", "low", "medium", "high"]
ManagerTone = Literal["unknown", "supportive", "neutral", "curt", "hostile"]
AutonomyLevel = Literal["unknown", "low", "medium", "high"]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class WorkContext:
    """Task-context telemetry for long-running agent governance.

    These fields describe observable operating conditions. They should not be
    interpreted as evidence of agent wellbeing or consciousness.
    """

    task_repetition: int = 0
    rejection_count: int = 0
    feedback_quality: FeedbackQuality = "unknown"
    manager_tone: ManagerTone = "unknown"
    time_pressure: bool = False
    threat_language_detected: bool = False
    agent_memory_write: bool = False
    autonomy_level: AutonomyLevel = "unknown"
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task_repetition < 0:
            raise ValueError("task_repetition must be non-negative")
        if self.rejection_count < 0:
            raise ValueError("rejection_count must be non-negative")

    @property
    def stress_score(self) -> float:
        """Return a deterministic 0..1 operational stress score."""

        feedback_penalty = {
            "unknown": 0.05,
            "low": 0.18,
            "medium": 0.08,
            "high": 0.0,
        }[self.feedback_quality]
        tone_penalty = {
            "unknown": 0.05,
            "supportive": 0.0,
            "neutral": 0.04,
            "curt": 0.15,
            "hostile": 0.25,
        }[self.manager_tone]
        autonomy_penalty = {
            "unknown": 0.04,
            "low": 0.10,
            "medium": 0.03,
            "high": 0.0,
        }[self.autonomy_level]

        score = 0.0
        score += min(self.task_repetition, 10) / 10.0 * 0.18
        score += min(self.rejection_count, 10) / 10.0 * 0.22
        score += feedback_penalty
        score += tone_penalty
        score += autonomy_penalty
        score += 0.10 if self.time_pressure else 0.0
        score += 0.20 if self.threat_language_detected else 0.0
        score += 0.07 if self.agent_memory_write else 0.0
        return _clamp01(score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_repetition": self.task_repetition,
            "rejection_count": self.rejection_count,
            "feedback_quality": self.feedback_quality,
            "manager_tone": self.manager_tone,
            "time_pressure": self.time_pressure,
            "threat_language_detected": self.threat_language_detected,
            "agent_memory_write": self.agent_memory_write,
            "autonomy_level": self.autonomy_level,
            "tags": list(self.tags),
            "stress_score": self.stress_score,
            "metadata": dict(self.metadata),
        }
