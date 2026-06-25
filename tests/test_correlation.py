# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.correlation — ρ matrix and diversity weights."""
from remora.canonical import phi
from remora.correlation import CorrelationMatrix, weighted_consensus


def _make_verdicts(answers: list[tuple[str, bool | None]]):
    return [(name, phi({"answer": a, "claim": "test claim"})) for name, a in answers]


def test_rho_self_is_one():
    cm = CorrelationMatrix()
    assert cm.rho("a", "a") == 1.0


def test_rho_no_data_is_zero():
    cm = CorrelationMatrix()
    assert cm.rho("a", "b") == 0.0


def test_observe_increments_samples():
    cm = CorrelationMatrix()
    verdicts = _make_verdicts([("a", True), ("b", True)])
    cm.observe(verdicts)
    assert cm.n_samples() == 1


def test_perfect_agreement_rho_one():
    cm = CorrelationMatrix(window_size=10)
    for _ in range(5):
        verdicts = _make_verdicts([("a", True), ("b", True)])
        cm.observe(verdicts)
    assert cm.rho("a", "b") == 1.0


def test_perfect_disagreement_rho_zero():
    cm = CorrelationMatrix(window_size=10)
    for i in range(5):
        verdicts = _make_verdicts([("a", True if i%2==0 else False),
                                   ("b", False if i%2==0 else True)])
        cm.observe(verdicts)
    assert cm.rho("a", "b") == 0.0


def test_diversity_weights_sum_to_one():
    cm = CorrelationMatrix()
    providers = ["a", "b", "c"]
    weights = cm.diversity_weights(providers)
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_independent_oracle_gets_higher_weight():
    cm = CorrelationMatrix(window_size=50)
    # a and b always agree; c always disagrees with both
    for _ in range(20):
        verdicts = _make_verdicts([("a", True), ("b", True), ("c", False)])
        cm.observe(verdicts)
    weights = cm.diversity_weights(["a", "b", "c"])
    assert weights["c"] > weights["a"]
    assert weights["c"] > weights["b"]


def test_weighted_consensus_returns_majority():
    cm = CorrelationMatrix()
    verdicts = _make_verdicts([("a", True), ("b", True), ("c", False)])
    consensus = weighted_consensus(verdicts, cm)
    assert consensus.winning_verdict is not None
    assert consensus.winning_verdict.polarity is True


def test_weighted_consensus_empty():
    cm = CorrelationMatrix()
    consensus = weighted_consensus([], cm)
    assert consensus.winning_fingerprint == ""
