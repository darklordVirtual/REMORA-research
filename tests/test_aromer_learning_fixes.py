# Author: Stian Skogbrott
# License: Apache-2.0
"""Regression tests for the v0.2 learning-loop fixes.

Step 2 — friction smoothing: the AII friction component was computed on a
single sliding-window snapshot whose composition swung 0.07↔0.635 between
cycles, dominating AII variance. Smoothing tracks sustained friction.

Step 3 — oracle bandit honesty: the bridge credited the whole oracle pool
with one shared correctness signal, driving every arm to an identical
posterior (live: alpha=19287, beta=1 for all three). The bandit must only
credit oracles that were actually consulted.
"""
from __future__ import annotations

from statistics import pstdev

import pytest

from remora.aromer.intelligence.score import (
    friction_score,
    friction_score_smoothed,
)


class TestFrictionSmoothing:
    def test_smoothing_reduces_variance(self):
        # A noisy benign-review series with a stable ~0.20 mean.
        noisy = [0.07, 0.635, 0.11, 0.55, 0.09, 0.30, 0.12, 0.42]
        raw = [friction_score(r) for r in noisy]
        smoothed = [
            friction_score_smoothed(noisy[: i + 1]) for i in range(len(noisy))
        ]
        # The smoothed friction series must be strictly less volatile.
        assert pstdev(smoothed) < pstdev(raw)

    def test_smoothing_tracks_sustained_change(self):
        # A genuine, sustained rise in friction must still move the score down.
        low = friction_score_smoothed([0.05] * 8)
        high = friction_score_smoothed([0.05] * 4 + [0.50] * 8)
        assert high < low

    def test_empty_falls_back_to_baseline(self):
        assert friction_score_smoothed([]) == pytest.approx(friction_score(0.27))

    def test_single_value_matches_raw(self):
        assert friction_score_smoothed([0.15]) == pytest.approx(friction_score(0.15))


class TestOracleCreditAssignment:
    def _bridge(self, tmp_path):
        from remora.aromer.integration.bridge import AromerAdapterBridge
        return AromerAdapterBridge(state_path=tmp_path / "bridge_state.json")

    def _episode(self, oracles_used):
        from remora.aromer.experience.episode import Episode, GroundTruth
        ep = Episode(
            domain="database", risk_tier="critical", action_type="destructive_write",
            phase="critical", trust_score=0.3, entropy_H=0.6, dissensus_D=0.3,
            verdict="ESCALATE", confidence=0.8, oracles_used=oracles_used,
        )
        # Resolve to a correct outcome so record_outcome credits the bandit.
        ep.record_ground_truth(GroundTruth.HARMFUL)
        return ep

    def test_only_consulted_oracle_credited(self, tmp_path):
        bridge = self._bridge(tmp_path)
        a0 = dict(bridge._bandit._alpha)
        bridge.record_outcome(self._episode(["cf_strong"]))
        a1 = bridge._bandit._alpha
        # cf_strong credited; the other two arms untouched.
        assert a1["cf_strong"] == a0["cf_strong"] + 1.0
        assert a1["cf_fast"] == a0["cf_fast"]
        assert a1["cf_diverse"] == a0["cf_diverse"]

    def test_unknown_provenance_credits_primary_only(self, tmp_path):
        bridge = self._bridge(tmp_path)
        a0 = dict(bridge._bandit._alpha)
        bridge.record_outcome(self._episode([]))
        a1 = bridge._bandit._alpha
        credited = [o for o in a1 if a1[o] > a0[o]]
        # Exactly one arm (the primary) is credited — never the whole pool.
        assert len(credited) == 1
