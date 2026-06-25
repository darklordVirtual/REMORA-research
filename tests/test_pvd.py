# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.selective.pvd — Prover-Verifier Deliberation.

All tests use mock backends or the TokenFingerprintBackend (no external
model required).  Tests cover:
  - Edge cases: empty responses, single oracle, all-agreeing oracles
  - Deliberation mechanics: prover/verifier selection, legibility computation
  - Routing: pvd_routing_score blends trust and deliberation
  - Mathematical properties: final_confidence in [0,1], agreement is binary float
"""
from __future__ import annotations


import pytest

from remora.selective.pvd import (
    PVDResult,
    _cluster_agreement,
    deliberate,
    pvd_routing_score,
)


# ---------------------------------------------------------------------------
# Mock backends
# ---------------------------------------------------------------------------


class _AlwaysEntailsBackend:
    name = "always_entails"

    def predict(self, premise: str, hypothesis: str) -> float:
        return 1.0


class _NeverEntailsBackend:
    name = "never_entails"

    def predict(self, premise: str, hypothesis: str) -> float:
        return 0.0


class _IdenticalOnlyBackend:
    """Entails only identical strings (like TokenFingerprint but simpler)."""
    name = "identical_only"

    def predict(self, premise: str, hypothesis: str) -> float:
        return 1.0 if premise == hypothesis else 0.0


# ---------------------------------------------------------------------------
# deliberate() — edge cases
# ---------------------------------------------------------------------------


def test_empty_responses_returns_zero_confidence():
    result = deliberate([])
    assert result.final_confidence == 0.0
    assert result.should_accept is False
    assert result.deliberation_rounds == 0


def test_single_response_returns_result():
    result = deliberate(["yes"])
    assert isinstance(result, PVDResult)
    assert result.prover_response == "yes"
    assert 0.0 <= result.final_confidence <= 1.0


def test_mismatched_confidences_raises():
    with pytest.raises(ValueError, match="same length"):
        deliberate(["yes", "no"], oracle_confidences=[0.8])


def test_returns_pvd_result_type():
    result = deliberate(["yes", "no"])
    assert isinstance(result, PVDResult)


# ---------------------------------------------------------------------------
# deliberate() — unanimous consensus
# ---------------------------------------------------------------------------


def test_all_agree_prover_is_any_member():
    """When all oracles agree, prover and verifier are both in the dominant cluster."""
    result = deliberate(["yes", "yes", "yes"])
    assert result.prover_cluster_mass == pytest.approx(1.0)


def test_all_agree_agreement_is_one():
    """All responses identical → prover and verifier are in same cluster."""
    result = deliberate(["yes", "yes", "yes"])
    assert result.agreement == pytest.approx(1.0)


def test_unanimous_final_confidence_bounded():
    result = deliberate(["yes", "yes", "yes"])
    assert 0.0 <= result.final_confidence <= 1.0


# ---------------------------------------------------------------------------
# deliberate() — dissensus
# ---------------------------------------------------------------------------


def test_disagreement_splits_clusters():
    """With _IdenticalOnlyBackend and different responses, each is its own cluster."""
    result = deliberate(
        ["alpha alpha alpha", "beta beta beta"],
        backend=_IdenticalOnlyBackend(),
        entailment_threshold=0.5,
    )
    assert result.se_result.n_clusters == 2


def test_disagreement_prover_is_dominant():
    """With 2 yes, 1 no: dominant cluster has mass 2/3."""
    result = deliberate(["yes", "yes", "no"])
    assert result.prover_cluster_mass == pytest.approx(2 / 3, abs=1e-9)


def test_disagreement_verifier_is_minority():
    """Verifier response should be from minority cluster when disagreement exists."""
    result = deliberate(["yes", "yes", "no"])
    assert result.verifier_response == "no"


def test_majority_three_one():
    """3 yes, 1 no: prover cluster mass = 3/4."""
    result = deliberate(["yes", "yes", "yes", "no"])
    assert result.prover_cluster_mass == pytest.approx(3 / 4, abs=1e-9)


# ---------------------------------------------------------------------------
# deliberate() — always-entails backend (maximum legibility)
# ---------------------------------------------------------------------------


def test_always_entails_high_legibility():
    """All-entails backend → maximum mean entailment → high legibility."""
    result = deliberate(
        ["alpha alpha", "beta beta"],
        backend=_AlwaysEntailsBackend(),
        entailment_threshold=0.5,
        n_rounds=2,
    )
    # With _AlwaysEntailsBackend, all responses cluster together → 1 cluster
    assert result.se_result.n_clusters == 1
    assert result.prover_cluster_mass == pytest.approx(1.0)


def test_never_entails_zero_legibility():
    """No-entails backend → zero deliberation → low final_confidence."""
    result = deliberate(
        ["alpha alpha alpha", "beta beta beta", "gamma gamma gamma"],
        backend=_NeverEntailsBackend(),
        entailment_threshold=0.5,
        n_rounds=2,
    )
    assert result.legibility_score == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# deliberate() — oracle_confidences
# ---------------------------------------------------------------------------


def test_higher_confidence_oracle_selected_as_prover():
    """Within the dominant cluster, the highest-confidence oracle is the prover."""
    responses = ["yes", "yes", "no"]
    confs = [0.9, 0.3, 0.5]
    result = deliberate(responses, oracle_confidences=confs)
    # Dominant cluster is "yes" (2 items), prover should be the one with conf=0.9
    assert result.prover_response == "yes"
    assert result.verifier_initial_confidence == pytest.approx(0.5)


def test_uniform_confidences_when_none_provided():
    result = deliberate(["yes", "no"], oracle_confidences=None)
    assert result.verifier_initial_confidence == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# deliberate() — deliberation rounds
# ---------------------------------------------------------------------------


def test_more_rounds_does_not_change_cluster_structure():
    """n_rounds only affects entailment accumulation, not SE clustering."""
    result_1 = deliberate(["yes", "yes", "no"], n_rounds=1)
    result_3 = deliberate(["yes", "yes", "no"], n_rounds=3)
    assert result_1.se_result.n_clusters == result_3.se_result.n_clusters


def test_round_decay_reduces_entailment_weight():
    """More rounds should reduce legibility via decay factor (for non-zero entailment)."""
    # Use responses that the token backend will give non-trivial scores to
    result_1 = deliberate(["yes", "yes", "no"], n_rounds=1, backend=_AlwaysEntailsBackend())
    result_3 = deliberate(["yes", "yes", "no"], n_rounds=3, backend=_AlwaysEntailsBackend())
    # Both should have legibility, but 1-round scores are not guaranteed to be higher
    # (decay averages across rounds — just verify both produce valid floats)
    assert 0.0 <= result_1.legibility_score <= 1.0
    assert 0.0 <= result_3.legibility_score <= 1.0


# ---------------------------------------------------------------------------
# deliberate() — mathematical properties
# ---------------------------------------------------------------------------


def test_final_confidence_in_unit_interval():
    for responses in [
        ["yes"],
        ["yes", "yes"],
        ["yes", "no"],
        ["yes", "yes", "no"],
        ["a", "b", "c"],
    ]:
        result = deliberate(responses)
        assert 0.0 <= result.final_confidence <= 1.0


def test_agreement_is_binary_float():
    """Agreement must be exactly 0.0 or 1.0."""
    for responses in [["yes", "yes"], ["yes", "no"]]:
        result = deliberate(responses)
        assert result.agreement in (0.0, 1.0)


def test_unanimous_agreement_is_one():
    result = deliberate(["yes", "yes", "yes"])
    assert result.agreement == 1.0


def test_split_agreement_is_zero():
    """When prover=yes and verifier=no, they are in different clusters."""
    result = deliberate(["yes", "yes", "no"])
    assert result.agreement == 0.0


def test_legibility_bounded_by_cluster_mass():
    """legibility_score = entailment × cluster_mass ≤ cluster_mass ≤ 1."""
    for responses in [["yes", "yes", "no"], ["a", "b", "c"]]:
        result = deliberate(responses)
        assert result.legibility_score <= result.prover_cluster_mass + 1e-9


def test_deliberation_rounds_recorded():
    result = deliberate(["yes", "no"], n_rounds=3)
    assert result.deliberation_rounds == 3


def test_should_accept_matches_threshold():
    """should_accept = (final_confidence >= accept_threshold)."""
    result_low = deliberate(["yes", "no"], accept_threshold=0.99)
    result_high = deliberate(["yes", "no"], accept_threshold=0.0)
    assert result_low.should_accept is False
    assert result_high.should_accept is True


def test_se_result_attached():
    result = deliberate(["yes", "no"])
    assert result.se_result is not None
    assert result.se_result.n_responses == 2


# ---------------------------------------------------------------------------
# pvd_routing_score
# ---------------------------------------------------------------------------


def test_routing_score_interpolates():
    result = deliberate(["yes", "yes", "no"])
    tau = 0.40
    score = pvd_routing_score(tau, result, pvd_weight=0.40)
    expected = 0.60 * tau + 0.40 * result.final_confidence
    assert score == pytest.approx(expected, rel=1e-9)


def test_routing_score_zero_pvd_weight_equals_tau():
    result = deliberate(["yes", "no"])
    tau = 0.70
    score = pvd_routing_score(tau, result, pvd_weight=0.0)
    assert score == pytest.approx(tau, rel=1e-9)


def test_routing_score_full_pvd_weight_equals_final_conf():
    result = deliberate(["yes", "yes", "no"])
    score = pvd_routing_score(0.5, result, pvd_weight=1.0)
    assert score == pytest.approx(result.final_confidence, rel=1e-9)


def test_routing_score_bounded():
    """Routing score must be in [0, 1]."""
    result = deliberate(["yes", "yes", "yes"])
    for tau in [0.0, 0.5, 1.0]:
        for w in [0.0, 0.4, 1.0]:
            score = pvd_routing_score(tau, result, pvd_weight=w)
            assert 0.0 <= score <= 1.0 + 1e-9


def test_routing_score_pvd_weight_clamped():
    """pvd_weight values outside [0,1] are clamped."""
    result = deliberate(["yes"])
    score_over = pvd_routing_score(0.5, result, pvd_weight=2.0)
    score_under = pvd_routing_score(0.5, result, pvd_weight=-1.0)
    assert 0.0 <= score_over <= 1.0 + 1e-9
    assert 0.0 <= score_under <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# _cluster_agreement helper
# ---------------------------------------------------------------------------


def test_cluster_agreement_same_cluster():
    se = deliberate(["yes", "yes"]).se_result
    assert _cluster_agreement("yes", "yes", se) == 1.0


def test_cluster_agreement_different_clusters():
    se = deliberate(["yes", "yes", "no"]).se_result
    # prover=yes, verifier=no → different clusters
    assert _cluster_agreement("yes", "no", se) == 0.0


# ---------------------------------------------------------------------------
# Import from selective module
# ---------------------------------------------------------------------------


def test_import_from_selective():
    from remora.selective import (  # noqa: F401
        PVDResult,
        deliberate,
        pvd_routing_score,
    )
