"""Numerical validation of Theorem 1 (Joint Convergence) and MaxEnt grounding."""

from __future__ import annotations

import math

import pytest

from remora.theory import (
    JointConvergenceTheorem,
    MaxEntropyGrounding,
    ScalingAnalysis,
)


# ---------------------------------------------------------------------------
# JointConvergenceTheorem
# ---------------------------------------------------------------------------


class TestJointConvergenceTheorem:
    def test_rejects_mu_star_at_or_below_half(self) -> None:
        with pytest.raises(ValueError):
            JointConvergenceTheorem(k=3, mu_star=0.5)
        with pytest.raises(ValueError):
            JointConvergenceTheorem(k=3, mu_star=0.3)

    def test_rejects_zero_oracles(self) -> None:
        with pytest.raises(ValueError):
            JointConvergenceTheorem(k=0, mu_star=0.85)

    def test_sigma_sq_bernoulli_properties(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        assert thm.sigma_sq(0.5) == pytest.approx(0.25)          # maximum
        assert thm.sigma_sq(0.0) == pytest.approx(0.0)
        assert thm.sigma_sq(1.0) == pytest.approx(0.0)
        assert thm.sigma_sq(0.85) < 0.25                         # strictly less than random

    def test_oracle_quality_converges_to_mu_star(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        q_early = thm.oracle_quality_at(10)
        q_late = thm.oracle_quality_at(100_000)
        assert q_late > q_early                          # improving
        assert q_late == pytest.approx(0.85, abs=0.05)  # near μ*

    def test_oracle_quality_never_below_half(self) -> None:
        thm = JointConvergenceTheorem(k=10, mu_star=0.55)
        for t in [1, 2, 5, 10]:
            assert thm.oracle_quality_at(t) >= 0.5

    def test_sigma_sq_avg_decreases_toward_sigma_sq_star(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        avg_10 = thm.sigma_sq_avg(10)
        avg_1000 = thm.sigma_sq_avg(1000)
        sigma_star = thm.sigma_sq(0.85)
        assert avg_10 > avg_1000                    # converging
        assert avg_1000 >= sigma_star               # lower bounded by σ²(μ*)
        assert avg_10 <= 0.25                       # upper bounded by random selection

    def test_adapter_regret_zero_at_t_zero(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        assert thm.adapter_regret_bound(0) == pytest.approx(0.0)

    def test_adapter_regret_grows_sublinearly(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        r100 = thm.adapter_regret_bound(100)
        r400 = thm.adapter_regret_bound(400)
        # Sublinear: r(4T) < 4·r(T)  (grows as √T)
        assert r400 < 4.0 * r100

    def test_bandit_regret_zero_at_t_zero(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        assert thm.bandit_regret_bound(0) == pytest.approx(0.0)

    def test_bandit_regret_grows_sublinearly(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        r100 = thm.bandit_regret_bound(100)
        r400 = thm.bandit_regret_bound(400)
        assert r400 < 4.0 * r100

    def test_coupled_strictly_less_than_decoupled(self) -> None:
        """Key theorem claim: coupled < decoupled for μ* > 0.5."""
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        for t in [50, 500, 5000]:
            assert thm.adapter_regret_bound(t) < thm.decoupled_regret_bound(t)

    def test_coupling_improvement_positive(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        result = thm.evaluate(1000)
        assert result.coupling_improvement > 0.0
        assert result.coupling_improvement_pct > 0.0

    def test_coupling_improvement_scales_with_mu_star(self) -> None:
        """Higher μ* → larger coupling improvement."""
        t = 1000
        imp_70 = JointConvergenceTheorem(k=3, mu_star=0.70).evaluate(t).coupling_improvement
        imp_85 = JointConvergenceTheorem(k=3, mu_star=0.85).evaluate(t).coupling_improvement
        imp_90 = JointConvergenceTheorem(k=3, mu_star=0.90).evaluate(t).coupling_improvement
        assert imp_90 > imp_85 > imp_70

    def test_asymptotic_coupling_factor_range(self) -> None:
        """κ ∈ (0, 1) for μ* ∈ (0.5, 1)."""
        for mu in [0.55, 0.70, 0.85, 0.90, 0.99]:
            kappa = JointConvergenceTheorem.asymptotic_coupling_factor(mu)
            assert 0.0 < kappa < 1.0

    def test_asymptotic_coupling_factor_known_values(self) -> None:
        """κ(0.85) = 4·0.85·0.15 = 0.51  (49 % variance reduction)."""
        assert JointConvergenceTheorem.asymptotic_coupling_factor(0.85) == pytest.approx(0.51, abs=1e-10)
        assert JointConvergenceTheorem.asymptotic_coupling_factor(0.90) == pytest.approx(0.36, abs=1e-10)

    def test_rounds_to_epsilon_decreases_with_better_oracle(self) -> None:
        """Better μ* → fewer rounds needed for same ε."""
        t_70 = JointConvergenceTheorem.rounds_to_epsilon(0.05, k=3, mu_star=0.70)
        t_85 = JointConvergenceTheorem.rounds_to_epsilon(0.05, k=3, mu_star=0.85)
        assert t_85 < t_70

    def test_rounds_to_epsilon_increases_with_stricter_requirement(self) -> None:
        t_10pct = JointConvergenceTheorem.rounds_to_epsilon(0.10, k=3, mu_star=0.85)
        t_5pct = JointConvergenceTheorem.rounds_to_epsilon(0.05, k=3, mu_star=0.85)
        assert t_5pct > t_10pct

    def test_average_regret_decreases_over_time(self) -> None:
        """E[R_T]/T → 0: the system converges."""
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        avg_100 = (thm.adapter_regret_bound(100) + thm.bandit_regret_bound(100)) / 100
        avg_10000 = (thm.adapter_regret_bound(10000) + thm.bandit_regret_bound(10000)) / 10000
        assert avg_10000 < avg_100

    def test_evaluate_returns_consistent_fields(self) -> None:
        thm = JointConvergenceTheorem(k=3, mu_star=0.85)
        r = thm.evaluate(500)
        assert r.joint_regret_bound == pytest.approx(r.adapter_regret_bound + r.bandit_regret_bound)
        assert r.coupling_improvement == pytest.approx(r.decoupled_regret_bound - r.joint_regret_bound)
        assert 0.0 < r.sigma_sq_optimal < r.sigma_sq_random == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# MaxEntropyGrounding
# ---------------------------------------------------------------------------


class TestMaxEntropyGrounding:
    def test_gibbs_distribution_sums_to_one(self) -> None:
        grounding = MaxEntropyGrounding(lambda_=1.5)
        votes = [10, 5, 2, 1]
        p = grounding.gibbs_distribution(votes)
        assert sum(p) == pytest.approx(1.0)
        assert all(pj > 0 for pj in p)

    def test_gibbs_peaks_on_plurality_answer(self) -> None:
        grounding = MaxEntropyGrounding(lambda_=2.0)
        p = grounding.gibbs_distribution([8, 2, 1])
        assert p[0] == max(p)

    def test_free_energy_formula_matches_neg_log_z(self) -> None:
        """Core theorem: F = λD − H = −log Z (up to floating-point noise)."""
        grounding = MaxEntropyGrounding(lambda_=1.0)
        for votes in [[5, 3, 2], [9, 1], [4, 4, 4, 4]]:
            result = grounding.verify_free_energy_formula(votes)
            assert result["formula_verified"], f"Verification failed for votes={votes}"
            assert result["absolute_error"] < 1e-9

    def test_gibbs_minimises_free_energy(self) -> None:
        """Gibbs distribution should have lower F than any random distribution."""
        grounding = MaxEntropyGrounding(lambda_=1.5)
        result = grounding.verify_gibbs_minimises_free_energy([7, 3, 1], n_random=2000, seed=42)
        assert result["gibbs_is_minimum"], (
            f"Gibbs free energy {result['f_gibbs']:.4f} not minimal; "
            f"found lower {result['f_random_min']:.4f}"
        )

    def test_lyapunov_free_energy_identity(self) -> None:
        """V = H + λD = F(T=−1) using Herfindahl dissensus."""
        grounding = MaxEntropyGrounding(lambda_=1.0)
        result = grounding.lyapunov_free_energy_identity([6, 3, 1])
        assert result["identity_holds"], (
            f"V={result['V_lyapunov']:.6f} ≠ F(T=-1)={result['F_at_T_neg1']:.6f}"
        )

    def test_entropy_uniform_is_maximum(self) -> None:
        n = 4
        h_uniform = MaxEntropyGrounding.entropy([1.0 / n] * n)
        h_skewed = MaxEntropyGrounding.entropy([0.7, 0.1, 0.1, 0.1])
        assert h_uniform > h_skewed

    def test_dissensus_zero_for_consensus(self) -> None:
        """All oracles agree → D = 0."""
        p = [1.0, 0.0, 0.0]
        assert MaxEntropyGrounding.dissensus(p) == pytest.approx(0.0)

    def test_dissensus_maximum_for_uniform(self) -> None:
        """Uniform distribution → D = 1 − 1/k."""
        k = 4
        p = [1.0 / k] * k
        assert MaxEntropyGrounding.dissensus(p) == pytest.approx(1.0 - 1.0 / k)

    def test_critical_temperature_formula(self) -> None:
        T_c = MaxEntropyGrounding.critical_temperature(lambda_=1.0, mean_consensus=0.5, k=3)
        assert T_c == pytest.approx(0.5 / math.log(3))

    def test_potts_order_parameter_range(self) -> None:
        assert MaxEntropyGrounding.potts_order_parameter([1.0, 0.0, 0.0]) == pytest.approx(1.0)
        k = 3
        assert MaxEntropyGrounding.potts_order_parameter([1 / k] * k) == pytest.approx(0.0)

    def test_lambda_controls_concentration(self) -> None:
        """Higher λ → more peaked Gibbs distribution → lower dissensus."""
        votes = [6, 3, 1]
        low = MaxEntropyGrounding(lambda_=0.5)
        high = MaxEntropyGrounding(lambda_=5.0)
        p_low = low.gibbs_distribution(votes)
        p_high = high.gibbs_distribution(votes)
        assert MaxEntropyGrounding.dissensus(p_high) < MaxEntropyGrounding.dissensus(p_low)


# ---------------------------------------------------------------------------
# ScalingAnalysis
# ---------------------------------------------------------------------------


class TestScalingAnalysis:
    def test_optimal_learning_rate_decreases_with_t(self) -> None:
        sa = ScalingAnalysis(mu_star=0.85)
        assert sa.optimal_learning_rate(100) > sa.optimal_learning_rate(10000)

    def test_optimal_oracle_count_decreases_with_t(self) -> None:
        # k* = (D₀·G·σ/C_ts)² / log T — decreases as log T grows.
        # At large T, bandit converges well with fewer oracles.
        sa = ScalingAnalysis(mu_star=0.85)
        k_100 = sa.optimal_oracle_count(100)
        k_10000 = sa.optimal_oracle_count(10000)
        assert k_10000 < k_100

    def test_average_regret_decreases_with_t(self) -> None:
        sa = ScalingAnalysis(mu_star=0.85)
        avg_100 = sa.average_regret(100, k=3)
        avg_10000 = sa.average_regret(10000, k=3)
        assert avg_10000 < avg_100

    def test_coupling_benefit_table_all_mu_above_half(self) -> None:
        table = ScalingAnalysis.coupling_benefit_table([0.55, 0.70, 0.85, 0.90])
        assert len(table) == 4
        for row in table:
            assert row["variance_reduction_pct"] > 0.0
            assert 0.0 < row["asymptotic_coupling_factor_kappa"] < 1.0

    def test_coupling_benefit_improves_with_mu_star(self) -> None:
        table = ScalingAnalysis.coupling_benefit_table([0.55, 0.70, 0.85, 0.90])
        reductions = [r["variance_reduction_pct"] for r in table]
        assert reductions == sorted(reductions)  # monotonically increasing

    def test_regret_table_structure(self) -> None:
        sa = ScalingAnalysis(mu_star=0.85)
        table = sa.regret_table([100, 1000], [2, 3])
        assert len(table) == 4
        for row in table:
            # Values are pre-rounded to 4 decimal places; allow 0.001 tolerance
            assert row["joint_regret"] == pytest.approx(
                row["adapter_regret"] + row["bandit_regret"], abs=1e-3
            )

    def test_rounds_to_epsilon_table_structure(self) -> None:
        sa = ScalingAnalysis(mu_star=0.85)
        table = sa.rounds_to_epsilon_table([0.1, 0.05], [2, 3])
        assert len(table) == 4
        for row in table:
            assert row["T_required"] >= 1
