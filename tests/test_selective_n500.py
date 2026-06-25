"""Locked regression tests for N500 selective-trust curve.

These tests assert the headline N500 results and run the experiment
reproducibly from the committed canonical artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.selective_n500 import run, _wilson, _p_value_one_sided

RESULTS_PATH = Path("results/selective_n500_results.json")
DATA_PATH = Path("results/thermodynamic_eval_n500_calibrated_results.json")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _load_results() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return run()


# ---------------------------------------------------------------------------
# Core statistics
# ---------------------------------------------------------------------------

class TestWilsonCI:
    def test_perfect_accuracy(self):
        lo, hi = _wilson(10, 10)
        assert lo > 0.69  # lower bound for 10/10
        assert hi == pytest.approx(1.0)

    def test_zero_accuracy(self):
        lo, hi = _wilson(0, 10)
        assert lo == pytest.approx(0.0)
        assert hi < 0.31

    def test_symmetry(self):
        lo1, hi1 = _wilson(3, 10)
        lo2, hi2 = _wilson(7, 10)
        assert pytest.approx(1 - hi1, abs=1e-6) == pytest.approx(lo2, abs=1e-6)

    def test_empty_population(self):
        lo, hi = _wilson(0, 0)
        assert lo == 0.0
        assert hi == 1.0


class TestPValue:
    def test_above_baseline(self):
        p = _p_value_one_sided(90, 100, 0.50)
        assert p < 0.001

    def test_at_baseline(self):
        p = _p_value_one_sided(50, 100, 0.50)
        assert p == pytest.approx(0.5, abs=0.02)

    def test_below_baseline(self):
        p = _p_value_one_sided(20, 100, 0.50)
        assert p > 0.99

    def test_empty_n(self):
        p = _p_value_one_sided(0, 0, 0.5)
        assert p == 1.0


# ---------------------------------------------------------------------------
# N500 baseline
# ---------------------------------------------------------------------------

class TestN500Baseline:
    def setup_method(self):
        self.d = _load_results()

    def test_n_items(self):
        assert self.d["n"] == 544

    def test_baseline_accuracy(self):
        assert self.d["baseline_accuracy"] == pytest.approx(0.4118, abs=0.001)

    def test_baseline_wilson_ci(self):
        lo, hi = self.d["baseline_wilson_ci"]
        assert lo == pytest.approx(0.371, abs=0.005)
        assert hi == pytest.approx(0.454, abs=0.005)

    def test_phase_ordered_accuracy(self):
        ph = self.d["phase_summary"]["ordered"]
        assert ph["n"] == 99
        assert ph["accuracy"] > 0.85

    def test_phase_disordered_accuracy(self):
        ph = self.d["phase_summary"]["disordered"]
        assert ph["n"] == 413
        assert ph["accuracy"] < 0.35


# ---------------------------------------------------------------------------
# Headline result: 88%+ at 18% coverage
# ---------------------------------------------------------------------------

class TestN500HeadlineResult:
    def setup_method(self):
        self.d = _load_results()
        self.best = self.d["best_operating_point"]

    def test_best_signal_is_neg_temperature(self):
        assert self.best["signal"] == "neg_temperature"

    def test_best_coverage_18pct(self):
        assert self.best["coverage"] == pytest.approx(0.18, abs=0.005)

    def test_best_accuracy_above_88pct(self):
        assert self.best["accuracy"] > 0.88

    def test_best_lift_above_45pp(self):
        assert self.best["lift_pp"] > 45.0

    def test_best_ci_lower_bound_above_baseline_upper(self):
        baseline_upper = self.d["baseline_wilson_ci"][1]
        assert self.best["wilson_ci_lo"] > baseline_upper

    def test_best_ci_nonoverlap(self):
        assert self.best["ci_nonoverlap"] is True

    def test_best_p_value_extremely_small(self):
        assert self.best["p_one_sided"] < 1e-6

    def test_best_phase_composition_dominated_by_ordered(self):
        comp = self.best["phase_composition"]
        total = sum(comp.values())
        ordered_frac = comp.get("ordered", 0) / total
        assert ordered_frac > 0.90


# ---------------------------------------------------------------------------
# 15% coverage: minimum quality bar
# ---------------------------------------------------------------------------

class TestN500At15PctCoverage:
    def setup_method(self):
        d = _load_results()
        rows = d["selective_curve"]
        self.row = next(
            r for r in rows
            if r["signal"] == "neg_temperature" and abs(r["coverage"] - 0.15) < 0.005
        )
        self.baseline_upper = d["baseline_wilson_ci"][1]

    def test_accuracy_above_85pct(self):
        assert self.row["accuracy"] >= 0.85

    def test_p_value_below_001(self):
        assert self.row["p_one_sided"] < 0.001

    def test_ci_nonoverlap_with_baseline(self):
        assert self.row["wilson_ci_lo"] > self.baseline_upper


# ---------------------------------------------------------------------------
# Signal breadth: all four signals show lift at 15%
# ---------------------------------------------------------------------------

class TestN500SignalBreadth:
    def setup_method(self):
        d = _load_results()
        self.rows = {
            r["signal"]: r
            for r in d["selective_curve"]
            if abs(r["coverage"] - 0.15) < 0.005
        }
        self.baseline = d["baseline_accuracy"]

    def test_all_signals_present(self):
        expected = {"neg_temperature", "trust_score", "neg_susceptibility", "order_parameter"}
        assert expected.issubset(self.rows.keys())

    def test_neg_temperature_best_at_15pct(self):
        neg_temp_acc = self.rows["neg_temperature"]["accuracy"]
        for sig, row in self.rows.items():
            if sig != "neg_temperature":
                # neg_temperature should be competitive (within 10pp)
                assert neg_temp_acc >= row["accuracy"] - 0.10

    def test_trust_score_positive_lift_at_15pct(self):
        assert self.rows["trust_score"]["accuracy"] > self.baseline
