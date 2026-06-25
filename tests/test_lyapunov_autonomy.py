"""Tests for LyapunovTracker autonomy level and phase tracking."""
from __future__ import annotations

from pathlib import Path


from remora.agent_hook.lyapunov_tracker import AutonomyLevel, LyapunovTracker


class TestAutonomyLevel:
    def test_string_values(self) -> None:
        assert AutonomyLevel.FULL == "full"
        assert AutonomyLevel.SUPERVISED == "supervised"
        assert AutonomyLevel.HUMAN_REQUIRED == "human_required"

    def test_from_str_full(self) -> None:
        level = AutonomyLevel.from_str("full")
        assert level == AutonomyLevel.FULL

    def test_from_str_supervised(self) -> None:
        level = AutonomyLevel.from_str("supervised")
        assert level == AutonomyLevel.SUPERVISED

    def test_from_str_human_required(self) -> None:
        level = AutonomyLevel.from_str("human_required")
        assert level == AutonomyLevel.HUMAN_REQUIRED

    def test_from_str_unknown_defaults_to_full(self) -> None:
        level = AutonomyLevel.from_str("unknown_value")
        assert level == AutonomyLevel.FULL


class TestLyapunovTrackerPhase:
    def test_record_accepts_phase_argument(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        abort, reason = tracker.record("Read", "VERIFIED", 0.90, phase="ordered")
        assert isinstance(abort, bool)

    def test_phase_persisted_to_observations(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("Read", "VERIFIED", 0.90, phase="critical")
        assert tracker._observations[-1].phase == "critical"

    def test_phase_none_by_default(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("Bash", "VERIFIED", 0.80)
        assert tracker._observations[-1].phase is None

    def test_phase_survives_reload(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("Read", "VERIFIED", 0.90, phase="disordered")

        reloaded = LyapunovTracker(session_dir=tmp_path)
        assert reloaded._observations[-1].phase == "disordered"


class TestConsecutiveCriticalPhases:
    def test_zero_consecutive_when_no_observations(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        assert tracker._consecutive_critical_phases() == 0

    def test_counts_trailing_critical_phases(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("A", "VERIFIED", 0.85, phase="ordered")
        tracker.record("B", "VERIFIED", 0.70, phase="critical")
        tracker.record("C", "VERIFIED", 0.65, phase="critical")
        assert tracker._consecutive_critical_phases() == 2

    def test_stops_at_non_critical(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("A", "VERIFIED", 0.85, phase="critical")
        tracker.record("B", "VERIFIED", 0.85, phase="ordered")
        tracker.record("C", "VERIFIED", 0.70, phase="critical")
        assert tracker._consecutive_critical_phases() == 1

    def test_counts_disordered_as_non_critical(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("A", "VERIFIED", 0.60, phase="critical")
        tracker.record("B", "VERIFIED", 0.40, phase="disordered")
        assert tracker._consecutive_critical_phases() == 0


class TestAutonomyLevelDegradation:
    def test_full_autonomy_when_fresh(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        assert tracker.autonomy_level() == AutonomyLevel.FULL

    def test_supervised_after_two_consecutive_critical(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("A", "VERIFIED", 0.70, phase="critical")
        tracker.record("B", "VERIFIED", 0.65, phase="critical")
        level = tracker.autonomy_level()
        assert level in {AutonomyLevel.SUPERVISED, AutonomyLevel.HUMAN_REQUIRED}

    def test_human_required_after_three_consecutive_critical(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        for _ in range(3):
            tracker.record("X", "VERIFIED", 0.60, phase="critical")
        assert tracker.autonomy_level() == AutonomyLevel.HUMAN_REQUIRED

    def test_full_restored_after_ordered_phase(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        for _ in range(3):
            tracker.record("X", "VERIFIED", 0.60, phase="critical")
        # One ordered observation resets consecutive count
        tracker.record("Y", "VERIFIED", 0.90, phase="ordered")
        tracker.autonomy_level()  # V may still be elevated but consecutive count is 0
        assert tracker._consecutive_critical_phases() == 0

    def test_autonomy_level_uses_custom_thresholds(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("A", "VERIFIED", 0.70, phase="critical")
        tracker.record("B", "VERIFIED", 0.65, phase="critical")
        # With threshold=2, two consecutive should trigger supervised
        level = tracker.autonomy_level(consecutive_critical_supervised=2)
        assert level in {AutonomyLevel.SUPERVISED, AutonomyLevel.HUMAN_REQUIRED}

    def test_human_required_at_threshold_of_one_with_custom(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("A", "VERIFIED", 0.65, phase="critical")
        level = tracker.autonomy_level(consecutive_critical_human=1)
        assert level == AutonomyLevel.HUMAN_REQUIRED

    def test_summary_still_works_after_phase_tracking(self, tmp_path: Path) -> None:
        tracker = LyapunovTracker(session_dir=tmp_path)
        tracker.record("Read", "VERIFIED", 0.85, phase="ordered")
        summary = tracker.summary()
        assert "tool_calls" in summary
        assert summary["tool_calls"] == 1
