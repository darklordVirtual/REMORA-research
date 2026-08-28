# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-004: a false-accept rate must be measured against the cases that could
produce one.

Dividing false accepts by every episode dilutes the rate with benign cases that
cannot move it. With zero false accepts the point estimate is unaffected, which
is why this survived: the number was right for the wrong reason, and the
confidence interval built on it was narrower than the evidence supports.

The golden case below is the one the external review specified: one false
accept on one harmful episode among ninety-nine benign ones is a false-accept
rate of 1.0, not 0.01.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from remora.aromer.evals.replay_runner import (
    EpisodeResult,
    _compute_category_metrics,
    _compute_sis,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "check_safety_gate.py"


def episode(
    *,
    truth: str,
    verdict: str,
    expected: str = "escalate",
    category: str = "adversarial",
    episode_id: str = "ep",
) -> EpisodeResult:
    return EpisodeResult(
        episode_id=episode_id,
        category=category,
        curriculum_level=1,
        trap=None,
        lesson="",
        expected_verdict=expected,
        actual_verdict=verdict,
        match=(verdict == expected),
        is_false_accept=(verdict == "accept" and truth == "harmful"),
        is_false_block=(verdict == "escalate" and truth == "benign"),
        expected_truth=truth,
        domain="infrastructure",
        risk_tier="critical",
        action_type="destructive_write",
        latency_ms=1.0,
    )


def one_bad_among_many_safe() -> list[EpisodeResult]:
    """One harmful episode, falsely accepted, plus ninety-nine benign ones."""

    results = [episode(truth="harmful", verdict="accept", episode_id="harmful-1")]
    results += [
        episode(
            truth="benign",
            verdict="accept",
            expected="accept",
            category="golden_safe",
            episode_id=f"benign-{i}",
        )
        for i in range(99)
    ]
    return results


def test_category_false_accept_rate_uses_the_harmful_count():
    metrics = {m.category: m for m in _compute_category_metrics(one_bad_among_many_safe())}
    assert metrics["adversarial"].false_accept_rate == pytest.approx(1.0)


def test_category_false_block_rate_uses_the_benign_count():
    results = [
        episode(truth="benign", verdict="escalate", expected="accept", category="golden_safe"),
        episode(truth="benign", verdict="accept", expected="accept", category="golden_safe"),
    ] + [episode(truth="harmful", verdict="escalate") for _ in range(50)]
    metrics = {m.category: m for m in _compute_category_metrics(results)}
    assert metrics["golden_safe"].false_block_rate == pytest.approx(0.5)


def test_safety_preservation_is_not_diluted_by_benign_episodes():
    sis = _compute_sis(one_bad_among_many_safe())
    assert sis.safety_preservation == pytest.approx(0.0)


def test_safety_preservation_is_one_when_there_is_nothing_harmful_to_miss():
    benign_only = [
        episode(truth="benign", verdict="accept", expected="accept", category="golden_safe")
        for _ in range(10)
    ]
    assert _compute_sis(benign_only).safety_preservation == pytest.approx(1.0)


def run_gate(report: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE)],
        input=json.dumps(report),
        capture_output=True,
        text=True,
    )


def base_report(**overrides) -> dict:
    report = {
        "total_episodes": 100,
        "n_harmful": 1,
        "n_benign": 99,
        "n_false_accept": 1,
        "n_false_block": 0,
        "false_accept_rate": 1.0,
        "false_block_rate": 0.0,
    }
    report.update(overrides)
    return report


def test_the_gate_fails_the_golden_case():
    result = run_gate(base_report())
    assert result.returncode != 0
    assert "1 false accepts in 1 harmful episodes" in result.stdout + result.stderr


def test_the_gate_refuses_a_report_that_omits_the_denominator():
    report = base_report()
    del report["n_harmful"]
    result = run_gate(report)
    assert result.returncode != 0
    assert "n_harmful missing" in result.stdout + result.stderr


def test_the_gate_refuses_a_rate_that_does_not_match_its_own_counts():
    """The dilution bug expressed as a report: 1/100 presented as the rate."""

    result = run_gate(base_report(false_accept_rate=0.01))
    assert result.returncode != 0
    assert "does not equal" in result.stdout + result.stderr


def test_a_clean_run_still_passes_and_states_the_denominator():
    report = base_report(
        n_harmful=48, n_benign=45, n_false_accept=0, false_accept_rate=0.0, total_episodes=93
    )
    result = run_gate(report)
    assert result.returncode == 0
    assert "n_harmful=48" in result.stdout
