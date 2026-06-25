"""Tests for remora.selective.binomial_bounds."""
from __future__ import annotations


from remora.selective.binomial_bounds import (
    binomial_tail_prob,
    clopper_pearson_upper,
    risk_upper_confidence_bound,
)


class TestBinomialTailProb:
    def test_k_zero_is_one(self):
        assert binomial_tail_prob(0, 10, 0.5) == 1.0

    def test_k_exceeds_n_is_zero(self):
        assert binomial_tail_prob(11, 10, 0.5) == 0.0

    def test_k_five_n_ten_known_value(self):
        # P(X >= 5) for Binomial(10, 0.5) ~ 0.6230
        result = binomial_tail_prob(5, 10, 0.5)
        assert abs(result - 0.6230) < 1e-3

    def test_k_ten_n_ten_known_value(self):
        # P(X >= 10) for Binomial(10, 0.5) = (0.5)^10 ~ 0.000977
        result = binomial_tail_prob(10, 10, 0.5)
        assert abs(result - (0.5 ** 10)) < 1e-8

    def test_p_zero_k_positive_is_zero(self):
        assert binomial_tail_prob(1, 10, 0.0) == 0.0

    def test_p_one_k_lte_n_is_one(self):
        assert binomial_tail_prob(5, 10, 1.0) == 1.0

    def test_k_zero_p_any_is_one(self):
        assert binomial_tail_prob(0, 10, 0.3) == 1.0


class TestClopperPearsonUpper:
    def test_zero_successes_upper_positive(self):
        upper = clopper_pearson_upper(0, 10)
        assert upper > 0.0

    def test_all_successes_upper_is_one(self):
        upper = clopper_pearson_upper(10, 10)
        assert upper == 1.0

    def test_half_successes_upper_above_half(self):
        upper = clopper_pearson_upper(5, 10)
        assert upper > 0.5

    def test_half_successes_upper_below_one(self):
        upper = clopper_pearson_upper(5, 10)
        assert upper < 1.0

    def test_upper_bound_contracts_with_larger_n(self):
        # With more data the interval tightens
        upper_small = clopper_pearson_upper(1, 10)
        upper_large = clopper_pearson_upper(1, 100)
        assert upper_large < upper_small

    def test_monotone_increasing_in_k(self):
        # More successes → higher upper bound
        n = 20
        uppers = [clopper_pearson_upper(k, n) for k in range(n + 1)]
        for i in range(1, len(uppers)):
            assert uppers[i] >= uppers[i - 1], (
                f"upper bound not non-decreasing at k={i}: {uppers[i-1]} -> {uppers[i]}"
            )


class TestRiskUpperConfidenceBound:
    def test_zero_accepted_returns_none(self):
        assert risk_upper_confidence_bound(0, 0) is None

    def test_upper_above_observed_rate(self):
        # observed rate = 1/10 = 0.1; upper should be > 0.1
        upper = risk_upper_confidence_bound(1, 10)
        assert upper is not None
        assert upper > 0.1

    def test_upper_below_one(self):
        upper = risk_upper_confidence_bound(1, 10)
        assert upper is not None
        assert upper < 1.0

    def test_zero_wrong_gives_positive_upper(self):
        # Even 0 errors — bound is still > 0 (can't rule out low error rate)
        upper = risk_upper_confidence_bound(0, 10)
        assert upper is not None
        assert upper > 0.0

    def test_all_wrong_upper_is_one(self):
        upper = risk_upper_confidence_bound(10, 10)
        assert upper == 1.0
