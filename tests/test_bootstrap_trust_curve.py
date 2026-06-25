"""Regression lock for bootstrap validation of the selective trust curve."""
from __future__ import annotations

import pathlib

import pytest

from experiments.bootstrap_trust_curve import run


@pytest.fixture(scope="module")
def report() -> dict:
    if not pathlib.Path("results/thermodynamic_eval_results.json").exists():
        pytest.skip("thermodynamic eval artifact missing")
    if not pathlib.Path("results/ablation_v2_canonical_results.json").exists():
        pytest.skip("canonical ablation artifact missing")
    # Use fewer iterations in test for speed; the real run uses 2000
    return run(
        "results/thermodynamic_eval_results.json",
        "results/ablation_v2_canonical_results.json",
        n_boot=500,
        coverage_points=[0.20, 0.25, 0.30],
        seed=99,
    )


def test_headline_bootstrap_validated(report: dict) -> None:
    """Headline operating point must be bootstrap-validated."""
    h = report["headline_neg_temperature_25pct"]
    assert h["bootstrap_validated"], (
        f"Headline NOT validated: mean_lift={h['mean_lift']}, "
        f"ci_lo={h['bootstrap_ci95_lo']}, pos_rate={h['positive_signal_rate']}"
    )


def test_headline_positive_rate_high(report: dict) -> None:
    h = report["headline_neg_temperature_25pct"]
    assert h["positive_signal_rate"] >= 0.90, (
        f"Expected pos_rate >= 0.90, got {h['positive_signal_rate']}"
    )


def test_headline_ci_lower_positive(report: dict) -> None:
    h = report["headline_neg_temperature_25pct"]
    assert h["bootstrap_ci95_lo"] > 0, (
        f"Bootstrap 95% CI lower bound is not positive: {h['bootstrap_ci95_lo']}"
    )


def test_20pct_also_validated(report: dict) -> None:
    r = report["signals"]["neg_temperature"]["0.2"]
    assert r["bootstrap_validated"] or r["positive_signal_rate"] >= 0.95, (
        f"20% operating point signal weaker than expected: {r}"
    )
