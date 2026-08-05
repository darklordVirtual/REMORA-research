# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""remora_session_status must emit what mcp-integration.md promises.

The doc documents drift score, autonomy level (FULL/SUPERVISED/
HUMAN_REQUIRED) and the consecutive-critical-phase count as output fields;
the handler previously emitted none of them (hook/safety sweep 2026-08-05,
finding 3) although the underlying tracker implements and tests all three.
"""
from __future__ import annotations


def test_summary_carries_autonomy_fields(tmp_path) -> None:
    from remora.agent_hook.lyapunov_tracker import LyapunovTracker

    tracker = LyapunovTracker(session_dir=tmp_path)
    tracker.record("Write", "VERIFIED", 0.9, drift_score=0.05)

    s = tracker.summary()
    assert s["autonomy_level"] == "FULL"
    assert s["consecutive_critical"] == 0
    assert s["latest_drift"] == 0.05


def test_session_status_reports_documented_fields(tmp_path) -> None:
    from remora.agent_hook.lyapunov_tracker import LyapunovTracker

    import servers.mcp_remora as mcp

    tracker = LyapunovTracker(session_dir=tmp_path)
    tracker.record("Write", "VERIFIED", 0.9, drift_score=0.05)

    out = mcp.handle_remora_session_status({"session_dir": str(tmp_path)})

    assert "Autonomy level" in out and "FULL" in out
    assert "Drift score" in out
    assert "Consecutive critical" in out
