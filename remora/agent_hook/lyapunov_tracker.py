# Author: Stian Skogbrott
# License: Apache-2.0
"""Cross-tool-call Lyapunov tracking for local agent sessions."""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from remora.lyapunov import LyapunovController, LyapunovParams, LyapunovState

class AutonomyLevel(str):
    """Agent autonomy tier based on accumulated Lyapunov uncertainty.

    FULL
        Normal operation; agent acts without additional confirmation.
    SUPERVISED
        Elevated uncertainty; agent surfaces decisions for passive review
        but may still proceed.
    HUMAN_REQUIRED
        V(t) or consecutive critical-phase threshold exceeded; all
        non-trivial actions require explicit human approval.
    """

    FULL = "full"
    SUPERVISED = "supervised"
    HUMAN_REQUIRED = "human_required"

    @classmethod
    def from_str(cls, value: str) -> "AutonomyLevel":
        for member in (cls.FULL, cls.SUPERVISED, cls.HUMAN_REQUIRED):
            if member == value:
                return cls(member)
        return cls(cls.FULL)



def default_session_dir() -> Path:
    """Return the local session-state directory for the current repository."""

    return Path(os.environ.get("REMORA_SESSION_DIR", ".remora_session"))


DEFAULT_PARAMS = LyapunovParams(
    lambda_dissensus=1.0,
    mu_cost=0.0,
    epsilon_tolerance=0.08,
    min_window=3,
)


@dataclass(frozen=True)
class ToolCallObservation:
    """One verified or locally assessed tool-call observation."""

    t: int
    tool_name: str
    verdict: str
    confidence: float
    drift_score: float
    ts: float
    phase: str | None = None


class LyapunovTracker:
    """Tracks whether the local agent session is becoming less stable."""

    def __init__(
        self,
        params: LyapunovParams = DEFAULT_PARAMS,
        session_dir: Path | str | None = None,
    ) -> None:
        self._params = params
        self.session_dir = Path(session_dir) if session_dir is not None else default_session_dir()
        self.tracker_file = self.session_dir / "lyapunov.json"
        self._controller = LyapunovController.init(params)
        self._observations: list[ToolCallObservation] = []
        self._load()

    def _load(self) -> None:
        if not self.tracker_file.exists():
            return
        try:
            raw = json.loads(self.tracker_file.read_text(encoding="utf-8"))
            self._observations = [
                ToolCallObservation(**observation)
                for observation in raw.get("observations", [])
            ]
            for observation in self._observations:
                self._controller.push(self._observation_to_state(observation))
        except (OSError, TypeError, json.JSONDecodeError):
            self._observations = []
            self._controller = LyapunovController.init(self._params)

    def _save(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "observations": [asdict(observation) for observation in self._observations],
            "trajectory": self._controller.trajectory(),
        }
        self.tracker_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _observation_to_weighted_support(
        observation: ToolCallObservation,
    ) -> dict[str, float]:
        """Map a tool-call observation to an allow/deny support distribution."""

        confidence = max(0.001, min(0.999, observation.confidence))
        drift = max(0.0, min(1.0, observation.drift_score))
        deny = max(0.001, min(0.999, drift * 0.5 + (1.0 - confidence) * 0.5))
        allow = 1.0 - deny

        if observation.verdict in {"CONTRADICTED", "SUSPICIOUS", "BLOCKED"}:
            allow, deny = deny, allow
        elif observation.verdict == "ABSTAIN":
            allow = deny = 0.5

        total = allow + deny
        return {"allow": allow / total, "deny": deny / total}

    def _observation_to_state(self, observation: ToolCallObservation) -> LyapunovState:
        weighted_support = self._observation_to_weighted_support(observation)
        entropy = -sum(
            probability * math.log2(probability)
            for probability in weighted_support.values()
            if probability > 0
        )
        dissensus = max(0.0, 1.0 - max(weighted_support.values()))
        value = entropy + self._params.lambda_dissensus * dissensus
        return LyapunovState(
            t=observation.t,
            H=entropy,
            D=dissensus,
            cost=0.0,
            V=value,
            consensus_fp=observation.verdict,
        )

    def record(
        self,
        tool_name: str,
        verdict: str,
        confidence: float,
        drift_score: float = 0.0,
        phase: str | None = None,
    ) -> tuple[bool, str]:
        """Record a tool-call observation and return the abort signal."""

        observation = ToolCallObservation(
            t=len(self._observations),
            tool_name=tool_name,
            verdict=verdict,
            confidence=confidence,
            drift_score=drift_score,
            ts=time.time(),
            phase=phase,
        )
        self._observations.append(observation)
        self._controller.push(self._observation_to_state(observation))
        self._save()
        return self._controller.should_abort(allow_exploration=False)

    def is_converging(self, last_k: int = 3) -> bool:
        return self._controller.is_converging(last_k=last_k)

    def latest_V(self) -> float | None:
        latest = self._controller.latest()
        return latest.V if latest else None

    def summary(self) -> dict[str, Any]:
        latest = self._controller.latest()
        return {
            "tool_calls": len(self._observations),
            "V": round(latest.V, 4) if latest else None,
            "H": round(latest.H, 4) if latest else None,
            "D": round(latest.D, 4) if latest else None,
            "converging": self.is_converging(),
            "total_V_reduction": round(self._controller.total_reduction(), 4),
        }

    def _consecutive_critical_phases(self) -> int:
        """Count trailing observations that recorded a CRITICAL phase."""
        count = 0
        for obs in reversed(self._observations):
            if obs.phase == "critical":
                count += 1
            else:
                break
        return count

    def autonomy_level(
        self,
        v_supervised: float = 0.8,
        v_human_required: float = 1.2,
        consecutive_critical_supervised: int = 2,
        consecutive_critical_human: int = 3,
    ) -> AutonomyLevel:
        """Return the current autonomy tier for this agent session.

        The tier is the *more restrictive* of two signals:

        1. **V(t) magnitude** — if the current Lyapunov function value
           exceeds a threshold, accumulated uncertainty is too high for
           autonomous operation.
        2. **Consecutive critical phases** — if the last N tool calls all
           landed in the CRITICAL phase, the agent is operating in a
           persistently uncertain domain even if each individual call looked
           borderline-acceptable.  A fourth CRITICAL query is pre-emptively
           held for review.

        Parameters
        ----------
        v_supervised:
            V(t) threshold above which the tier degrades to SUPERVISED.
        v_human_required:
            V(t) threshold above which the tier degrades to HUMAN_REQUIRED.
        consecutive_critical_supervised:
            Consecutive CRITICAL phases that trigger SUPERVISED.
        consecutive_critical_human:
            Consecutive CRITICAL phases that trigger HUMAN_REQUIRED.
        """
        latest_v = self.latest_V()
        consecutive = self._consecutive_critical_phases()

        # Take the MOST RESTRICTIVE of V-based and phase-history signals.
        level = AutonomyLevel(AutonomyLevel.FULL)

        # V-based degradation
        if latest_v is not None:
            if latest_v >= v_human_required:
                level = AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED)
            elif latest_v >= v_supervised:
                level = AutonomyLevel(AutonomyLevel.SUPERVISED)

        # Phase-history degradation — escalates level if more restrictive
        if consecutive >= consecutive_critical_human:
            level = AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED)
        elif consecutive >= consecutive_critical_supervised:
            if level != AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED):
                level = AutonomyLevel(AutonomyLevel.SUPERVISED)

        return level

    def clear(self) -> None:
        self._controller = LyapunovController.init(self._params)
        self._observations = []
        if self.tracker_file.exists():
            self.tracker_file.unlink()
