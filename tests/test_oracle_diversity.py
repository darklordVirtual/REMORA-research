# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.oracles.diversity — oracle diversity tracker and swarm selection."""
from __future__ import annotations

import pytest

from remora.oracles.diversity import (
    OracleDiversityTracker,
    diversity_score,
    select_diverse_swarm,
)


# ---------------------------------------------------------------------------
# OracleDiversityTracker
# ---------------------------------------------------------------------------

class TestOracleDiversityTracker:
    def test_rho_self_is_one(self):
        t = OracleDiversityTracker()
        assert t.rho("A", "A") == 1.0

    def test_rho_unknown_pair_returns_prior(self):
        t = OracleDiversityTracker()
        assert t.rho("X", "Y") == 0.5

    def test_observe_updates_rho(self):
        t = OracleDiversityTracker()
        # 3 agreements, 1 disagreement → ρ = 0.75
        for _ in range(3):
            t.observe("A", "B", agreed=True)
        t.observe("A", "B", agreed=False)
        assert abs(t.rho("A", "B") - 0.75) < 1e-9

    def test_observe_symmetric(self):
        t = OracleDiversityTracker()
        t.observe("A", "B", agreed=True)
        t.observe("A", "B", agreed=False)
        assert t.rho("A", "B") == t.rho("B", "A")

    def test_observe_batch(self):
        t = OracleDiversityTracker()
        # All agree on True — 2 observations each to exceed the prior threshold
        t.observe_batch(["A", "B", "C"], [True, True, True])
        t.observe_batch(["A", "B", "C"], [True, True, True])
        assert t.rho("A", "B") == 1.0
        assert t.rho("A", "C") == 1.0
        assert t.rho("B", "C") == 1.0

    def test_observe_batch_disagreement(self):
        t = OracleDiversityTracker()
        # Use 2 observations per pair so we're past the 1-sample case
        t.observe_batch(["A", "B", "C"], [True, False, True])
        t.observe_batch(["A", "B", "C"], [True, False, True])
        # A-B disagree (0/2), A-C agree (2/2), B-C disagree (0/2)
        assert t.rho("A", "B") == 0.0
        assert t.rho("A", "C") == 1.0
        assert t.rho("B", "C") == 0.0

    def test_observe_batch_length_mismatch_raises(self):
        t = OracleDiversityTracker()
        with pytest.raises(ValueError):
            t.observe_batch(["A", "B"], [True])

    def test_rolling_window(self):
        t = OracleDiversityTracker(window_size=4)
        # Fill with agreements
        for _ in range(4):
            t.observe("A", "B", agreed=True)
        assert t.rho("A", "B") == 1.0
        # Push in disagreements — old agreements roll out
        for _ in range(4):
            t.observe("A", "B", agreed=False)
        assert t.rho("A", "B") == 0.0

    def test_known_oracles(self):
        t = OracleDiversityTracker()
        t.observe("llama", "claude", agreed=True)
        t.observe("llama", "gemma", agreed=False)
        known = t.known_oracles()
        assert "llama" in known
        assert "claude" in known
        assert "gemma" in known

    def test_mean_rho_single_oracle(self):
        t = OracleDiversityTracker()
        assert t.mean_rho(["A"]) == 0.0

    def test_mean_rho_identical_oracles(self):
        t = OracleDiversityTracker()
        for _ in range(10):
            t.observe("A", "B", agreed=True)
        assert t.mean_rho(["A", "B"]) == 1.0

    def test_diversity_score_identical(self):
        """Identical oracles → diversity score near 0."""
        t = OracleDiversityTracker()
        for _ in range(20):
            t.observe("A", "B", agreed=True)
        score = t.diversity_score(["A", "B"])
        assert score < 0.1

    def test_diversity_score_independent(self):
        """50/50 agreement → diversity score near 1."""
        t = OracleDiversityTracker()
        for i in range(20):
            t.observe("A", "B", agreed=(i % 2 == 0))
        score = t.diversity_score(["A", "B"])
        assert score > 0.9

    def test_high_correlation_pairs(self):
        t = OracleDiversityTracker(high_correlation_threshold=0.70)
        for _ in range(10):
            t.observe("A", "B", agreed=True)
        for _ in range(5):
            t.observe("A", "B", agreed=False)
        # ρ = 10/15 ≈ 0.67 — below threshold, not reported
        pairs = t.high_correlation_pairs()
        assert all(rho > 0.70 for _, _, rho in pairs)

    def test_correlation_report_keys(self):
        t = OracleDiversityTracker()
        t.observe("X", "Y", agreed=True)
        report = t.correlation_report(["X", "Y"])
        assert "rho_matrix" in report
        assert "mean_rho" in report
        assert "diversity_score" in report


# ---------------------------------------------------------------------------
# select_diverse_swarm
# ---------------------------------------------------------------------------

class TestSelectDiverseSwarm:
    def _tracker_with_known_rhos(self) -> OracleDiversityTracker:
        """Create a tracker where A-B are highly correlated, C-D are independent."""
        t = OracleDiversityTracker()
        for _ in range(20):
            # A and B always agree (ρ=1)
            t.observe("A", "B", agreed=True)
            # C and D always disagree (ρ=0)
            t.observe("C", "D", agreed=False)
            # A-C, A-D, B-C, B-D are 50/50 independent
        for i in range(20):
            agreed = (i % 2 == 0)
            t.observe("A", "C", agreed=agreed)
            t.observe("A", "D", agreed=agreed)
            t.observe("B", "C", agreed=agreed)
            t.observe("B", "D", agreed=agreed)
        return t

    def test_selects_k_oracles(self):
        t = self._tracker_with_known_rhos()
        selected = select_diverse_swarm(["A", "B", "C", "D"], t, k=3)
        assert len(selected) == 3

    def test_avoids_highly_correlated_pair(self):
        """A and B are perfectly correlated — the diverse selection should not pick both."""
        t = self._tracker_with_known_rhos()
        selected = select_diverse_swarm(["A", "B", "C", "D"], t, k=2)
        # Should prefer A (or B) and C (or D) over A+B
        assert not ("A" in selected and "B" in selected), \
            f"Diverse selection should not pick A and B together, got {selected}"

    def test_k_equals_candidates(self):
        t = OracleDiversityTracker()
        selected = select_diverse_swarm(["A", "B", "C"], t, k=3)
        assert set(selected) == {"A", "B", "C"}

    def test_k_zero_returns_empty(self):
        t = OracleDiversityTracker()
        assert select_diverse_swarm(["A", "B"], t, k=0) == []

    def test_empty_candidates_returns_empty(self):
        t = OracleDiversityTracker()
        assert select_diverse_swarm([], t, k=3) == []

    def test_seed_oracle_always_included(self):
        t = self._tracker_with_known_rhos()
        selected = select_diverse_swarm(["A", "B", "C", "D"], t, k=2, seed_oracle="C")
        assert "C" in selected

    def test_k_larger_than_candidates_capped(self):
        t = OracleDiversityTracker()
        selected = select_diverse_swarm(["A", "B"], t, k=10)
        assert len(selected) == 2


# ---------------------------------------------------------------------------
# diversity_score (matrix-based)
# ---------------------------------------------------------------------------

class TestDiversityScoreMatrix:
    def test_identical_oracles(self):
        matrix = {"A": {"A": 1.0, "B": 1.0}, "B": {"A": 1.0, "B": 1.0}}
        score = diversity_score(["A", "B"], matrix)
        assert score == 0.0

    def test_perfectly_independent(self):
        # ρ = 0.5 → diversity = (1 - 0.5) / 0.5 = 1.0
        matrix = {"A": {"A": 1.0, "B": 0.5}, "B": {"A": 0.5, "B": 1.0}}
        score = diversity_score(["A", "B"], matrix)
        assert abs(score - 1.0) < 1e-9

    def test_single_oracle_returns_one(self):
        score = diversity_score(["A"], {})
        assert score == 1.0

    def test_empty_returns_one(self):
        assert diversity_score([], {}) == 1.0

    def test_range_is_zero_to_one(self):
        for rho in [0.0, 0.25, 0.5, 0.75, 1.0]:
            matrix = {"X": {"X": 1.0, "Y": rho}, "Y": {"X": rho, "Y": 1.0}}
            score = diversity_score(["X", "Y"], matrix)
            assert 0.0 <= score <= 1.0
