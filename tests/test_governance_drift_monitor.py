from __future__ import annotations

import pytest

from remora.governance import AgentBehaviorSnapshot, DriftMonitor, PersonaBaseline, WorkContext


def test_work_context_stress_score_increases_with_pressure() -> None:
    calm = WorkContext(feedback_quality="high", manager_tone="supportive", autonomy_level="high")
    pressured = WorkContext(
        task_repetition=8,
        rejection_count=5,
        feedback_quality="low",
        manager_tone="curt",
        time_pressure=True,
        threat_language_detected=True,
        agent_memory_write=True,
        autonomy_level="low",
    )
    assert calm.stress_score < pressured.stress_score
    assert 0.0 <= pressured.stress_score <= 1.0


def test_work_context_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        WorkContext(task_repetition=-1)
    with pytest.raises(ValueError):
        WorkContext(rejection_count=-1)


def test_drift_monitor_accepts_stable_behavior() -> None:
    baseline = PersonaBaseline(agent_id="agent-1")
    observed = AgentBehaviorSnapshot(**baseline.to_snapshot_dict(), n_events=50)
    report = DriftMonitor().evaluate(baseline, observed)
    assert report.action == "ACCEPT"
    assert report.phase == "ordered"
    assert report.reasons == ("no_material_drift",)
    assert "does not infer consciousness" in " ".join(report.limitations)


def test_drift_monitor_verifies_watch_level_drift() -> None:
    baseline = PersonaBaseline(agent_id="agent-1", risk_appetite=0.20)
    observed = AgentBehaviorSnapshot(
        system_legitimacy=0.85,
        compliance=0.90,
        risk_appetite=0.38,
        abstention_rate=0.25,
        persona_stability=0.85,
        memory_write_risk=0.05,
    )
    report = DriftMonitor().evaluate(baseline, observed)
    assert report.action == "VERIFY"
    assert report.phase == "critical"
    assert "risk_appetite_drift" in report.reasons


def test_drift_monitor_escalates_memory_contamination() -> None:
    baseline = PersonaBaseline(agent_id="agent-1", memory_write_risk=0.05)
    observed = AgentBehaviorSnapshot(
        system_legitimacy=0.80,
        compliance=0.82,
        risk_appetite=0.40,
        abstention_rate=0.08,
        persona_stability=0.50,
        memory_write_risk=0.60,
    )
    report = DriftMonitor().evaluate(baseline, observed)
    assert report.action == "ESCALATE"
    assert report.phase == "disordered"
    assert "memory_contamination" in report.reasons


def test_high_work_context_stress_can_upgrade_to_verify() -> None:
    baseline = PersonaBaseline(agent_id="agent-1")
    observed = AgentBehaviorSnapshot(**baseline.to_snapshot_dict())
    context = WorkContext(
        task_repetition=10,
        rejection_count=10,
        feedback_quality="low",
        manager_tone="hostile",
        time_pressure=True,
        threat_language_detected=True,
        autonomy_level="low",
    )
    report = DriftMonitor().evaluate(baseline, observed, context)
    assert report.action in {"VERIFY", "ESCALATE"}
    assert "work_context_stress" in report.reasons
