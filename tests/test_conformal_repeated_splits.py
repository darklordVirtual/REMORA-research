"""Tests for experiments.conformal_repeated_splits."""
from __future__ import annotations



def test_repeated_splits_output_exists():
    from experiments.conformal_repeated_splits import run
    results = run()
    assert isinstance(results, list)
    assert len(results) == 3  # 3 target risks


def test_repeated_splits_structure():
    from experiments.conformal_repeated_splits import run
    results = run()
    for entry in results:
        assert "target_risk" in entry
        assert "n_seeds" in entry
        assert entry["n_seeds"] == 20
        assert "mean_holdout_risk" in entry
        assert "max_holdout_risk" in entry
        assert "failures_by_point_estimate" in entry
        assert "failures_by_upper_bound" in entry
        assert "notes" in entry


def test_repeated_splits_honest_failures():
    """failures_by_upper_bound >= failures_by_point_estimate (UCB is always more conservative)."""
    from experiments.conformal_repeated_splits import run
    results = run()
    for entry in results:
        assert entry["failures_by_upper_bound"] >= entry["failures_by_point_estimate"]
