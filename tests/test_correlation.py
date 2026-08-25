# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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
    assert cm.rho_observed("a", "b") == 0.0


def test_observe_increments_samples():
    cm = CorrelationMatrix()
    verdicts = _make_verdicts([("a", True), ("b", True)])
    cm.observe(verdicts)
    assert cm.n_samples() == 1


def test_perfect_agreement_stays_one():
    """The upper bound of five-for-five agreement is 1.0, and stays there.

    #370 named this case too, but a one-sided bound can only correct one end
    and this is the end where uncorrected is already conservative: pulling it
    down would need the lower bound, which understates correlation.
    """
    cm = CorrelationMatrix(window_size=10)
    for _ in range(5):
        verdicts = _make_verdicts([("a", True), ("b", True)])
        cm.observe(verdicts)
    assert cm.rho("a", "b") == 1.0
    assert cm.rho_observed("a", "b") == 1.0


def test_perfect_disagreement_is_not_reported_as_zero_correlation():
    """Five disagreements are not proof of independence (#370).

    The raw rate said 0.0, which claims the pair is perfectly diverse on the
    strength of five rounds. The Wilson upper bound keeps a substantial
    residual, and the estimator the engine reads is the bound.
    """
    cm = CorrelationMatrix(window_size=10)
    for i in range(5):
        verdicts = _make_verdicts([("a", True if i%2==0 else False),
                                   ("b", False if i%2==0 else True)])
        cm.observe(verdicts)
    assert cm.rho_observed("a", "b") == 0.0
    assert 0.30 < cm.rho("a", "b") < 0.50


def test_the_bound_tightens_towards_the_observed_rate_as_n_grows():
    """The correction is a small-sample correction, not a permanent penalty."""
    small = CorrelationMatrix._wilson_upper(0, 5)
    large = CorrelationMatrix._wilson_upper(0, 400)
    assert small > large
    assert large < 0.01


def test_an_unobserved_pair_stays_neutral():
    """n=0 is absence of data, not a small sample of it.

    The mathematically correct upper bound at n=0 is 1.0. That is refused
    deliberately: it would declare every provider maximally redundant with
    every other before the swarm has answered a round. See _wilson_upper.
    """
    assert CorrelationMatrix._wilson_upper(0, 0) == 0.0


def test_rho_is_never_below_the_rate_it_bounds():
    """Property: the estimator fed to gates can never flatter the raw count."""
    for n in range(1, 60):
        for k in range(n + 1):
            assert CorrelationMatrix._wilson_upper(k, n) >= k / n - 1e-12


def test_rho_stays_inside_the_unit_interval():
    for n in range(1, 60):
        for k in range(n + 1):
            assert 0.0 <= CorrelationMatrix._wilson_upper(k, n) <= 1.0


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
