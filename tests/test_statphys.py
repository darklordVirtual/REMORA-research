# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.statphys: Potts model, Gibbs distributions, and energy functions."""
from __future__ import annotations

import math

import pytest

from remora.statphys.energy import consensus_energy, minimum_energy_verdict, state_entropy
from remora.statphys.gibbs import free_energy_approx, gibbs_probability, partition_function_approx
from remora.statphys.potts import potts_critical_temperature_approx, potts_energy, potts_order_parameter


# ── Potts energy ───────────────────────────────────────────────────────────────

class TestPottsEnergy:
    def test_full_agreement_is_minimum_energy(self):
        counts = {"A": 3}
        e = potts_energy(counts, J=1.0)
        assert e < 0, "Full agreement should produce negative (minimum) energy"

    def test_full_disagreement_is_zero_energy(self):
        counts = {"A": 1, "B": 1, "C": 1}
        e = potts_energy(counts, J=1.0)
        assert e == 0.0, "All-different should give zero energy"

    def test_single_oracle_is_zero(self):
        assert potts_energy({"A": 1}) == 0.0

    def test_agreement_beats_partial(self):
        full = potts_energy({"A": 3}, J=1.0)
        partial = potts_energy({"A": 2, "B": 1}, J=1.0)
        assert full < partial, "Full agreement should have lower energy than partial"

    def test_coupling_scales_energy(self):
        counts = {"A": 3}
        e1 = potts_energy(counts, J=1.0)
        e2 = potts_energy(counts, J=2.0)
        assert abs(e2 / e1 - 2.0) < 1e-9, "Energy should scale linearly with J"


# ── Potts order parameter ──────────────────────────────────────────────────────

class TestPottsOrderParameter:
    def test_full_consensus_is_one(self):
        eta = potts_order_parameter({"A": 3}, k=3)
        assert abs(eta - 1.0) < 1e-9

    def test_uniform_is_zero(self):
        eta = potts_order_parameter({"A": 1, "B": 1, "C": 1}, k=3)
        assert abs(eta) < 1e-9

    def test_binary_consensus(self):
        eta = potts_order_parameter({"A": 3}, k=2)
        assert abs(eta - 1.0) < 1e-9

    def test_binary_split(self):
        eta = potts_order_parameter({"A": 1, "B": 1}, k=2)
        assert abs(eta) < 1e-9

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            potts_order_parameter({})

    def test_k_less_than_2_raises(self):
        with pytest.raises(ValueError):
            potts_order_parameter({"A": 3}, k=1)

    def test_default_k_uses_distinct_count(self):
        eta = potts_order_parameter({"A": 2, "B": 1})
        assert 0.0 <= eta <= 1.0


# ── Potts critical temperature ─────────────────────────────────────────────────

class TestPottsCriticalTemperature:
    def test_binary_tc(self):
        tc = potts_critical_temperature_approx(k=2, J=1.0)
        assert abs(tc - 0.5) < 1e-9

    def test_ternary_tc(self):
        tc = potts_critical_temperature_approx(k=3, J=1.0)
        assert abs(tc - 2.0 / 3.0) < 1e-9

    def test_k_less_than_2_raises(self):
        with pytest.raises(ValueError):
            potts_critical_temperature_approx(k=1)


# ── Gibbs partition function ───────────────────────────────────────────────────

class TestPartitionFunction:
    def test_single_state(self):
        Z = partition_function_approx([0.0], temperature=1.0)
        assert abs(Z - 1.0) < 1e-9

    def test_two_equal_energies(self):
        Z = partition_function_approx([0.0, 0.0], temperature=1.0)
        assert abs(Z - 2.0) < 1e-9

    def test_low_temperature_concentrates(self):
        Z_low = partition_function_approx([0.0, 10.0], temperature=0.01)
        assert abs(Z_low - 1.0) < 0.01, "Low T should concentrate on lowest energy"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            partition_function_approx([], temperature=1.0)

    def test_zero_temperature_raises(self):
        with pytest.raises(ValueError):
            partition_function_approx([1.0], temperature=0.0)


# ── Gibbs probability ─────────────────────────────────────────────────────────

class TestGibbsProbability:
    def test_single_state_gives_one(self):
        p = gibbs_probability(0.0, temperature=1.0, energies=[0.0])
        assert abs(p - 1.0) < 1e-9

    def test_equal_energies_give_uniform(self):
        p = gibbs_probability(0.0, temperature=1.0, energies=[0.0, 0.0, 0.0])
        assert abs(p - 1.0 / 3.0) < 1e-9

    def test_low_energy_dominates_at_low_temperature(self):
        p_low = gibbs_probability(0.0, temperature=0.01, energies=[0.0, 5.0, 10.0])
        assert p_low > 0.99, "Lowest energy state should dominate at low T"

    def test_probabilities_sum_to_one(self):
        energies = [0.5, 1.0, 2.0]
        T = 1.0
        total = sum(gibbs_probability(e, T, energies) for e in energies)
        assert abs(total - 1.0) < 1e-9


# ── Free energy ────────────────────────────────────────────────────────────────

class TestFreeEnergy:
    def test_single_zero_energy_state(self):
        F = free_energy_approx([0.0], temperature=1.0)
        assert abs(F) < 1e-9, "F = -T log(1) = 0"

    def test_two_zero_energy_states(self):
        F = free_energy_approx([0.0, 0.0], temperature=1.0)
        assert abs(F - (-math.log(2))) < 1e-9

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            free_energy_approx([], temperature=1.0)

    def test_zero_temperature_raises(self):
        with pytest.raises(ValueError):
            free_energy_approx([1.0], temperature=0.0)


# ── Consensus energy ──────────────────────────────────────────────────────────

class TestConsensusEnergy:
    def test_single_verdict_is_zero(self):
        e = consensus_energy({"A": 1.0})
        assert abs(e) < 1e-9

    def test_uniform_is_maximum(self):
        e_uniform = consensus_energy({"A": 1.0, "B": 1.0, "C": 1.0})
        e_partial = consensus_energy({"A": 2.0, "B": 1.0})
        assert e_uniform > e_partial

    def test_empty_is_zero(self):
        assert consensus_energy({}) == 0.0


# ── State entropy ──────────────────────────────────────────────────────────────

class TestStateEntropy:
    def test_deterministic_is_zero(self):
        assert state_entropy({"A": 1.0}) == 0.0

    def test_uniform_binary_is_ln2(self):
        H = state_entropy({"A": 1.0, "B": 1.0})
        assert abs(H - math.log(2)) < 1e-9

    def test_empty_is_zero(self):
        assert state_entropy({}) == 0.0


# ── Minimum energy verdict ────────────────────────────────────────────────────

class TestMinimumEnergyVerdict:
    def test_returns_highest_weight(self):
        assert minimum_energy_verdict({"A": 3.0, "B": 1.0}) == "A"

    def test_empty_returns_none(self):
        assert minimum_energy_verdict({}) is None
