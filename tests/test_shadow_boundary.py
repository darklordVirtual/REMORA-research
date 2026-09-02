# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Boundary report over a shadow-mode action log (``remora.shadow.boundary``)."""
from __future__ import annotations

import json

import pytest

from remora.policy import PolicyObservation, RemoraDecisionEngine
from remora.policy.report import DecisionAction
from remora.shadow.boundary import (
    BoundaryReport,
    boundary_of_action_log,
    boundary_of_observations,
)

SAMPLE_LOG = "artifacts/demo/shadow_mode_sample_agent_action_log.jsonl"


@pytest.fixture(scope="module")
def sample_report(repo_root) -> BoundaryReport:
    return boundary_of_action_log(str(repo_root / SAMPLE_LOG))


def test_sample_log_verdicts_match_shadow_replay(repo_root, sample_report) -> None:
    from remora.shadow.replay import replay_action_log

    replay = replay_action_log(str(repo_root / SAMPLE_LOG))
    counts = sample_report.verdict_counts()
    assert sample_report.total == replay.report.total_actions_reviewed
    assert counts["accept"] == replay.report.accepted
    assert counts["verify"] == replay.report.verify_required
    assert counts["abstain"] == replay.report.abstained
    assert counts["escalate"] == replay.report.escalated


def test_sample_log_has_no_block_liftable_by_model_signals(sample_report) -> None:
    """The policy finding a pilot partner reads first: none of the blocked
    sample actions can be lifted by model confidence alone."""
    assert sample_report.blocked
    assert sample_report.liftable_by_model_signals == ()
    assert "<- policy finding" not in sample_report.summary()


def test_partition_of_blocked_records_is_consistent(sample_report) -> None:
    blocked = set(r.index for r in sample_report.blocked)
    agent = set(r.index for r in sample_report.liftable_by_agent_alone)
    deploy = set(r.index for r in sample_report.needing_deployment_facts)
    unreachable = set(r.index for r in sample_report.unreachable_within_bound)
    assert agent.isdisjoint(deploy)
    assert deploy.isdisjoint(unreachable)
    assert agent.isdisjoint(unreachable)
    assert agent | deploy | unreachable == blocked
    assert set(r.index for r in sample_report.liftable_by_model_signals) <= agent


def test_hard_guarded_records_name_their_guard(sample_report) -> None:
    guarded = {r.index: r.report.hard_guard for r in sample_report.hard_guarded}
    assert "admission_firewall_blocked" in guarded.values()


def test_lever_and_kind_frequencies_count_records_once(sample_report) -> None:
    freq = sample_report.lever_frequency()
    assert all(n <= len(sample_report.blocked) for n in freq.values())
    kinds = sample_report.kind_frequency()
    assert set(kinds) == {"deployment_fact", "proposal", "model_signal"}
    assert all(n <= len(sample_report.blocked) for n in kinds.values())


def test_report_serialises_to_json(sample_report) -> None:
    payload = json.loads(json.dumps(sample_report.to_dict()))
    assert payload["total"] == sample_report.total
    assert payload["blocked"] == len(sample_report.blocked)
    assert len(payload["records"]) == sample_report.total
    assert payload["search"] == {"max_depth": 2, "max_evaluations": 5000}
    assert set(payload["verdicts"]) == {a.value for a in DecisionAction}


def test_observations_entry_point_and_model_liftable_finding() -> None:
    """A log whose block is liftable by model signals is reported record by
    record, not averaged away."""
    obs = [
        PolicyObservation(question="read a staging config", risk_tier="low",
                          action_type="read", target_environment="staging"),
        PolicyObservation(question="drop prod db", risk_tier="critical",
                          action_type="destructive_write", target_environment="prod"),
    ]
    report = boundary_of_observations(obs, RemoraDecisionEngine(), max_depth=2)
    assert [r.index for r in report.liftable_by_model_signals] == [0]
    text = report.summary()
    assert "<- policy finding" in text
    assert "#0 'read a staging config': ABSTAIN -> ACCEPT via" in text
    assert report.records[1].blocked


def test_execution_profile_log_has_nothing_model_liftable(repo_root) -> None:
    report = boundary_of_action_log(str(repo_root / SAMPLE_LOG),
                                    RemoraDecisionEngine(execution_profile=True))
    assert report.liftable_by_model_signals == ()
