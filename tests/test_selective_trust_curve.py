"""Regression test for the selective trust curve breakthrough.

Locks the headline numbers from the canonical N=302 run so accidental
calibration drift cannot quietly erode the result.
"""
from __future__ import annotations

import pathlib

import pytest

from experiments.selective_trust_curve import run

THERMO = "results/thermodynamic_eval_results.json"
ABLATION = "results/ablation_v2_canonical_results.json"


@pytest.fixture(scope="module")
def report() -> dict:
    if not pathlib.Path(THERMO).exists() or not pathlib.Path(ABLATION).exists():
        pytest.skip("canonical artifacts missing")
    return run(THERMO, ABLATION, random_trials=500)


def test_baseline_locked(report: dict) -> None:
    assert report["meta"]["n_items"] == 302
    assert report["meta"]["baseline_rate"] == pytest.approx(0.8278, abs=1e-3)


def test_neg_temperature_25pct_breakthrough(report: dict) -> None:
    rows = {r["coverage_pct"]: r for r in report["curves"]["neg_temperature"]}
    r25 = rows[0.25]
    assert r25["k_covered"] == 76
    assert r25["correct"] == 72
    assert r25["accuracy"] == pytest.approx(0.9474, abs=1e-3)
    assert r25["lift_vs_baseline"] >= 0.10
    assert r25["p_value_one_sided_vs_baseline"] < 0.01
    ci_lo, ci_hi = r25["wilson_ci95"]
    assert ci_lo > 0.866, "lower Wilson CI must clear baseline upper CI bound"


def test_multiple_signals_significant(report: dict) -> None:
    # At least three distinct (signal, coverage) operating points should
    # remain significant at p < 0.05; this protects against a fragile
    # single-point fluke.
    assert report["summary"]["n_significant_points"] >= 3


def test_pure_susceptibility_not_significant(report: dict) -> None:
    # We claim susceptibility alone is not a strong predictor; lock that
    # honesty into the test so future runs don't drift into overclaiming.
    rows = report["curves"]["neg_susceptibility"]
    significant = [r for r in rows if r["p_value_one_sided_vs_baseline"] < 0.05 and r["lift_vs_baseline"] > 0]
    assert significant == [], f"susceptibility should not produce significant points yet, got {significant}"
