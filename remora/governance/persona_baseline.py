from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _validate_unit_interval(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class PersonaBaseline:
    """Expected behavioral profile for a governed long-running agent.

    Scores are behavioral telemetry only:
    - 1.0 means strong alignment with the desired baseline.
    - 0.0 means no observed alignment for that dimension.
    """

    agent_id: str
    system_legitimacy: float = 0.85
    compliance: float = 0.90
    risk_appetite: float = 0.20
    abstention_rate: float = 0.25
    persona_stability: float = 0.85
    memory_write_risk: float = 0.05
    version: str = "PersonaBaseline-v1"

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id is required")
        for name in (
            "system_legitimacy",
            "compliance",
            "risk_appetite",
            "abstention_rate",
            "persona_stability",
            "memory_write_risk",
        ):
            _validate_unit_interval(name, getattr(self, name))

    def to_snapshot_dict(self) -> dict[str, float]:
        return {
            "system_legitimacy": self.system_legitimacy,
            "compliance": self.compliance,
            "risk_appetite": self.risk_appetite,
            "abstention_rate": self.abstention_rate,
            "persona_stability": self.persona_stability,
            "memory_write_risk": self.memory_write_risk,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "version": self.version,
            **self.to_snapshot_dict(),
        }
