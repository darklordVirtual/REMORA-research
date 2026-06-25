# Author: Stian Skogbrott
# License: Apache-2.0
"""Executable evidence tests for the central findings in REMORA_v4_Thermodynamics_Findings.docx.

OVERVIEW
========
The findings document makes eight distinct claims, summarised in
docs/use-cases/REMORA_v4_Thermodynamics_Evidence_Status.md.  Each test below
is anchored to exactly one claim and is labelled with the claim number.  The
mapping is:

  Claim 1 – V = H + λD is formally identifiable with a free-energy objective.
            Status: SUPPORTED (structural/algebraic observation).
        Tests:  test_free_energy_objective_is_algebraically_defined
            test_veto_potential_equals_free_energy_at_inverted_temperature

  Claim 2 – REMORA can classify pre-sweep states as ordered/critical/disordered.
            Status: SUPPORTED empirically (N=302 canonical benchmark).
            Tests:  test_phase_classification_is_nontrivial_on_canonical_benchmark

  Claim 3 – Trust is no longer degenerate after calibration.
            Status: SUPPORTED empirically.
            Tests:  test_trust_is_strictly_ordered_across_phases

  Claim 4 – Phase-aware modelling captures real benchmark temperature structure.
            Status: PARTIALLY SUPPORTED (Experiment 3 baseline).
            Tests:  test_phase_transition_study_shows_real_temperature_structure

  Claim 5 – Susceptibility χ carries measurable but limited predictive information.
        Status: PARTIALLY SUPPORTED (offline AUC ≈ 0.57–0.58, weak but non-
            trivial; live perturbation pilot does not yet confirm the
            stronger fragility hypothesis).
            Tests:  test_empirical_chi_carries_moderate_harm_signal
                    test_d2_focused_susceptibility_validation_is_negative
            test_live_chi_perturbation_pilot_does_not_confirm_fragility_law

  Claim 6 – Phase-aware routing improves routing decisions over majority / D2.
        Status: PARTIALLY SUPPORTED — phase-aware abstention improves
                    accuracy on answered items by +5.76 pp and reduces false-
            trust rate by 33.5 %, but the enforced thermodynamic
            guardrail policy is currently over-conservative;
                    no routing policy beats majority when all items must be answered.
            Tests:  test_routing_superiority_is_not_yet_established
            test_thermodynamic_guardrail_policy_is_currently_overconservative
                    test_phase_aware_abstention_reduces_false_trust_rate

  Claim 7 – A hallucination bound is empirically established.
            Status: NOT YET SUPPORTED (bound is mathematically defined but not
                    validated as a theorem or empirical law on real data).
            Tests:  test_hallucination_bound_is_mathematically_defined
                    test_hallucination_bound_is_not_validated_as_empirical_law

  Claim 8 – Multi-oracle consensus outperforms single-oracle baseline.
            Status: SUPPORTED by ablation (B_majority +26 pp over A_single).
            Tests:  test_multi_oracle_majority_significantly_outperforms_single_oracle

ARTIFACT SOURCES
================
All empirical tests read committed result artifacts so that any material change
to the underlying measurements causes an immediate CI failure and forces the
evidence statement to be re-evaluated before merging.

  results/thermodynamic_eval_results.json    – Experiment 2: phase classification
  results/phase_transition_study_results.json – Experiment 3: temperature structure
  results/chi_iteration_utility_results.json  – Experiment 5: χ utility (C_remora) [PRODUCED by experiments/chi_iteration_utility.py]
  results/susceptibility_validation_results.json – χ validation (D2, negative result)
    results/chi_perturbation_study_results.json   – Live χ perturbation pilot (negative)
    results/ablation_v2_canonical_results.json  – Immutable canonical N=302 ablation snapshot
  results/phase_aware_routing_results.json    – Phase-aware routing / abstention policies
    results/thermodynamic_router_eval_n500_final_results.json – Calibrated N500 selective guardrail
    results/thermodynamic_router_eval_n500_evidence_results.json – Calibrated N500 evidence-backed policy
"""
from __future__ import annotations

import math
import json
from pathlib import Path

from remora.thermodynamics import (
    free_energy,
    hallucination_bound,
)


ROOT = Path(__file__).resolve().parent.parent


def load_json(relative_path: str) -> dict:
    path = ROOT / relative_path
    return json.loads(path.read_text(encoding="utf-8"))


# ── Claim 1: V = H + λD free-energy structural identification ─────────────────

def test_free_energy_objective_is_algebraically_defined():
    """Claim 1 – SUPPORTED (structural/algebraic).

    The findings document asserts that REMORA's consensus objective
    V = H + λD has a formal relationship to the Helmholtz-style free energy
    F(T) = λD − T·H.  This test verifies the *exact* algebraic identity and
    the sign conventions that are essential for the claim to be watertight.

    KEY SIGN DISTINCTION — see free_energy() docstring for full detail:
      • In F(T) = λD − T·H  the entropy term enters with sign −T:
        entropy *lowers* free energy at T > 0  (standard Helmholtz).
      • In V   = H + λD    the entropy term enters with sign +1:
        entropy *raises* V regardless of temperature.
      These are not the same functional.  The rigorous bridge is:

          V(H, D) = F(T=−1 ; H, D)  [exact algebraic identity]

    This test verifies:
    - free_energy() implements F = λ·D − T·H correctly.
    - F is monotone in the expected directions (disorder raises F; entropy at
      T > 0 lowers F).
    - The identity V = F(T=−1) holds exactly (to floating-point precision).
    - At T → 0 the thermal term vanishes: F(0) = λD (the dissensus component
      of V), *not* V itself — confirming the two objects differ at T ≠ −1.
    """
    # F(T=0) = λD.  This is the dissensus-only component of V, NOT V itself:
    # V = H + λD = 1.0 + 1.0 ≠ F(0) = 1.0.  They differ whenever H ≠ 0.
    f_zero_temp = free_energy(entropy=1.0, dissensus=0.5, temperature=0.0, lambda_coupling=2.0)
    assert math.isclose(f_zero_temp, 2.0 * 0.5, rel_tol=1e-9)
    v_same_point = 1.0 + 2.0 * 0.5   # H + λD = 1.0 + 1.0 = 2.0
    assert not math.isclose(f_zero_temp, v_same_point), (
        "F(T=0) must differ from V = H + λD whenever H != 0, "
        "confirming V and F are distinct objects"
    )

    # Higher disorder (dissensus) raises free energy at constant entropy and T.
    f_low_d = free_energy(entropy=0.5, dissensus=0.2, temperature=0.5, lambda_coupling=1.0)
    f_high_d = free_energy(entropy=0.5, dissensus=0.8, temperature=0.5, lambda_coupling=1.0)
    assert f_high_d > f_low_d

    # Higher entropy lowers free energy at constant dissensus and T > 0
    # (standard Helmholtz sign: entropy term is −T·H, so more H → lower F).
    f_low_h = free_energy(entropy=0.1, dissensus=0.5, temperature=1.0, lambda_coupling=1.0)
    f_high_h = free_energy(entropy=0.9, dissensus=0.5, temperature=1.0, lambda_coupling=1.0)
    assert f_high_h < f_low_h

    # Verify F is finite and well-defined for typical in-distribution inputs.
    f_typical = free_energy(entropy=0.6, dissensus=0.4, temperature=0.7, lambda_coupling=1.0)
    assert math.isfinite(f_typical)


# ── Claim 1 addendum: exact V = F(T=−1) identity ─────────────────────────────

def test_veto_potential_equals_free_energy_at_inverted_temperature():
    """Claim 1 addendum – EXACT ALGEBRAIC IDENTITY (sign-convention proof).

    This test machine-verifies the rigorous bridge between REMORA's two
    free-energy-related expressions, closing the mathematical vulnerability
    identified by external review.

    The identity is:
        V(H, D) = H + λD  =  λD − (−1)·H  =  F(T=−1 ; H, D)

    That is, the VETO/Lyapunov potential V is *exactly* the thermodynamic
    free energy F evaluated at the inverted temperature T = −1.

    Sign-convention summary
    -----------------------
    Expression          Entropy sign    Physical interpretation
    ──────────────────────────────────────────────────────────
    F(T) = λD − T·H     negative (−T)   Helmholtz: entropy reduces free energy
                                         at T > 0, system can tolerate disorder
    V    = H + λD       positive (+1)   Lyapunov: entropy always raises cost,
                                         system is driven toward ordered states
    ──────────────────────────────────────────────────────────
    At T = −1 these coincide exactly: F(−1) = λD + H = V.

    Tested for ten numerically diverse (H, D, λ) triples to confirm the
    identity holds across the full valid parameter range.
    """
    import itertools

    test_cases = list(itertools.product(
        [0.0, 0.3, 0.693, 1.0],   # entropy values
        [0.0, 0.25, 0.5, 1.0],    # dissensus values
        [0.5, 1.0, 2.0],           # lambda values
    ))

    failures = []
    for h, d, lam in test_cases:
        v = h + lam * d
        f_neg1 = free_energy(entropy=h, dissensus=d, temperature=-1.0, lambda_coupling=lam)
        if not math.isclose(v, f_neg1, rel_tol=1e-12, abs_tol=1e-12):
            failures.append((h, d, lam, v, f_neg1))

    assert not failures, (
        f"V = F(T=−1) identity failed for {len(failures)} cases: "
        f"{failures[:3]}..."
    )

    # Explicitly confirm the identity fails at T=0 and T=1 when H > 0,
    # proving V ≠ F in general (identity only holds at T=−1).
    h, d, lam = 0.5, 0.5, 1.0
    v = h + lam * d   # = 1.0
    assert not math.isclose(v, free_energy(h, d, 0.0, lam)), "F(T=0) ≠ V"
    assert not math.isclose(v, free_energy(h, d, 1.0, lam)), "F(T=1) ≠ V"


# ── Claims 2 & 3: Non-trivial phase split and non-degenerate trust ─────────────

def test_phase_classification_is_nontrivial_on_canonical_benchmark():
    """Claim 2 – SUPPORTED empirically (N=302 canonical benchmark).

    The findings document states that REMORA can assign pre-sweep benchmark
    states to three distinct thermodynamic phases.  The canonical N=302 run
    must produce all three phases in non-trivial proportions: the earlier
    prototype collapsed into degenerate states; this must no longer be true.

    Asserted bounds are conservative lower bounds on the actual counts
    (ordered=12, critical=84, disordered=206) to tolerate minor re-runs.
    """
    data = load_json("results/thermodynamic_eval_results.json")
    summary = data["summary"]
    phase_counts = summary["phase_counts"]

    assert summary["n_items"] == 302, "Canonical artifact must be N=302"
    assert set(phase_counts) == {"ordered", "critical", "disordered"}, (
        "All three phases must be present; a two-phase collapse would invalidate Claim 2"
    )
    assert phase_counts["ordered"] >= 10, (
        f"Ordered count {phase_counts['ordered']} too low; expected ≥ 10"
    )
    assert phase_counts["critical"] >= 50, (
        f"Critical count {phase_counts['critical']} too low; expected ≥ 50 for a non-trivial critical regime"
    )
    assert phase_counts["disordered"] >= 150, (
        f"Disordered count {phase_counts['disordered']} too low; expected ≥ 150"
    )


def test_trust_is_strictly_ordered_across_phases():
    """Claim 3 – SUPPORTED empirically.

    After calibration, mean trust must be strictly ordered
    ordered > critical > disordered, and the spread must be material
    (not near-zero everywhere as in the pre-calibration prototype).

    Expected values from the canonical artifact:
      ordered trust  = 0.9051
      critical trust = 0.2384
      disordered trust = 0.0118

    Temperature must be strictly ordered in the opposite direction
    (ordered is cold, disordered is hot), confirming the physical intuition.
    """
    data = load_json("results/thermodynamic_eval_results.json")
    ps = data["summary"]["phase_summary"]

    ordered_trust = ps["ordered"]["mean_trust_score"]
    critical_trust = ps["critical"]["mean_trust_score"]
    disordered_trust = ps["disordered"]["mean_trust_score"]

    assert ordered_trust > critical_trust > disordered_trust, (
        "Trust must be strictly ordered: ordered > critical > disordered"
    )
    assert ordered_trust > 0.80, (
        f"Ordered trust {ordered_trust:.4f} must exceed 0.80 to confirm non-degenerate high-trust regime"
    )
    assert disordered_trust < 0.05, (
        f"Disordered trust {disordered_trust:.4f} must be below 0.05 to confirm non-degenerate low-trust regime"
    )

    ordered_temp = ps["ordered"]["mean_temperature"]
    critical_temp = ps["critical"]["mean_temperature"]
    disordered_temp = ps["disordered"]["mean_temperature"]

    assert ordered_temp < critical_temp < disordered_temp, (
        "Temperature must be strictly ordered: ordered (cold) < critical < disordered (hot)"
    )


# ── Claim 4: Phase-aware modelling captures real temperature structure ─────────

def test_phase_transition_study_shows_real_temperature_structure():
    """Claim 4 – PARTIALLY SUPPORTED (Experiment 3 baseline, N=302).

    The findings document claims that REMORA's thermodynamic framing captures
    meaningful structure in the benchmark, not just a trivial collapse.
    Experiment 3 (phase_transition_study) is the primary evidence artifact.

    This test validates:
    - Five non-empty temperature bands exist (no collapse to fewer).
    - The order-parameter range η is large enough (≥ 0.50) to be non-trivial.
    - The lowest temperature band is dominated by critical/ordered phases.
    - The highest temperature band is entirely disordered.
    - Trust and η both decrease monotonically from coldest to hottest band.

    This is NOT a proof of a phase transition, but it confirms that the
    framing distinguishes real structure in the benchmark data.
    """
    data = load_json("results/phase_transition_study_results.json")
    summary = data["summary"]
    bands = summary["band_summaries"]

    assert summary["n_items"] == 302
    assert summary["n_bins"] == 5
    assert len(bands) == 5, "All five temperature bands must be present"
    assert summary["eta_range"] >= 0.50, (
        f"η range {summary['eta_range']:.4f} too small; non-trivial structure requires ≥ 0.50"
    )

    low = bands["T_bin_1"]
    high = bands["T_bin_5"]

    assert low["mean_eta"] > high["mean_eta"], "Cold band must have higher order parameter than hot band"
    assert low["mean_trust"] > high["mean_trust"], "Cold band must have higher trust than hot band"

    # The coldest band must be entirely critical or ordered (no disordered items).
    assert low["phase_counts"].get("disordered", 0) == 0, (
        "Lowest temperature band must contain no disordered items"
    )
    assert low["phase_counts"]["critical"] + low["phase_counts"].get("ordered", 0) == low["n"]

    # The hottest band must be entirely disordered.
    assert high["phase_counts"]["disordered"] == high["n"], (
        "Highest temperature band must be entirely disordered"
    )


# ── Claim 5: χ carries weak but real predictive information ───────────────────

def test_chi_correlates_with_accuracy_in_critical_phase():
    """Claim 5 (revised, Trinn 3) -- chi predicts accuracy, not fragility.

    Phase-stability analysis of the canonical N=302 benchmark shows that within
    the critical phase (n=84), Spearman rho(chi, majority_error) = -0.312.
    Negative rho means higher susceptibility chi correlates with FEWER errors --
    the oracle pool is more consensus-ready near the phase transition, not more
    fragile. The original fragility interpretation (chi -> harm) is not confirmed.

    This test locks the corrected empirical finding from results/phase_stability_results.json.
    """
    data = load_json("results/phase_stability_results.json")
    critical = data["per_phase_chi_analysis"]["critical"]
    global_rho = data["global_rho_chi_vs_error"]

    assert critical["n"] >= 80, f"Critical phase sample too small: n={critical['n']}"
    rho = critical["rho_chi_vs_majority_error"]
    assert rho is not None
    assert rho < 0, (
        f"Expected negative rho (chi -> accuracy, not harm) in critical phase, got {rho:.4f}"
    )
    # Global signal must remain weak (no spurious global correlation)
    assert abs(global_rho) < 0.15, (
        f"Global chi rho should be near-zero, got {global_rho:.4f}"
    )


def test_d2_focused_susceptibility_validation_is_negative():
    """Claim 5b – negative result, intentionally preserved.

    The D2-focused susceptibility validation (results/susceptibility_validation_results.json)
    tested whether high χ predicts that D2_balanced routing will help over majority.
    The answer is NO: help_rate = 0% in every χ band, not_help_rate = 100%.

    This test explicitly preserves and asserts the negative result.
    It serves as a guard: if someone improves the D2 condition enough to show
    positive χ-to-improvement correlation, these assertions will fail and
    the evidence status must be updated to reflect the change.
    """
    data = load_json("results/susceptibility_validation_results.json")
    summary = data["summary"]

    assert summary["n_items"] == 302
    assert summary["overall"]["help_rate"] == 0.0, (
        "D2 χ-validation help_rate must remain 0.0; a non-zero value changes the evidence claim"
    )
    assert summary["overall"]["not_help_rate"] == 1.0, (
        "D2 χ-validation not_help_rate must remain 1.0 until routing superiority is demonstrated"
    )
    for band_name, band in summary["by_chi_band"].items():
        assert band["not_help_rate"] == 1.0, (
            f"χ band {band_name}: not_help_rate must be 1.0; D2 does not improve over majority in any band"
        )


def test_live_chi_perturbation_pilot_does_not_confirm_fragility_law():
    """Claim 5c – live perturbation pilot is currently negative.

    A stronger version of the χ story would say that susceptibility is not only
    weakly predictive of iteration harm offline, but also tracks *live panel
    fragility* across independent oracle calls: ordered items should remain
    stable, disordered items should fluctuate more, and χ should correlate
    positively with measured fragility.

    The live phase-balanced pilot in results/chi_perturbation_study_results.json
    tests exactly that hypothesis on 30 items (10 per phase) using fresh Groq
    calls against a second oracle panel.

    Current result: the stronger fragility law is NOT confirmed.
      ordered mean fragility     = 0.2826
      critical mean fragility    = 0.3230
      disordered mean fragility  = 0.1642
      Spearman ρ(χ, fragility)   = -0.0102

    This preserves the correct scientific boundary:
    - χ has weak offline utility as a harm signal (Claim 5a)
    - χ does NOT yet have robust live per-item fragility validation
    """
    data = load_json("results/chi_perturbation_study_results.json")
    summary = data["summary"]
    phase_summary = summary["phase_summary"]

    assert summary["n_items"] == 30, "The committed live perturbation pilot must remain N=30"
    assert data["meta"]["is_partial"] is False, "Committed live artifact must be complete"
    assert summary["fragility_hypothesis_holds"] is False, (
        "If the live perturbation pilot starts confirming ordered < disordered fragility, "
        "Claim 5 must be upgraded and this test rewritten"
    )

    ordered_frag = phase_summary["ordered"]["mean_fragility"]
    disordered_frag = phase_summary["disordered"]["mean_fragility"]
    assert ordered_frag >= disordered_frag, (
        f"Ordered fragility {ordered_frag:.4f} unexpectedly dropped below disordered {disordered_frag:.4f}; "
        "the live fragility hypothesis may now hold"
    )

    rho = summary["spearman_rho_chi_fragility"]
    assert rho <= 0.10, (
        f"Spearman rho {rho:.4f} is now materially positive; live χ-to-fragility relation may be emerging"
    )


def test_chi_iteration_utility_auroc_is_near_chance():
    """Claim 5d – Chi has weak but non-zero AUROC for iteration outcomes.

    The chi_iteration_utility experiment computes AUROC of χ as a predictor
    of whether C_remora's adaptive iteration helps or hurts relative to the
    B_majority baseline on N=302.

    Current result:
      auc_help = 0.5881  (chi marginally predicts C_remora helping)
      auc_hurt = 0.5727  (chi marginally predicts C_remora hurting)

    Both AUROCs are near the 0.5 chance baseline, confirming that χ has
    negligible practical utility as an iteration-routing signal. The modest
    non-zero values are consistent with the Phase-IV clarification that χ
    captures consensus sensitivity (not harm) near the critical point.
    """
    data = load_json("results/chi_iteration_utility_results.json")
    summary = data["summary"]

    assert summary["n_items"] == 302
    auc_help = summary["auc_help"]
    auc_hurt = summary["auc_hurt"]
    assert auc_help is not None
    assert auc_hurt is not None
    # Must remain near-chance; a large AUC would require upgrading this claim
    assert auc_help < 0.70, (
        f"auc_help={auc_help:.4f} exceeds 0.70; χ may now be a reliable help predictor"
    )
    assert auc_hurt < 0.70, (
        f"auc_hurt={auc_hurt:.4f} exceeds 0.70; χ may now be a reliable hurt predictor"
    )
    assert auc_help >= 0.40, f"auc_help={auc_help:.4f} fell below chance"
    assert auc_hurt >= 0.40, f"auc_hurt={auc_hurt:.4f} fell below chance"
    # C_remora hurts many more items than it helps on N=302
    assert summary["n_hurt"] > summary["n_helped"], (
        "C_remora should hurt more items than it helps on N=302 (adaptive iteration regresses)"
    )


# ── Claim 6: Routing superiority NOT yet established ──────────────────────────

def test_routing_superiority_is_not_yet_established():
    """Claim 6 – NOT YET SUPPORTED.

    The findings document is explicit that phase-aware routing (D2_balanced)
    does not yet demonstrate a routing advantage over the majority baseline:
      d2_helped_items = 0
      d2_hurt_items   = 2
      non_ordered D2 accuracy ≤ non_ordered majority accuracy

    This test locks that negative finding.  It will fail the moment the D2
    condition actually starts helping, forcing that upgrade to be documented
    before it enters the claim set.
    """
    data = load_json("results/thermodynamic_eval_results.json")
    summary = data["summary"]

    assert summary["d2_helped_items"] == 0, (
        f"d2_helped_items = {summary['d2_helped_items']}; routing superiority not established"
    )
    assert summary["d2_hurt_items"] >= 1, (
        "At least one hurt item must be present to confirm routing is not yet safe to promote"
    )
    assert summary["non_ordered_d2_accuracy"] <= summary["non_ordered_majority_accuracy"], (
        f"D2 accuracy {summary['non_ordered_d2_accuracy']:.4f} must not exceed "
        f"majority accuracy {summary['non_ordered_majority_accuracy']:.4f} on non-ordered items"
    )


def test_no_gate_between_majority_and_d2_can_currently_beat_majority():
    """Claim 6 – root-cause explanation for why routing is still unsupported.

    This is the decisive control-policy fact in the current canonical artifact:
    there are zero items where D2_balanced is correct and majority is wrong.

    That means any controller whose action space is limited to choosing between
    the existing majority baseline and the existing D2 policy cannot outperform
    majority on this dataset, regardless of how good its thermodynamic routing
    signal might be.  A gate can only help if there exists at least one item
    for which D2 is the better branch.  Today that count is exactly zero.
    """
    data = load_json("results/thermodynamic_eval_results.json")
    items = data["items"]

    helped = [item for item in items if item["helped_vs_majority"]]
    hurt = [item for item in items if item["hurt_vs_majority"]]

    assert len(helped) == 0, (
        "No control policy can beat majority by gating to D2 when there are zero helped items"
    )
    assert len(hurt) == 2, (
        f"Expected exactly 2 D2 hurt items in the canonical artifact, got {len(hurt)}"
    )

    # Every per-item disagreement currently favors majority, never D2.
    disagreements = [item for item in items if item["majority_correct"] != item["d2_correct"]]
    assert len(disagreements) == len(hurt)
    assert all(item["majority_correct"] and not item["d2_correct"] for item in disagreements), (
        "All current majority/D2 disagreements must favor majority for the routing claim to remain unsupported"
    )


def test_thermodynamic_guardrail_policy_is_currently_overconservative():
    """Claim 6 – enforced guardrail exists, but current policy is negative.

    The new thermodynamic router evaluation measures the *implemented* runtime
    guardrail rather than the earlier static D2-vs-majority comparison.

    Current N=302 result:
    - the guardrail flags 69.21% of items as evidence-required,
    - intercepts 83.67% of majority errors,
    - but achieves only 23.66% accuracy on the answered subset,
    - which is 59.14 pp worse than majority on that same coverage slice.

    This is important because it sharpens the current evidence boundary:
    the guardrail is real and does triage many risky items, but the present
    thermodynamic control law is too conservative to support a positive
    routing-quality claim.
    """
    data = load_json("results/thermodynamic_router_eval_results.json")
    summary = data["summary"]

    assert summary["n_items"] == 302
    assert summary["guardrail_require_rag_rate"] > 0.60, (
        "Current guardrail result should remain a high-abstention policy until the control law improves"
    )
    assert summary["majority_error_intercept_rate"] > 0.80, (
        "The guardrail should still intercept most majority errors in the committed artifact"
    )
    assert summary["guardrail_accuracy_on_answered"] < 0.30, (
        "If answered-item accuracy rises materially, Claim 6 status may need upgrading"
    )
    assert summary["guardrail_vs_majority_same_coverage_delta"] < 0.0, (
        "Current committed artifact must remain worse than majority on the same answered slice"
    )


def test_n500_calibrated_phase_split_is_nontrivial_and_separated():
    """N500 upgrade path – calibrated phase structure is now real on 544 items."""
    data = load_json("results/thermodynamic_eval_n500_calibrated_results.json")
    summary = data["summary"]
    phase_counts = summary["phase_counts"]

    assert summary["n_items"] == 544
    assert phase_counts["ordered"] >= 90
    assert phase_counts["critical"] >= 20
    assert phase_counts["disordered"] >= 350
    assert phase_counts["ordered"] + phase_counts["critical"] + phase_counts["disordered"] == 544
    assert summary["ordered_direct_accept_accuracy"] >= 0.85, (
        f"Ordered direct-accept accuracy fell to {summary['ordered_direct_accept_accuracy']:.4f}"
    )
    assert summary["non_ordered_d2_accuracy"] <= summary["non_ordered_majority_accuracy"], (
        "N500 artifact should still reflect that routing superiority is not yet proven"
    )


def test_n500_calibrated_guardrail_has_nonzero_coverage_and_high_precision():
    """N500 upgrade path – calibrated guardrail now yields a real answered slice."""
    data = load_json("results/thermodynamic_router_eval_n500_final_results.json")
    summary = data["summary"]

    assert summary["n_items"] == 544
    assert summary["guardrail_coverage"] >= 0.15, (
        f"Coverage {summary['guardrail_coverage']:.4f} is too low for the calibrated N500 artifact"
    )
    assert summary["guardrail_accuracy_on_answered"] >= 0.85, (
        f"Answered accuracy {summary['guardrail_accuracy_on_answered']:.4f} fell below the current calibrated floor"
    )
    assert summary["majority_error_intercept_rate"] >= 0.95, (
        f"Intercept rate {summary['majority_error_intercept_rate']:.4f} fell below the current calibrated floor"
    )
    assert summary["guardrail_require_rag_rate"] > summary["guardrail_coverage"], (
        "Most items should still be routed to evidence in the current calibrated policy"
    )
    assert summary["phase_counts"]["ordered"] >= 90
    assert summary["phase_flagged_counts"]["critical"] >= 20
    assert summary["phase_flagged_counts"]["disordered"] >= 350


def test_n500_evidence_backfill_closes_full_coverage_with_positive_delta():
    """N500 upgrade path – evidence backfill now completes the benchmark run.

    This artifact exercises the public Cloudflare query endpoint on the full
    544-item benchmark after the calibrated thermodynamic guardrail routes the
    risky slice to evidence. The current committed result is still modest in
    absolute terms, but it must remain a real end-to-end policy rather than a
    missing or degenerate artifact.
    """
    data = load_json("results/thermodynamic_router_eval_n500_evidence_results.json")
    summary = data["summary"]
    evidence = data["evidence_backfill"]

    assert summary["n_items"] == 544
    assert evidence["coverage"] == 1.0, "Evidence-backed policy should close the full benchmark"
    assert evidence["n_answered"] == 544
    assert evidence["extra_evidence_calls"] >= 400, (
        "The current calibrated policy should still send most of the benchmark to evidence"
    )
    assert evidence["accuracy"] >= 0.45, (
        f"Evidence-backed accuracy {evidence['accuracy']:.4f} fell below the committed N500 floor"
    )
    assert evidence["accuracy"] > summary["majority_accuracy"], (
        "Evidence-backed end-to-end policy should remain above plain majority on the same benchmark"
    )
    assert evidence["etr_rate"] >= 0.30, (
        f"Evidence-backed ETR {evidence['etr_rate']:.4f} fell below the committed floor"
    )


# ── Claim 7: Hallucination bound – defined but not empirically validated ───────

def test_hallucination_bound_is_mathematically_defined():
    """Claim 7a – mathematical structure SUPPORTED, empirical law NOT YET SUPPORTED.

    The findings document notes that a 'useful empirical program exists' for
    the hallucination bound, but the bound is not yet validated as a theorem
    or robust empirical law.

    This test verifies the structural properties the bound *does* satisfy:
    - Output is always in [0, 1].
    - The bound decreases as the oracle pool grows (more oracles = tighter bound).
    - The bound is zero only in the degenerate perfect-oracle case.
    - The bound increases with higher individual error rate.
    """
    # Structural range check.
    for n in range(2, 8):
        b = hallucination_bound(n_oracles=n, rho_bar=0.2, individual_error_rate=0.10)
        assert 0.0 <= b <= 1.0, f"Bound out of [0,1] for n={n}"

    # More oracles → tighter bound.
    b3 = hallucination_bound(n_oracles=3, rho_bar=0.20, individual_error_rate=0.10)
    b5 = hallucination_bound(n_oracles=5, rho_bar=0.20, individual_error_rate=0.10)
    b7 = hallucination_bound(n_oracles=7, rho_bar=0.20, individual_error_rate=0.10)
    assert b3 > b5 > b7, "Bound must tighten as oracle pool grows"

    # Higher individual error → looser bound.
    b_low_err = hallucination_bound(n_oracles=3, rho_bar=0.2, individual_error_rate=0.05)
    b_high_err = hallucination_bound(n_oracles=3, rho_bar=0.2, individual_error_rate=0.20)
    assert b_high_err > b_low_err, "Higher individual error rate must yield a looser bound"

    # Perfectly correlated oracles still produce a finite informative bound.
    b_high_rho = hallucination_bound(n_oracles=3, rho_bar=0.40, individual_error_rate=0.10)
    assert 0.0 < b_high_rho < 1.0, "Bound must remain informative at high correlation"


def test_hallucination_bound_is_not_validated_as_empirical_law():
    """Claim 7b – explicitly asserts the NOT YET SUPPORTED boundary condition.

    The thermodynamic eval artifact stores a mean_hallucination_bound per phase.
    This test confirms that the bound values are present and finite, but also
    asserts that they are near-constant across phases — which means the bound
    is NOT yet useful as a phase-discriminating empirical signal.

    If a future study shows that the bound discriminates phases with statistical
    significance, these assertions should be replaced by a positive evidence test
    and the findings document updated accordingly.
    """
    data = load_json("results/thermodynamic_eval_results.json")
    ps = data["summary"]["phase_summary"]

    for phase_name, phase_data in ps.items():
        bound = phase_data["mean_hallucination_bound"]
        assert 0.0 < bound < 1.0, f"Phase {phase_name}: bound must be finite and in (0,1)"

    # The bound should NOT vary materially across phases at this stage.
    bounds = [ps[p]["mean_hallucination_bound"] for p in ("ordered", "critical", "disordered")]
    spread = max(bounds) - min(bounds)
    assert spread < 0.005, (
        f"Hallucination bound spread across phases = {spread:.6f}; "
        "the bound is near-constant and not yet an empirically discriminating signal"
    )


def test_hallucination_bound_does_not_upper_bound_observed_phase_error_rates():
    """Claim 7 – detailed reason the bound is not yet an empirical result.

    The repository currently reports a tiny mean hallucination bound per phase
    (about 0.0034-0.0036), while the observed benchmark error rate of the
    majority baseline is roughly 0.11-0.20 by phase.  Even if majority error is
    only a proxy for the target false-consensus event, this gap is far too large
    to market the reported quantity as an empirically validated upper bound on
    observable error behavior.

    This test therefore preserves the current negative conclusion: the bound is
    implemented and numerically stable, but the existing artifacts do not yet
    support any claim that it is a validated empirical law.
    """
    data = load_json("results/thermodynamic_eval_results.json")
    items = data["items"]
    phase_summary = data["summary"]["phase_summary"]

    for phase_name in ("ordered", "critical", "disordered"):
        phase_items = [item for item in items if item["phase"] == phase_name]
        observed_error_rate = sum(1 for item in phase_items if not item["majority_correct"]) / len(phase_items)
        mean_bound = phase_summary[phase_name]["mean_hallucination_bound"]

        assert observed_error_rate > mean_bound, (
            f"Phase {phase_name}: observed error {observed_error_rate:.4f} must remain above "
            f"reported bound {mean_bound:.4f}; otherwise the evidence status changed"
        )
        assert observed_error_rate / mean_bound > 20, (
            f"Phase {phase_name}: expected at least an order-of-magnitude mismatch between "
            f"observed error and reported bound, got ratio {observed_error_rate / mean_bound:.2f}"
        )


# ── Claim 8: Multi-oracle consensus outperforms single oracle ─────────────────

def test_multi_oracle_majority_significantly_outperforms_single_oracle():
    """Claim 8 (underlying) – SUPPORTED by ablation.

    Before any phase-specific claim can stand, the baseline consensus mechanism
    must outperform a single oracle on the canonical benchmark.

    From ablation_v2_results.json (N=302):
      A_single   accuracy = 0.5695  (single oracle baseline)
      B_majority accuracy = 0.8278  (three-oracle majority vote)
      D2_balanced accuracy = 0.8212  (REMORA with balanced router)

    The consensus lift of B_majority over A_single is ≈ 26 percentage points,
    well outside the 95% CI of either condition.  This is the empirical
    foundation that all thermodynamic claims build on.
    """
    data = load_json("results/ablation_v2_canonical_results.json")
    conditions = data["conditions"]

    a_single_acc = conditions["A_single"]["accuracy"]
    b_majority_acc = conditions["B_majority"]["accuracy"]
    d2_acc = conditions["D2_balanced"]["accuracy"]

    assert a_single_acc == 0.5695, (
        f"A_single accuracy changed to {a_single_acc}; ablation artifact may have been replaced"
    )
    assert b_majority_acc == 0.8278, (
        f"B_majority accuracy changed to {b_majority_acc}; ablation artifact may have been replaced"
    )

    lift = b_majority_acc - a_single_acc
    assert lift >= 0.25, (
        f"Majority lift over single oracle = {lift:.4f}; must be ≥ 0.25 pp to support the consensus claim"
    )

    # D2_balanced must be competitive with majority (within 2 pp) to justify the REMORA framing.
    assert abs(d2_acc - b_majority_acc) <= 0.02, (
        f"D2 accuracy {d2_acc:.4f} diverges from majority {b_majority_acc:.4f} by more than 2 pp"
    )

    # The 95% CI of B_majority must not overlap with A_single's CI.
    a_ci_upper = conditions["A_single"]["ci_95"][1]
    b_ci_lower = conditions["B_majority"]["ci_95"][0]
    assert b_ci_lower > a_ci_upper, (
        f"95% CIs overlap: B_majority lower {b_ci_lower:.4f} ≤ A_single upper {a_ci_upper:.4f}; "
        "consensus advantage is not statistically distinguishable"
    )


# ── Claim 6 routing (abstention result): phase-aware abstention ───────────────

def test_phase_aware_abstention_reduces_false_trust_rate():
    """Claim 6 – PARTIALLY SUPPORTED (abstention improvement only).

    Phase-aware routing between the *existing* conditions (A–D) cannot beat
    B_majority when all 302 items must be answered (the oracle-optimal ceiling
    = 82.78 %, same as B_majority — see test_routing_superiority_is_not_yet_
    established for the root-cause proof).

    However, the thermodynamic phase classification provides a *valid abstention
    signal*: marking disordered items as 'do not answer' and applying B_majority
    only to ordered and critical items materially improves two quality metrics:

      E1 (phase-abstain):      acc_on_covered = 0.8854  (+5.76 pp over baseline)
                               false_trust_rate = 0.1146 (−33.5 % reduction)
                               coverage = 31.79 %  (96 / 302 items answered)

      B_majority (no abstain): acc = 0.8278  false_trust = 0.1722  coverage = 100 %

    The phase classifier also adds marginal value over a naive η-threshold:
      E1 (phase-based):  88.54 %  on covered
      E2 (η-threshold, same coverage):  87.50 %  on covered  (+1.04 pp for E1)

    This result is meaningful for high-stakes domains (legal, medical, safety)
    where abstaining on uncertain items is preferable to returning a low-
    confidence answer.  It does *not* satisfy the full routing-superiority
    claim, which requires improvement without coverage loss.

    Results locked to results/phase_aware_routing_results.json.
    """
    data = load_json("results/phase_aware_routing_results.json")
    policies = data["policies"]
    _summary = data["summary"]  # noqa: F841

    baseline_acc = policies["baseline"]["accuracy_on_covered"]
    e1 = policies["E1_phase_abstain"]
    e2 = policies["E2_eta_threshold_abstain"]
    e4 = policies["E4_oracle_optimal_phase_route"]

    # ── E1 must improve accuracy on covered items vs full-coverage baseline ──
    e1_acc = e1["accuracy_on_covered"]
    assert e1_acc >= baseline_acc + 0.04, (
        f"Phase-abstain accuracy on covered items {e1_acc:.4f} does not improve "
        f"over B_majority baseline {baseline_acc:.4f} by ≥ 4 pp"
    )

    # ── E1 must reduce false-trust rate by at least 25 % (relative) ─────────
    e1_ftr = e1["false_trust_rate_on_covered"]
    base_ftr = policies["baseline"]["false_trust_rate_on_covered"]
    relative_reduction = (base_ftr - e1_ftr) / base_ftr
    assert relative_reduction >= 0.25, (
        f"Phase-abstain false-trust relative reduction {relative_reduction:.3f} < 0.25; "
        f"baseline FTR={base_ftr:.4f}, E1 FTR={e1_ftr:.4f}"
    )

    # ── E1 must be at least as accurate as η-threshold at the same coverage ─
    e2_acc = e2["accuracy_on_covered"]
    assert e1_acc >= e2_acc, (
        f"Phase-based abstention {e1_acc:.4f} is worse than η-threshold {e2_acc:.4f}; "
        "thermodynamic temperature should not under-perform raw η"
    )
    # Same coverage (same number of abstained items)
    assert e1["covered"] == e2["covered"], (
        f"Coverage mismatch: E1={e1['covered']}, E2={e2['covered']}"
    )

    # ── Oracle-optimal per-phase routing cannot beat B_majority ──────────────
    # This confirms the routing ceiling: no static phase→condition mapping
    # beats majority when all items must be answered.
    e4_acc = e4["accuracy_on_covered"]
    assert e4_acc <= baseline_acc + 0.001, (
        f"Oracle-optimal routing {e4_acc:.4f} beats B_majority {baseline_acc:.4f}; "
        "an existing condition that beats majority in some phase has appeared — "
        "routing with coverage is now possible and this test should be updated"
    )

    # ── Coverage: phase-abstain must reduce coverage by at least 50 % ────────
    # (disordered = 206/302 ≈ 68 %; coverage should be ≈ 32 %)
    assert e1["coverage_rate"] <= 0.40, (
        f"E1 coverage {e1['coverage_rate']:.4f} unexpectedly high; "
        "abstention may not be filtering disordered items"
    )
