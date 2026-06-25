# Author: Stian Skogbrott
# License: Apache-2.0
"""Apply follow-up Lyapunov tracker patch logic for autonomy-level escalation ordering."""
import pathlib

path = pathlib.Path("remora/agent_hook/lyapunov_tracker.py")
content = path.read_text(encoding="utf-8")

old = """        latest_v = self.latest_V()
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

        return AutonomyLevel(AutonomyLevel.FULL)"""

new = """        latest_v = self.latest_V()
        consecutive = self._consecutive_critical_phases()

        # Take the MOST RESTRICTIVE of V-based and phase-history signals.
        level = AutonomyLevel(AutonomyLevel.FULL)

        # V-based degradation
        if latest_v is not None:
            if latest_v >= v_human_required:
                level = AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED)
            elif latest_v >= v_supervised:
                level = AutonomyLevel(AutonomyLevel.SUPERVISED)

        # Phase-history degradation - escalates level if more restrictive
        if consecutive >= consecutive_critical_human:
            level = AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED)
        elif consecutive >= consecutive_critical_supervised:
            if level != AutonomyLevel(AutonomyLevel.HUMAN_REQUIRED):
                level = AutonomyLevel(AutonomyLevel.SUPERVISED)

        return level"""

assert old in content, "pattern not found in file"
path.write_text(content.replace(old, new, 1), encoding="utf-8")
print("patched")
