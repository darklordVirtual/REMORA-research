# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.uncertainty.decompose — epistemic/aleatoric uncertainty decomposition."""
from __future__ import annotations

import pytest

from remora.uncertainty.decompose import (
    UncertaintyEstimate,
    decompose,
    oracle_responses_to_probs,
    uncertainty_phase,
)


# ---------------------------------------------------------------------------
# decompose — basic contracts
# ---------------------------------------------------------------------------

class TestDecomposeContracts:
    def test_empty_input_returns_escalate_human(self):
        result = decompose([])
        assert result.action == "escalate_human"
        assert result.n_oracles == 0

    def test_single_oracle_high_confidence_accept(self):
        # Single oracle, highly confident True → low aleatoric
        result = decompose([0.95], aleatoric_threshold=0.50)
        # p=0.95: aleatoric = p*(1-p) / 0.25 = 0.95*0.05/0.25 = 0.19
        assert result.aleatoric < 0.50
        # With only 1 oracle, epistemic is maximal (we can't know without others)
        assert result.n_oracles == 1

    def test_all_agree_high_confidence_low_epistemic(self):
        """Three oracles all say True with high confidence → low epistemic."""
        result = decompose([0.9, 0.92, 0.88])
        # Variance of {0.9, 0.92, 0.88}: small → epistemic near 0
        assert result.epistemic < 0.20

    def test_all_disagree_high_epistemic(self):
        """One oracle says True (p=0.95), another says False (p=0.05)."""
        result = decompose([0.95, 0.05])
        # These are maximally opposed → high inter-oracle variance
        assert result.epistemic > 0.50

    def test_all_uncertain_high_aleatoric(self):
        """All oracles are individually uncertain (p ≈ 0.5)."""
        result = decompose([0.5, 0.5, 0.5])
        # p*(1-p) = 0.25 → normalised aleatoric = 1.0
        assert abs(result.aleatoric - 1.0) < 1e-6

    def test_normalised_values_in_unit_interval(self):
        for probs in [
            [0.1, 0.9],
            [0.5, 0.5, 0.5],
            [0.9, 0.9, 0.9],
            [0.1, 0.2, 0.8, 0.9],
        ]:
            result = decompose(probs)
            assert 0.0 <= result.epistemic <= 1.0, f"epistemic={result.epistemic}"
            assert 0.0 <= result.aleatoric <= 1.0, f"aleatoric={result.aleatoric}"
            assert 0.0 <= result.total <= 1.0, f"total={result.total}"

    def test_probs_clipped_to_unit_interval(self):
        """Input values outside [0,1] are clipped — should not crash."""
        result = decompose([1.5, -0.2, 0.5])
        assert 0.0 <= result.epistemic <= 1.0


# ---------------------------------------------------------------------------
# Action recommendations
# ---------------------------------------------------------------------------

class TestActionRecommendations:
    def test_unanimous_confident_is_accept(self):
        result = decompose([0.9, 0.91, 0.89],
                           epistemic_threshold=0.35,
                           aleatoric_threshold=0.50)
        assert result.action == "accept"

    def test_disagreement_with_confident_oracles_is_add_oracles(self):
        """Oracles strongly disagree (high epistemic) but individually confident (low aleatoric)."""
        result = decompose([0.95, 0.05, 0.90],
                           epistemic_threshold=0.10,
                           aleatoric_threshold=0.50)
        assert result.action == "add_oracles"

    def test_consensus_uncertainty_is_escalate_human(self):
        """All oracles are uncertain → question is genuinely ambiguous."""
        result = decompose([0.52, 0.48, 0.50],
                           epistemic_threshold=0.35,
                           aleatoric_threshold=0.30)
        assert result.action == "escalate_human"

    def test_all_high_is_escalate_adversarial(self):
        """Both high epistemic and high aleatoric → worst case.

        Use [0.7, 0.5, 0.3]: oracles spread from 0.3–0.7 around 0.5 so
        inter-oracle variance is non-trivial (epistemic > 0.05) while
        each oracle is individually near-uncertain (aleatoric > 0.30).
        """
        result = decompose([0.7, 0.5, 0.3],
                           epistemic_threshold=0.05,
                           aleatoric_threshold=0.30)
        assert result.action == "escalate_adversarial"


# ---------------------------------------------------------------------------
# oracle_responses_to_probs
# ---------------------------------------------------------------------------

class TestOracleResponsestoProbs:
    def test_true_answer_gives_confidence_as_prob(self):
        probs = oracle_responses_to_probs([True], [0.8])
        assert abs(probs[0] - 0.8) < 1e-9

    def test_false_answer_inverts_confidence(self):
        probs = oracle_responses_to_probs([False], [0.8])
        assert abs(probs[0] - 0.2) < 1e-9

    def test_none_answer_gives_half(self):
        probs = oracle_responses_to_probs([None], [0.9])
        assert abs(probs[0] - 0.5) < 1e-9

    def test_mixed_answers(self):
        probs = oracle_responses_to_probs([True, False, None], [0.9, 0.7, 0.6])
        assert abs(probs[0] - 0.9) < 1e-9
        assert abs(probs[1] - 0.3) < 1e-9
        assert abs(probs[2] - 0.5) < 1e-9

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            oracle_responses_to_probs([True, False], [0.8])

    def test_confidence_clipped(self):
        probs = oracle_responses_to_probs([True], [1.5])
        assert probs[0] <= 1.0
        probs2 = oracle_responses_to_probs([True], [-0.1])
        assert probs2[0] >= 0.0


# ---------------------------------------------------------------------------
# uncertainty_phase
# ---------------------------------------------------------------------------

class TestUncertaintyPhase:
    def _make_estimate(self, action: str) -> UncertaintyEstimate:
        return UncertaintyEstimate(
            epistemic=0.0, aleatoric=0.0, total=0.0,
            mean_prob=0.9, n_oracles=3, action=action
        )

    def test_accept_maps_to_confident(self):
        assert uncertainty_phase(self._make_estimate("accept")) == "confident"

    def test_add_oracles_maps_to_epistemically_uncertain(self):
        assert uncertainty_phase(self._make_estimate("add_oracles")) == "epistemically_uncertain"

    def test_escalate_human_maps_to_aleatorically_uncertain(self):
        assert uncertainty_phase(self._make_estimate("escalate_human")) == "aleatorically_uncertain"

    def test_escalate_adversarial_maps_to_maximally_uncertain(self):
        assert uncertainty_phase(self._make_estimate("escalate_adversarial")) == "maximally_uncertain"


# ---------------------------------------------------------------------------
# Total variance decomposition (law of total variance)
# ---------------------------------------------------------------------------

class TestTotalVarianceDecomposition:
    def test_total_bounded_by_sum(self):
        """total = min(1, epistemic + aleatoric) — never exceeds 1."""
        for probs in [[0.5, 0.5], [0.1, 0.9], [0.3, 0.7, 0.5]]:
            est = decompose(probs)
            assert est.total <= 1.0 + 1e-9
            # total should be at most epistemic + aleatoric
            assert est.total <= est.epistemic + est.aleatoric + 1e-9

    def test_perfect_agreement_total_near_aleatoric(self):
        """When oracles perfectly agree, epistemic ≈ 0, total ≈ aleatoric."""
        est = decompose([0.9, 0.9, 0.9])
        assert est.epistemic < 0.01
        assert abs(est.total - est.aleatoric) < 1e-6
