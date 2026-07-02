"""Tests for the hallucination bound theorem and its numerical verification."""
from __future__ import annotations

import pathlib

import pytest

from remora.proofs.hallucination_bound_theorem import bound, verify_on_benchmark


class TestBoundFormula:
    def test_monotone_in_epsilon(self) -> None:
        """Bound rises as individual error rate increases."""
        rho, n = 0.2, 3
        prev = 0.0
        for eps in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
            b = bound(n, eps, rho)
            assert b >= prev, f"bound not monotone at eps={eps}"
            prev = b

    def test_monotone_in_rho(self) -> None:
        """Bound rises as pairwise correlation increases."""
        eps, n = 0.20, 3
        prev = 0.0
        for rho in [0.0, 0.1, 0.2, 0.3, 0.4, 0.49, 0.6]:
            b = bound(n, eps, rho)
            assert b >= prev, f"bound not monotone at rho={rho}"
            prev = b

    def test_degenerate_eps_above_half(self) -> None:
        assert bound(3, 0.50, 0.0) == 1.0
        assert bound(3, 0.99, 0.2) == 1.0

    def test_degenerate_n_lt_2(self) -> None:
        assert bound(1, 0.1, 0.0) == 1.0

    def test_zero_correlation_matches_iid_pairs(self) -> None:
        """At rho=0 bound equals eps^(2*floor(n/2)) — the proven pair exponent.

        (q = eps^2 at rho=0, and B = q^floor(n/2).) A prior version asserted
        eps^n, matching the retracted n/2-exponent claim.
        """
        eps, n = 0.2, 3
        b = bound(n, eps, 0.0)
        assert abs(b - (eps * eps) ** (n // 2)) < 1e-9

    def test_no_049_clamp_bound_stays_honest_above_half_rho(self) -> None:
        """The theorem function must NOT clamp rho at 0.49 (the runtime proxy
        does; the verification function reports honest values)."""
        assert bound(3, 0.2, 0.5) > bound(3, 0.2, 0.49)
        assert bound(3, 0.2, 0.6) > bound(3, 0.2, 0.5)
        assert bound(3, 0.2, 1.0) < 1.0  # q < eps < 0.5 keeps it informative

    def test_proven_exponent_is_floor_n_over_2(self) -> None:
        """B uses floor(n/2), not n/2: at n=3 the proven bound is q^1."""
        eps, rho = 0.264, 0.236
        q = eps * eps + rho * eps * (1 - eps)
        assert abs(bound(3, eps, rho) - q) < 1e-12
        assert abs(bound(4, eps, rho) - q ** 2) < 1e-12
        assert bound(3, eps, rho) > q ** 1.5  # the retracted claim was tighter

    def test_bound_is_always_in_unit_interval(self) -> None:
        for eps in [0.01, 0.1, 0.3, 0.49]:
            for rho in [0.0, 0.2, 0.49]:
                for n in [2, 3, 5, 10]:
                    b = bound(n, eps, rho)
                    assert 0.0 <= b <= 1.0


class TestNumericalVerification:
    @pytest.fixture(scope="class")
    def result(self) -> dict:
        if not pathlib.Path("results/ablation_v2_canonical_results.json").exists():
            pytest.skip("canonical artifact missing")
        return verify_on_benchmark(rho_bar=0.236, n_oracles=3)

    def test_theorem_holds(self, result: dict) -> None:
        assert result["theorem_status"] == "HOLDS", (
            f"Theorem violated: B={result['theoretical_bound_B']} "
            f"but model={result['p_all_wrong_independence_model']}"
        )

    def test_bound_exceeds_independence_model(self, result: dict) -> None:
        assert result["theoretical_bound_B"] >= result["p_all_wrong_independence_model"]
        assert result["bound_slack_vs_model"] > 0

    def test_bound_exceeds_practical_estimate(self, result: dict) -> None:
        assert result["theoretical_bound_B"] >= result["p_all_wrong_practical_conditional_est"]

    def test_implied_epsilon_range(self, result: dict) -> None:
        eps = result["eps_implied_from_majority_pool"]
        assert 0.0 < eps < 0.5, f"Implied epsilon {eps} out of valid range"

    def test_bound_not_vacuous(self, result: dict) -> None:
        # Bound should be informative: strictly less than 1 and less than
        # the majority error rate.
        assert result["theoretical_bound_B"] < 1.0
        assert result["theoretical_bound_B"] < result["p_majority_wrong_observed"]
