"""Regression lock for phase stability and chi re-analysis."""
from __future__ import annotations

import pathlib

import pytest

from experiments.phase_stability import run


@pytest.fixture(scope="module")
def report() -> dict:
    if not pathlib.Path("results/thermodynamic_eval_results.json").exists():
        pytest.skip("thermo artifact missing")
    if not pathlib.Path("results/ablation_v2_canonical_results.json").exists():
        pytest.skip("ablation artifact missing")
    return run(
        "results/thermodynamic_eval_results.json",
        "results/ablation_v2_canonical_results.json",
        n_boot=300,
        seed=7,
    )


def test_critical_and_disordered_stable(report: dict) -> None:
    for ph in ("critical", "disordered"):
        v = report["phase_fraction_stability"][ph]
        assert v["cv"] < 0.25, f"{ph} phase unstable: CV={v['cv']}"


def test_top25_composed_mostly_of_critical(report: dict) -> None:
    critical_frac = report["phase_composition_of_top25pct_selection"]["critical"]["mean_fraction_in_top25"]
    ordered_frac  = report["phase_composition_of_top25pct_selection"]["ordered"]["mean_fraction_in_top25"]
    assert critical_frac > 0.70, f"Critical fraction in top-25% too low: {critical_frac}"
    assert ordered_frac + critical_frac > 0.95, "Top-25% should be almost all ordered+critical"


def test_chi_negative_in_critical(report: dict) -> None:
    rho = report["per_phase_chi_analysis"]["critical"]["rho_chi_vs_majority_error"]
    # chi is negatively correlated with error within critical phase —
    # higher chi = more accurate (not more fragile as originally hypothesized).
    assert rho is not None
    assert rho < 0, f"Expected rho < 0 (chi -> accuracy in critical), got {rho}"


def test_global_chi_rho_small(report: dict) -> None:
    rho = report["global_rho_chi_vs_error"]
    assert rho is not None
    assert abs(rho) < 0.15, f"Global chi Spearman rho should be small, got {rho}"
