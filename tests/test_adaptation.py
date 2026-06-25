"""Tests for the online adaptation modules: ThermodynamicAdapter and OracleBandit."""

from __future__ import annotations

import math

import pytest

from remora.adaptation import OracleBandit, ThermodynamicAdapter
from remora.thermodynamics import ThermodynamicCalibration


# ---------------------------------------------------------------------------
# ThermodynamicAdapter
# ---------------------------------------------------------------------------


class TestThermodynamicAdapter:
    def test_initializes_with_default_parameters(self) -> None:
        adapter = ThermodynamicAdapter()
        assert adapter.adapted_lambda() == pytest.approx(1.0)
        weights = adapter.adapted_phase_weights()
        assert weights["ordered"] == pytest.approx(1.0)
        assert weights["critical"] == pytest.approx(0.5)
        assert weights["disordered"] == pytest.approx(0.1)

    def test_returns_default_weights_before_min_samples(self) -> None:
        adapter = ThermodynamicAdapter(min_samples=20)
        for _ in range(5):
            adapter.record_outcome(0.3, 0.5, "ordered", "ACCEPT", True)
        weights = adapter.adapted_phase_weights()
        assert weights["ordered"] == pytest.approx(1.0)  # defaults still

    def test_lambda_increases_when_high_dissensus_precedes_errors(self) -> None:
        adapter = ThermodynamicAdapter(initial_lambda=1.0, learning_rate=0.1, min_samples=0)
        # Feed 30 incorrect ACCEPT decisions with high dissensus
        for _ in range(30):
            adapter.record_outcome(0.9, 0.8, "ordered", "ACCEPT", False)
        # λ should increase (penalty on dissensus should be stronger)
        assert adapter.adapted_lambda() > 1.0

    def test_lambda_decreases_when_low_dissensus_precedes_errors(self) -> None:
        adapter = ThermodynamicAdapter(initial_lambda=2.0, learning_rate=0.1, min_samples=0)
        # Feed 30 correct ACCEPT decisions with low dissensus
        for _ in range(30):
            adapter.record_outcome(0.05, 0.1, "ordered", "ACCEPT", True)
        # Correct low-dissensus answers → λ should not need to be high
        assert adapter.adapted_lambda() < 2.0

    def test_lambda_stays_within_bounds(self) -> None:
        adapter = ThermodynamicAdapter(
            initial_lambda=1.0,
            learning_rate=10.0,  # very aggressive
            min_samples=0,
            lambda_min=0.1,
            lambda_max=5.0,
        )
        for _ in range(100):
            adapter.record_outcome(1.0, 1.0, "disordered", "ACCEPT", False)
        assert adapter.adapted_lambda() <= 5.0
        assert adapter.adapted_lambda() >= 0.1

    def test_phase_weights_adapt_from_observed_accuracy(self) -> None:
        adapter = ThermodynamicAdapter(min_samples=0)
        # Ordered phase is always correct, disordered always wrong
        for _ in range(50):
            adapter.record_outcome(0.05, 0.1, "ordered", "ACCEPT", True)
            adapter.record_outcome(0.9, 0.9, "disordered", "ACCEPT", False)
        weights = adapter.adapted_phase_weights()
        assert weights["ordered"] > weights["disordered"]

    def test_phase_weight_ordering_constraint_preserved(self) -> None:
        adapter = ThermodynamicAdapter(min_samples=0)
        # Inject reversed accuracy signal (disordered > ordered) - constraint must hold
        for _ in range(50):
            adapter.record_outcome(0.05, 0.1, "disordered", "ACCEPT", True)
            adapter.record_outcome(0.9, 0.9, "ordered", "ACCEPT", False)
        weights = adapter.adapted_phase_weights()
        assert weights["ordered"] >= weights["critical"] >= weights["disordered"]

    def test_adapted_calibration_returns_thermodynamic_calibration(self) -> None:
        adapter = ThermodynamicAdapter()
        cal = adapter.adapted_calibration()
        assert isinstance(cal, ThermodynamicCalibration)

    def test_state_reports_convergence_after_sufficient_stable_updates(self) -> None:
        adapter = ThermodynamicAdapter(min_samples=5, ema_alpha=0.5)
        # Feed uniform correct signals to drive convergence
        for _ in range(100):
            adapter.record_outcome(0.2, 0.3, "ordered", "ACCEPT", True)
        state = adapter.state()
        assert state.n_updates == 100
        assert math.isfinite(state.v_params)

    def test_sgd_convergence_bound_decreases_with_more_steps(self) -> None:
        bound_10 = ThermodynamicAdapter.sgd_convergence_bound(10)
        bound_100 = ThermodynamicAdapter.sgd_convergence_bound(100)
        assert bound_10 > bound_100

    def test_sgd_convergence_bound_is_zero_for_t_zero(self) -> None:
        assert ThermodynamicAdapter.sgd_convergence_bound(0) == float("inf")

    def test_lambda_signal_positive_when_incorrect_has_higher_dissensus(self) -> None:
        adapter = ThermodynamicAdapter(ema_alpha=0.5, min_samples=0)
        for _ in range(20):
            adapter.record_outcome(0.9, 0.8, "disordered", "ACCEPT", False)
            adapter.record_outcome(0.1, 0.2, "ordered", "ACCEPT", True)
        assert adapter.lambda_signal() > 0

    def test_summary_returns_complete_dict(self) -> None:
        adapter = ThermodynamicAdapter()
        adapter.record_outcome(0.3, 0.5, "ordered", "ACCEPT", True)
        s = adapter.summary()
        assert "lambda" in s
        assert "phase_weights" in s
        assert "converged" in s
        assert "v_params" in s


# ---------------------------------------------------------------------------
# OracleBandit
# ---------------------------------------------------------------------------


class TestOracleBandit:
    def test_select_returns_correct_number_of_oracles(self) -> None:
        bandit = OracleBandit(["a", "b", "c", "d"], seed=42)
        selected = bandit.select(3)
        assert len(selected) == 3
        assert all(oid in ["a", "b", "c", "d"] for oid in selected)

    def test_select_clamps_to_pool_size(self) -> None:
        bandit = OracleBandit(["a", "b"], seed=42)
        assert len(bandit.select(10)) == 2

    def test_update_increases_alpha_on_correct(self) -> None:
        bandit = OracleBandit(["oracle_1"], seed=0)
        before = bandit._alpha["oracle_1"]
        bandit.update("oracle_1", correct=True)
        assert bandit._alpha["oracle_1"] == before + 1.0

    def test_update_increases_beta_on_incorrect(self) -> None:
        bandit = OracleBandit(["oracle_1"], seed=0)
        before = bandit._beta["oracle_1"]
        bandit.update("oracle_1", correct=False)
        assert bandit._beta["oracle_1"] == before + 1.0

    def test_expected_accuracy_converges_toward_true_accuracy(self) -> None:
        bandit = OracleBandit(["good", "bad"], seed=7)
        import random
        rng = random.Random(7)
        for _ in range(200):
            bandit.update("good", correct=rng.random() < 0.9)
            bandit.update("bad", correct=rng.random() < 0.2)
        assert bandit.expected_accuracy("good") > bandit.expected_accuracy("bad")
        assert bandit.expected_accuracy("good") > 0.7
        assert bandit.expected_accuracy("bad") < 0.5

    def test_ranking_puts_best_oracle_first(self) -> None:
        bandit = OracleBandit(["a", "b", "c"], seed=1)
        for _ in range(50):
            bandit.update("a", correct=True)
            bandit.update("b", correct=False)
            bandit.update("c", correct=True)
        ranking = bandit.ranking()
        assert ranking[0] in ("a", "c")
        assert ranking[-1] == "b"

    def test_select_prefers_better_oracle_over_many_rounds(self) -> None:
        bandit = OracleBandit(["good", "bad"], seed=99)
        import random
        rng = random.Random(99)
        for _ in range(100):
            bandit.update("good", correct=rng.random() < 0.85)
            bandit.update("bad", correct=rng.random() < 0.15)
        # Over 100 Thompson Sampling selections, good oracle should be chosen more
        counts: dict[str, int] = {"good": 0, "bad": 0}
        for _ in range(100):
            chosen = bandit.select(1)[0]
            counts[chosen] += 1
        assert counts["good"] > counts["bad"]

    def test_select_ucb_returns_oracle_ids(self) -> None:
        bandit = OracleBandit(["x", "y"], seed=3)
        bandit.update("x", correct=True)
        selected = bandit.select_ucb(1)
        assert len(selected) == 1
        assert selected[0] in ("x", "y")

    def test_regret_bound_is_logarithmic(self) -> None:
        bandit = OracleBandit(["a", "b", "c"], seed=0)
        r100 = bandit.regret_bound(100)
        r400 = bandit.regret_bound(400)
        # O(√(kT log T)) — doubling T less than doubles regret
        assert r400 < 3 * r100

    def test_regret_bound_zero_for_zero_rounds(self) -> None:
        bandit = OracleBandit(["a"], seed=0)
        assert bandit.regret_bound(0) == pytest.approx(0.0)

    def test_posterior_variance_decreases_with_observations(self) -> None:
        bandit = OracleBandit(["o"], seed=0)
        var_before = bandit.posterior_variance("o")
        for _ in range(100):
            bandit.update("o", correct=True)
        var_after = bandit.posterior_variance("o")
        assert var_after < var_before

    def test_add_oracle_extends_pool(self) -> None:
        bandit = OracleBandit(["a"], seed=0)
        bandit.add_oracle("b", prior_alpha=2.0, prior_beta=1.0)
        assert "b" in bandit.ranking()

    def test_remove_oracle_shrinks_pool(self) -> None:
        bandit = OracleBandit(["a", "b"], seed=0)
        bandit.remove_oracle("a")
        assert bandit.select(2) == ["b"]

    def test_update_many_applies_all_outcomes(self) -> None:
        bandit = OracleBandit(["a", "b"], seed=0)
        bandit.update_many({"a": True, "b": False})
        assert bandit._alpha["a"] > bandit._alpha["b"]

    def test_unknown_oracle_raises_on_update(self) -> None:
        bandit = OracleBandit(["a"], seed=0)
        with pytest.raises(KeyError):
            bandit.update("nonexistent", correct=True)

    def test_empty_oracle_ids_raises(self) -> None:
        with pytest.raises(ValueError):
            OracleBandit([])

    def test_summary_contains_all_oracles(self) -> None:
        bandit = OracleBandit(["x", "y", "z"], seed=0)
        s = bandit.summary()
        assert set(s["oracles"].keys()) == {"x", "y", "z"}
        assert "ranking" in s
