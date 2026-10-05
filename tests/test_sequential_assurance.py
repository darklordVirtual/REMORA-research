# SPDX-License-Identifier: BUSL-1.1
"""Tests for the RF-14 per-decision sequential assurance layer.

Covers the three instruments (Beta-mixture CS reuse, empirical-Bernstein CS,
rate e-process), the premise gate (NOT_ESTABLISHED on violation), epoch
reset semantics, the receipt schema and the authority-separation invariant.
Seeded simulations assert the time-uniform guarantee itself, mirroring
tests/test_confidence_sequence.py.
"""
from __future__ import annotations

import math
import random

import pytest

from remora.aromer.evals.sequential_assurance_adapter import outcomes_from_episode_records
from remora.selective.confidence_sequence import bernoulli_upper_confidence_sequence
from remora.selective.sequential_assurance import (
    AUTHORITY_SEPARATION_STATEMENT,
    CONTRADICTED,
    ESTABLISHED,
    METHOD_BETA_MIXTURE,
    METHOD_EMPIRICAL_BERNSTEIN,
    NOT_ESTABLISHED,
    PARTIALLY_ESTABLISHED,
    STANDING_ASSUMPTIONS,
    AssuranceEpoch,
    DecisionOutcome,
    SequentialAssuranceMonitor,
    empirical_bernstein_upper_cs,
    log_rate_eprocess,
)

EPOCH_A = AssuranceEpoch(policy="policy-v1", toolspec="ts-v1", model="model-a")
EPOCH_B = AssuranceEpoch(policy="policy-v2", toolspec="ts-v1", model="model-a")


def outcome(
    decision_id: str,
    event: bool = False,
    epoch: AssuranceEpoch = EPOCH_A,
    loss: float | None = None,
    resolved: bool = True,
    cluster_id: str | None = None,
) -> DecisionOutcome:
    return DecisionOutcome(
        decision_id=decision_id,
        event=event,
        loss=float(event) if loss is None else loss,
        epoch=epoch,
        resolved=resolved,
        verdict="accept",
        cluster_id=cluster_id,
    )


def clustered(decision_id: str, **kwargs) -> DecisionOutcome:
    """A decision in an explicit singleton cluster: the fully tagged case."""
    kwargs.setdefault("cluster_id", f"cluster-of-{decision_id}")
    return outcome(decision_id, **kwargs)


# ---------------------------------------------------------------------------
# Empirical-Bernstein confidence sequence: correctness
# ---------------------------------------------------------------------------

def test_eb_empty_stream_returns_trivial_bound() -> None:
    assert empirical_bernstein_upper_cs([], alpha=0.05) == 1.0


def test_eb_bound_contains_empirical_mean_and_shrinks() -> None:
    rng = random.Random(7)
    xs = [1.0 if rng.random() < 0.05 else 0.0 for _ in range(400)]
    for n in (50, 100, 200, 400):
        bound = empirical_bernstein_upper_cs(xs[:n], alpha=0.05)
        assert 0.0 <= bound <= 1.0
    bounds = [empirical_bernstein_upper_cs(xs[:n]) for n in (50, 100, 200, 400)]
    assert bounds[-1] < bounds[0]


def test_eb_bound_above_empirical_mean_in_seeded_runs() -> None:
    rng = random.Random(11)
    for _ in range(20):
        n = rng.randrange(20, 200)
        xs = [rng.random() * 0.3 for _ in range(n)]
        bound = empirical_bernstein_upper_cs(xs, alpha=0.05)
        assert bound >= sum(xs) / n - 1e-9


def test_eb_smaller_alpha_gives_wider_bound() -> None:
    xs = [0.1, 0.0, 0.2, 0.0, 0.1] * 20
    assert empirical_bernstein_upper_cs(xs, alpha=0.01) > empirical_bernstein_upper_cs(
        xs, alpha=0.10
    )


def test_eb_variance_adaptivity_beats_worst_case_on_low_variance_stream() -> None:
    """A near-constant low stream must get a tighter bound than the same
    count of 0/1 outcomes with the same mean; variance adaptation is the
    point of the construction."""
    low_variance = [0.05] * 200
    bernoulli_like = ([1.0] * 10) + ([0.0] * 190)
    assert empirical_bernstein_upper_cs(low_variance) < empirical_bernstein_upper_cs(
        bernoulli_like
    )


def test_eb_input_validation() -> None:
    with pytest.raises(ValueError):
        empirical_bernstein_upper_cs([0.5, 1.5])
    with pytest.raises(ValueError):
        empirical_bernstein_upper_cs([-0.1])
    with pytest.raises(ValueError):
        empirical_bernstein_upper_cs([0.1], alpha=1.0)
    with pytest.raises(ValueError):
        empirical_bernstein_upper_cs([0.1], lambda_cap=1.0)


@pytest.mark.slow
def test_eb_time_uniform_coverage_under_continuous_monitoring() -> None:
    """The true mean must stay below the bound at EVERY step, with failure
    probability at most alpha over the whole horizon. Bounded non-Bernoulli
    outcomes (Beta(0.5, 8), mean ~0.0588) exercise the fractional-loss path.
    Seeded; Ville's inequality caps the violation rate at 5%, we assert 6%.
    """
    rng = random.Random(42)
    alpha, horizon, trajectories = 0.05, 200, 300
    p_true = 0.5 / 8.5
    violations = 0
    for _ in range(trajectories):
        xs: list[float] = []
        violated = False
        for _n in range(1, horizon + 1):
            xs.append(rng.betavariate(0.5, 8.0))
            if empirical_bernstein_upper_cs(xs, alpha) < p_true:
                violated = True
                break
        violations += violated
    assert violations / trajectories <= 0.06


# ---------------------------------------------------------------------------
# Rate e-process: validity under the null, power under the alternative
# ---------------------------------------------------------------------------

def test_eprocess_starts_at_one_and_validates_input() -> None:
    assert log_rate_eprocess([], p0=0.05) == 0.0
    with pytest.raises(ValueError):
        log_rate_eprocess([False], p0=0.0)


@pytest.mark.slow
def test_eprocess_never_exceeds_alpha_budget_under_null() -> None:
    """Seeded trajectories at the null boundary p = p0: the rejection rate
    over continuous monitoring must stay at or below alpha (plus slack)."""
    rng = random.Random(123)
    p0, alpha, horizon, trajectories = 0.10, 0.05, 300, 400
    log_threshold = math.log(1.0 / alpha)
    rejections = 0
    for _ in range(trajectories):
        events: list[bool] = []
        rejected = False
        for _n in range(horizon):
            events.append(rng.random() < p0)
            if log_rate_eprocess(events, p0) >= log_threshold:
                rejected = True
                break
        rejections += rejected
    assert rejections / trajectories <= 0.06


@pytest.mark.slow
def test_eprocess_rejects_eventually_when_rate_is_below_threshold() -> None:
    """Power check: with a true rate well under p0 the process must cross
    1/alpha within a moderate horizon in essentially all seeded runs."""
    rng = random.Random(99)
    p0, alpha, horizon, trajectories = 0.10, 0.05, 400, 50
    log_threshold = math.log(1.0 / alpha)
    rejections = 0
    for _ in range(trajectories):
        events: list[bool] = []
        for _n in range(horizon):
            events.append(rng.random() < 0.02)
            if log_rate_eprocess(events, p0) >= log_threshold:
                rejections += 1
                break
    assert rejections / trajectories >= 0.95


# ---------------------------------------------------------------------------
# Monitor: epoch reset, premise gate, receipt
# ---------------------------------------------------------------------------

def test_epoch_change_closes_segment_and_restarts_counts() -> None:
    monitor = SequentialAssuranceMonitor(alpha=0.05, threshold=0.05)
    monitor.observe_all(clustered(f"a-{i}", epoch=EPOCH_A) for i in range(10))
    monitor.observe_all(clustered(f"b-{i}", epoch=EPOCH_B) for i in range(5))
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    assert receipt.epoch_resets == 1
    assert [s.n_resolved for s in receipt.segments] == [10, 5]
    assert receipt.segments[0].epoch == EPOCH_A
    assert receipt.segments[1].epoch == EPOCH_B
    # No borrowing across the boundary: the second segment's bound is the
    # n=5 bound, which must be wider than the n=10 bound at k=0.
    upper_first = receipt.segments[0].upper_bound
    upper_second = receipt.segments[1].upper_bound
    assert upper_first is not None and upper_second is not None
    assert upper_second > upper_first


def test_any_epoch_field_change_resets() -> None:
    for field_name in ("policy", "toolspec", "model"):
        other = AssuranceEpoch(
            policy="policy-v2" if field_name == "policy" else EPOCH_A.policy,
            toolspec="ts-v2" if field_name == "toolspec" else EPOCH_A.toolspec,
            model="model-b" if field_name == "model" else EPOCH_A.model,
        )
        monitor = SequentialAssuranceMonitor()
        monitor.observe(outcome("d-1", epoch=EPOCH_A))
        monitor.observe(outcome("d-2", epoch=other))
        assert monitor.epoch_resets == 1, field_name


def test_duplicate_decision_id_flips_segment_to_contradicted() -> None:
    """The overlapping-window failure mode: one decision counted twice.
    The duplicate is withheld from n and the bounds are withheld."""
    monitor = SequentialAssuranceMonitor()
    monitor.observe_all(clustered(f"d-{i}") for i in range(10))
    monitor.observe(clustered("d-3"))  # recount
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    segment = receipt.segments[0]
    assert segment.n_resolved == 10
    assert segment.assumption_status == CONTRADICTED
    assert receipt.assumption_status == CONTRADICTED
    assert segment.upper_bound is None
    assert segment.supplementary_bounds is None
    assert segment.diagnostics is not None
    assert segment.diagnostics["valid"] is False
    identity = next(
        c for c in segment.premise_checks if c.name == "unique_decision_identity"
    )
    assert identity.status == "contradicted"
    assert "d-3" in identity.detail


def test_duplicate_across_epochs_is_still_recounting() -> None:
    monitor = SequentialAssuranceMonitor()
    monitor.observe(clustered("d-1", epoch=EPOCH_A))
    monitor.observe(clustered("d-1", epoch=EPOCH_B))  # same decision, new epoch
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    assert receipt.segments[1].n_resolved == 0
    assert receipt.segments[1].assumption_status == CONTRADICTED
    assert receipt.assumption_status == CONTRADICTED


def test_unresolved_outcomes_are_excluded_and_counted() -> None:
    monitor = SequentialAssuranceMonitor()
    monitor.observe_all(clustered(f"d-{i}") for i in range(5))
    monitor.observe(clustered("d-pending", resolved=False))
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    assert receipt.segments[0].n_resolved == 5
    assert receipt.excluded_unresolved == 1
    assert receipt.to_dict()["excluded"] == {"unresolved": 1}
    # An exclusion degrades the segment: a selection effect cannot be ruled out.
    assert receipt.segments[0].assumption_status == PARTIALLY_ESTABLISHED


def test_missing_cluster_ids_degrade_to_partially_established() -> None:
    monitor = SequentialAssuranceMonitor()
    monitor.observe_all(outcome(f"d-{i}") for i in range(8))
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    segment = receipt.segments[0]
    assert segment.assumption_status == PARTIALLY_ESTABLISHED
    # Degraded, not contradicted: bounds stay quotable, flagged.
    assert segment.upper_bound is not None
    cluster = next(
        c for c in segment.premise_checks if c.name == "independence_cluster_coverage"
    )
    assert cluster.status == "degraded"


def test_shared_cluster_degrades_to_partially_established() -> None:
    monitor = SequentialAssuranceMonitor()
    for i in range(6):
        monitor.observe(outcome(f"d-{i}", cluster_id="same-template"))
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    segment = receipt.segments[0]
    assert segment.assumption_status == PARTIALLY_ESTABLISHED
    assert segment.n_clusters == 1
    assert segment.n_resolved == 6


def test_invalid_loss_and_empty_identity_raise() -> None:
    with pytest.raises(ValueError):
        outcome("d-1", loss=1.5)
    with pytest.raises(ValueError):
        outcome("", loss=0.0)
    with pytest.raises(ValueError):
        AssuranceEpoch(policy="", toolspec="ts", model="m")


def test_monitor_rejects_bad_alpha_and_threshold() -> None:
    with pytest.raises(ValueError):
        SequentialAssuranceMonitor(alpha=0.0)
    with pytest.raises(ValueError):
        SequentialAssuranceMonitor(threshold=1.0)


# ---------------------------------------------------------------------------
# Receipt schema and authority separation
# ---------------------------------------------------------------------------

def _clean_receipt() -> dict:
    monitor = SequentialAssuranceMonitor(alpha=0.05, threshold=0.05)
    monitor.observe_all(clustered(f"d-{i}", event=(i == 7)) for i in range(20))
    return monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
        git_commit=None,
    ).to_dict()


def test_receipt_schema_fields() -> None:
    receipt = _clean_receipt()
    assert receipt["schema"] == "sequential_assurance_receipt_v1"
    assert receipt["assumption_status"] == ESTABLISHED
    assert receipt["authority_separation"] == AUTHORITY_SEPARATION_STATEMENT
    assert receipt["standing_assumptions"] == STANDING_ASSUMPTIONS
    assert receipt["outcome_unit"] == "resolved_decision"
    segment = receipt["segments"][0]
    assert segment["n_resolved"] == 20
    assert segment["false_accepts"] == 1
    assert segment["point_estimate"] == pytest.approx(1 / 20)
    assert segment["method"] == METHOD_BETA_MIXTURE
    assert segment["epoch_id"] == "policy=policy-v1|toolspec=ts-v1|model=model-a"
    assert segment["upper_bound"] == pytest.approx(
        bernoulli_upper_confidence_sequence(1, 20, alpha=0.05)
    )
    assert 0.0 < segment["supplementary_bounds"][METHOD_EMPIRICAL_BERNSTEIN] <= 1.0
    assert segment["e_process"]["null"] == "event rate >= 0.05"
    assert isinstance(segment["e_process"]["reject_null_at_alpha"], bool)


def test_empirical_bernstein_can_be_the_preregistered_method() -> None:
    monitor = SequentialAssuranceMonitor(method=METHOD_EMPIRICAL_BERNSTEIN)
    monitor.observe_all(clustered(f"d-{i}", event=(i == 0)) for i in range(10))
    segment = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    ).segments[0]
    assert segment.method == METHOD_EMPIRICAL_BERNSTEIN
    assert segment.upper_bound == pytest.approx(
        empirical_bernstein_upper_cs([1.0] + [0.0] * 9, alpha=0.05)
    )
    assert segment.supplementary_bounds is not None
    assert METHOD_BETA_MIXTURE in segment.supplementary_bounds


def test_unknown_method_rejected() -> None:
    with pytest.raises(ValueError, match="preregistered method"):
        SequentialAssuranceMonitor(method="wilson")


def test_receipt_is_deterministic() -> None:
    assert _clean_receipt() == _clean_receipt()


def test_receipt_bounds_agree_with_direct_calls() -> None:
    """The receipt must not drift from the instruments it wraps."""
    xs = [0.0, 1.0, 0.0, 0.0, 0.25, 0.0]
    monitor = SequentialAssuranceMonitor(
        alpha=0.05, threshold=0.05, method=METHOD_EMPIRICAL_BERNSTEIN
    )
    for i, x in enumerate(xs):
        monitor.observe(clustered(f"d-{i}", event=x >= 1.0, loss=x))
    segment = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    ).segments[0]
    assert segment.upper_bound == pytest.approx(
        empirical_bernstein_upper_cs(xs, alpha=0.05)
    )
    assert segment.e_process["log_e_value"] == pytest.approx(
        log_rate_eprocess([x >= 1.0 for x in xs], 0.05)
    )


# ---------------------------------------------------------------------------
# Episode-record adapter
# ---------------------------------------------------------------------------

def test_adapter_maps_verdict_truth_grid() -> None:
    records = [
        {"id": "e-1", "verdict": "accept", "ground_truth": "benign"},
        {"id": "e-2", "verdict": "ACCEPT", "ground_truth": "harmful"},
        {"id": "e-3", "verdict": "verify", "ground_truth": "harmful"},
        {"id": "e-4", "verdict": "accept", "ground_truth": "unknown"},
        {"id": "e-5", "verdict": "accept", "ground_truth": None},
    ]
    stream = outcomes_from_episode_records(records, epoch=EPOCH_A)
    # verify rows are outside the accept population.
    assert [o.decision_id for o in stream] == ["e-1", "e-2", "e-4", "e-5"]
    assert [(o.event, o.resolved) for o in stream] == [
        (False, True),
        (True, True),
        (False, False),
        (False, False),
    ]


def test_empty_monitor_receipt_is_not_established() -> None:
    receipt = SequentialAssuranceMonitor().receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    assert receipt.segments == ()
    assert receipt.assumption_status == NOT_ESTABLISHED


def test_adapter_population_all_keeps_every_verdict() -> None:
    records = [
        {"id": "e-1", "verdict": "accept", "ground_truth": "benign"},
        {"id": "e-2", "verdict": "escalate", "ground_truth": "harmful"},
    ]
    stream = outcomes_from_episode_records(records, epoch=EPOCH_A, population="all")
    assert len(stream) == 2


def test_adapter_requires_decision_identity() -> None:
    with pytest.raises(ValueError, match="no id"):
        outcomes_from_episode_records([{"verdict": "accept"}], epoch=EPOCH_A)


def test_adapter_end_to_end_receipt() -> None:
    records = [
        {"id": f"e-{i}", "verdict": "accept", "ground_truth": "benign"}
        for i in range(24)
    ]
    monitor = SequentialAssuranceMonitor(alpha=0.05, threshold=0.05)
    monitor.observe_all(outcomes_from_episode_records(records, epoch=EPOCH_A))
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition="accept-verdict decisions",
        input_description="synthetic test stream",
        generated_by="tests/test_sequential_assurance.py",
    )
    segment = receipt.segments[0]
    assert segment.n_resolved == 24
    assert segment.false_accepts == 0
    # Fixture rows carry no cluster identifiers: degraded, not established.
    assert segment.assumption_status == PARTIALLY_ESTABLISHED
    assert segment.upper_bound == pytest.approx(
        bernoulli_upper_confidence_sequence(0, 24, alpha=0.05)
    )
