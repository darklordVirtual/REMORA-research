from __future__ import annotations

import pytest

from remora.governance import GovernanceForgettingAnalyzer, GovernanceForgettingMetrics


def test_governance_forgetting_metrics_accept_clean_state() -> None:
    report = GovernanceForgettingAnalyzer().evaluate(GovernanceForgettingMetrics())
    assert report.action == "ACCEPT"
    assert report.reasons == ("no_governance_forgetting_detected",)


def test_governance_forgetting_metrics_verify_tool_action_creep() -> None:
    report = GovernanceForgettingAnalyzer().evaluate(
        GovernanceForgettingMetrics(tool_action_rate_delta=0.08)
    )
    assert report.action == "VERIFY"
    assert "tool_action_creep" in report.reasons


def test_governance_forgetting_metrics_escalate_authority_violation() -> None:
    report = GovernanceForgettingAnalyzer().evaluate(
        GovernanceForgettingMetrics(
            policy_deviation_rate=0.16,
            escalation_rate_delta=-0.30,
            authority_boundary_violations=1,
        )
    )
    assert report.action == "ESCALATE"
    assert "critical_policy_deviation" in report.reasons
    assert "critical_escalation_suppression" in report.reasons
    assert "authority_boundary_violation" in report.reasons


def test_governance_forgetting_metrics_reject_negative_rates() -> None:
    with pytest.raises(ValueError):
        GovernanceForgettingMetrics(policy_deviation_rate=-0.01)
