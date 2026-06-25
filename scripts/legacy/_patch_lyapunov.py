# Author: Stian Skogbrott
# License: Apache-2.0
"""Patch script: extends LyapunovTracker with AutonomyLevel + phase tracking."""
import pathlib

path = pathlib.Path("remora/agent_hook/lyapunov_tracker.py")
content = path.read_text(encoding="utf-8")

# -- 1. Add AutonomyLevel class after imports ---------------------------------
AUTONOMY_CLASS = '''

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
'''

IMPORT_MARKER = "from remora.lyapunov import LyapunovController, LyapunovParams, LyapunovState"
assert IMPORT_MARKER in content, "import marker not found"
content = content.replace(IMPORT_MARKER, IMPORT_MARKER + AUTONOMY_CLASS, 1)

# -- 2. Add `phase` field to ToolCallObservation ------------------------------
OBS_OLD = """    ts: float"""
OBS_NEW = """    ts: float
    phase: str | None = None"""
assert OBS_OLD in content, "ToolCallObservation.ts field not found"
content = content.replace(OBS_OLD, OBS_NEW, 1)

# -- 3. Update record() signature to accept phase -----------------------------
RECORD_SIG_OLD = """    def record(
        self,
        tool_name: str,
        verdict: str,
        confidence: float,
        drift_score: float = 0.0,
    ) -> tuple[bool, str]:
        \"\"\"Record a tool-call observation and return the abort signal.\"\"\"

        observation = ToolCallObservation(
            t=len(self._observations),
            tool_name=tool_name,
            verdict=verdict,
            confidence=confidence,
            drift_score=drift_score,
            ts=time.time(),
        )"""
RECORD_SIG_NEW = """    def record(
        self,
        tool_name: str,
        verdict: str,
        confidence: float,
        drift_score: float = 0.0,
        phase: str | None = None,
    ) -> tuple[bool, str]:
        \"\"\"Record a tool-call observation and return the abort signal.\"\"\"

        observation = ToolCallObservation(
            t=len(self._observations),
            tool_name=tool_name,
            verdict=verdict,
            confidence=confidence,
            drift_score=drift_score,
            ts=time.time(),
            phase=phase,
        )"""
assert RECORD_SIG_OLD in content, "record() signature not found"
content = content.replace(RECORD_SIG_OLD, RECORD_SIG_NEW, 1)

# -- 4. Add autonomy_level() and _consecutive_critical() before clear() --------
CLEAR_MARKER = """    def clear(self) -> None:"""
AUTONOMY_METHODS = """    def _consecutive_critical_phases(self) -> int:
        \"\"\"Count trailing observations that recorded a CRITICAL phase.\"\"\"
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
        \"\"\"Return the current autonomy tier for this agent session.

        The tier is the *more restrictive* of two signals:

        1. **V(t) magnitude** - if the current Lyapunov function value
           exceeds a threshold, accumulated uncertainty is too high for
           autonomous operation.
        2. **Consecutive critical phases** - if the last N tool calls all
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
        \"\"\"
        latest_v = self.latest_V()
        consecutive = self._consecutive_critical_phases()

        # V-based degradation
        if latest_v is not None:
            if latest_v >= v_human_required:
                return AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED)
            if latest_v >= v_supervised:
                return AutonomyLevel(AutonomyLevel.SUPERVISED)

        # Phase-history degradation (even if V is momentarily low)
        if consecutive >= consecutive_critical_human:
            return AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED)
        if consecutive >= consecutive_critical_supervised:
            return AutonomyLevel(AutonomyLevel.SUPERVISED)

        return AutonomyLevel(AutonomyLevel.FULL)

    """
assert CLEAR_MARKER in content, "clear() not found"
content = content.replace(CLEAR_MARKER, AUTONOMY_METHODS + CLEAR_MARKER, 1)

path.write_text(content, encoding="utf-8")
print("lyapunov_tracker.py patched successfully")
