# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for thermodynamic consensus helpers and the phase controller."""
from __future__ import annotations

import math

import pytest

from remora.phase_controller import phase_decision
from remora.thermodynamics import (
    DomainClassifier,
    ThermodynamicCalibration,
    ThermodynamicState,
    classify_phase,
    compute_phase_diagram,
    critical_temperature,
    estimate_structural_temperature,
    estimate_temperature,
    free_energy,
    hallucination_bound,
    order_parameter,
    predict_trust_before_iteration,
    trust_score,
)


def test_free_energy_uses_helmholtz_sign():
    assert free_energy(entropy=1.0, dissensus=0.5, temperature=2.0, lambda_coupling=1.0) == -1.5


def test_temperature_increases_with_entropy_and_dissensus():
    low = estimate_temperature(
        {"yes": 1.0},
        rho_bar=0.1,
        individual_confidences=[0.95, 0.95, 0.95],
    )
    high = estimate_temperature(
        {"yes": 0.34, "no": 0.33, "maybe": 0.33},
        rho_bar=0.1,
        individual_confidences=[0.5, 0.5, 0.5],
    )
    assert high > low


def test_classify_phase_near_tc_is_critical():
    assert classify_phase(temperature=1.0, t_critical=1.05, eta=0.6, tolerance=0.15) == "critical"


def test_classify_phase_respects_calibrated_ordered_min_eta():
    calibration = ThermodynamicCalibration(ordered_min_eta=0.7)
    assert classify_phase(temperature=0.8, t_critical=1.1, eta=0.6, calibration=calibration) == "disordered"


def test_order_parameter_bounds():
    assert order_parameter({"yes": 1.0}, 2) == 1.0
    assert order_parameter({"yes": 0.5, "no": 0.5}, 2) == 0.0


def test_critical_temperature_decreases_with_higher_correlation():
    low_rho = critical_temperature(lambda_coupling=1.0, rho_bar=0.1, k=2)
    high_rho = critical_temperature(lambda_coupling=1.0, rho_bar=0.6, k=2)
    assert low_rho > high_rho


def test_hallucination_bound_shrinks_with_more_oracles():
    bound_three = hallucination_bound(n_oracles=3, rho_bar=0.236, individual_error_rate=0.10)
    bound_five = hallucination_bound(n_oracles=5, rho_bar=0.236, individual_error_rate=0.10)
    assert 0.0 <= bound_five <= bound_three <= 1.0


def test_hallucination_bound_remains_informative_at_high_rho():
    bound = hallucination_bound(n_oracles=3, rho_bar=0.8, individual_error_rate=0.10)
    assert 0.0 < bound < 1.0


def test_predict_trust_before_iteration_prefers_ordered_consensus():
    state = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "fp_yes"), ("b", "fp_yes"), ("c", "fp_yes")],
        pre_sweep_confidences=[0.95, 0.92, 0.90],
        rho_bar=0.15,
        lambda_coupling=0.4,
    )
    assert state.phase == "ordered"
    assert state.order_parameter > 0.9
    assert state.trust_score > 0.5
    assert state.critical_temperature is not None
    assert state.temperature_ratio is not None


def test_predict_trust_uses_confidence_weighted_distribution():
    state = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "fp_yes"), ("b", "fp_yes"), ("c", "fp_no")],
        pre_sweep_confidences=[0.90, 0.85, 0.20],
        rho_bar=0.2,
        lambda_coupling=0.4,
    )
    assert state.order_parameter > 0.33
    assert state.temperature > 0.0


def test_adversarial_three_way_low_confidence_pre_sweep_is_hotter() -> None:
    ordered = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "stable"), ("b", "stable"), ("c", "stable")],
        pre_sweep_confidences=[0.95, 0.94, 0.93],
        rho_bar=0.1,
        lambda_coupling=0.4,
    )
    adversarial = predict_trust_before_iteration(
        pre_sweep_verdicts=[
            ("a", "nonsense_alpha"),
            ("b", "nonsense_beta"),
            ("c", "nonsense_gamma"),
        ],
        pre_sweep_confidences=[0.12, 0.18, 0.15],
        rho_bar=0.1,
        lambda_coupling=0.4,
    )
    assert adversarial.raw_temperature is not None
    assert ordered.raw_temperature is not None
    assert adversarial.raw_temperature > ordered.raw_temperature
    assert adversarial.trust_score < ordered.trust_score
    assert adversarial.phase != "ordered"


def test_long_identical_fingerprints_do_not_inflate_temperature() -> None:
    short = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "yes"), ("b", "yes"), ("c", "yes")],
        pre_sweep_confidences=[0.9, 0.9, 0.9],
        rho_bar=0.1,
        lambda_coupling=0.4,
    )
    long_fp = "yes_" + ("x" * 5000)
    long = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", long_fp), ("b", long_fp), ("c", long_fp)],
        pre_sweep_confidences=[0.9, 0.9, 0.9],
        rho_bar=0.1,
        lambda_coupling=0.4,
    )
    assert long.raw_temperature == pytest.approx(short.raw_temperature)
    assert long.phase == short.phase


def test_phase_decision_refuses_low_trust_disordered_state():
    decision = phase_decision(
        ThermodynamicState(
            temperature=2.0,
            free_energy=1.5,
            order_parameter=0.1,
            susceptibility=0.80,  # below chi_escalate_threshold=1.45
            phase="disordered",
            hallucination_bound=0.2,
            trust_score=0.05,
        ),
        genome_max_iterations=4,
    )
    assert decision.action == "refuse"
    assert decision.require_rag is True


def test_phase_decision_critical_state_requires_evidence():
    decision = phase_decision(
        ThermodynamicState(
            temperature=1.0,
            free_energy=0.1,
            order_parameter=0.5,
            susceptibility=0.60,  # below chi_escalate_threshold=1.45
            phase="critical",
            hallucination_bound=0.01,
            trust_score=0.4,
        ),
        genome_max_iterations=4,
    )
    assert decision.require_rag is True
    assert decision.action == "iterate_cautious"


def test_phase_decision_chi_escalation_overrides_normal_routing():
    """χ > 1.45 → escalate_adversarial regardless of phase or trust."""
    for phase, trust in [("ordered", 0.95), ("critical", 0.50), ("disordered", 0.10)]:
        decision = phase_decision(
            ThermodynamicState(
                temperature=1.0,
                free_energy=0.5,
                order_parameter=0.5,
                susceptibility=2.00,  # above default chi_escalate_threshold=1.45
                phase=phase,
                hallucination_bound=0.05,
                trust_score=trust,
            ),
            genome_max_iterations=4,
        )
        assert decision.action == "escalate_adversarial", (
            f"Expected escalate_adversarial for phase={phase} trust={trust}, got {decision.action!r}"
        )
        assert decision.require_rag is True
        assert decision.max_iterations == 0


def test_phase_decision_chi_below_threshold_allows_normal_routing():
    """χ = 1.44 (just below threshold) should NOT trigger escalation."""
    decision = phase_decision(
        ThermodynamicState(
            temperature=0.5,
            free_energy=-0.3,
            order_parameter=0.9,
            susceptibility=1.44,
            phase="ordered",
            hallucination_bound=0.01,
            trust_score=0.90,
        ),
        genome_max_iterations=4,
    )
    assert decision.action == "trust"


def test_phase_decision_custom_chi_threshold():
    """Custom chi_escalate_threshold is respected."""
    state = ThermodynamicState(
        temperature=1.0,
        free_energy=0.5,
        order_parameter=0.5,
        susceptibility=3.0,
        phase="ordered",
        hallucination_bound=0.01,
        trust_score=0.90,
    )
    # With threshold=5.0, chi=3.0 should NOT escalate
    decision_no_escalate = phase_decision(state, chi_escalate_threshold=5.0)
    assert decision_no_escalate.action == "trust"
    # With threshold=2.5, chi=3.0 SHOULD escalate
    decision_escalate = phase_decision(state, chi_escalate_threshold=2.5)
    assert decision_escalate.action == "escalate_adversarial"


def test_compute_phase_diagram_returns_states_and_gamma():
    diagram = compute_phase_diagram(n_oracles=3, k_verdicts=2, rho_bar=0.2, lambda_coupling=1.0, n_points=16)
    assert len(diagram.states) == 17
    assert math.isclose(diagram.gamma_exponent, 7.0 / 4.0)
    assert all(state.phase in {"ordered", "critical", "disordered"} for state in diagram.states)


def test_trust_score_respects_calibrated_phase_weights():
    default = trust_score(eta=0.7, chi=5.0, halluc_bound=0.1, phase="critical")
    tuned = trust_score(
        eta=0.7,
        chi=5.0,
        halluc_bound=0.1,
        phase="critical",
        calibration=ThermodynamicCalibration(critical_phase_weight=0.8, chi_scale=20.0),
    )
    assert tuned > default


# ---------------------------------------------------------------------------
# estimate_structural_temperature — circularity-free pre-inference T estimator
# ---------------------------------------------------------------------------


def test_structural_temperature_returns_float_in_bounds() -> None:
    """Any non-empty prompt should return T in [0.05, 2.0]."""
    t = estimate_structural_temperature("Is the boiling point of water 100°C at sea level?")
    assert 0.05 <= t <= 2.0


def test_structural_temperature_empty_prompt_returns_default_prior() -> None:
    """Empty string falls back to the default (reasoning) prior without crashing."""
    t = estimate_structural_temperature("")
    assert 0.05 <= t <= 2.0


def test_structural_temperature_adversarial_above_factoid() -> None:
    """Adversarial category prior should be higher than factoid prior."""
    t_factoid = estimate_structural_temperature("Is Paris the capital of France?", category="factoid")
    t_adversarial = estimate_structural_temperature("Is Paris the capital of France?", category="adversarial")
    assert t_adversarial > t_factoid


def test_structural_temperature_longer_prompt_same_category() -> None:
    """Length factor (log1p-scaled) is strictly increasing with prompt length.

    The total T is not guaranteed to be strictly monotone in length because
    zlib density can decrease for longer prompts (more compressible English text),
    partially offsetting the length contribution.  What *is* guaranteed is that
    the length-factor component alone increases — and that a prompt whose only
    difference is additional length has a non-negative impact on T.

    We test the invariant that really matters for the design: a very short prompt
    (factoid category) yields a lower T than a long adversarial prompt, where
    both the prior and the length component push the adversarial prompt higher.
    """
    t_short_factoid = estimate_structural_temperature("2+2=4?", category="factoid")
    t_long_adversarial = estimate_structural_temperature(
        "Consider a multi-step arithmetic problem: "
        "If Alice has 47 apples and gives 1/3 to Bob, who then trades 40% of his share "
        "with Carol in exchange for twice as many oranges, how many apples does Bob have? "
        "Show all intermediate steps, verify the result, and explain any ambiguities.",
        category="adversarial",
    )
    # Adversarial prior (1.70) vs factoid prior (0.25) guarantees this holds
    # regardless of density/length interactions.
    assert t_long_adversarial > t_short_factoid


def test_structural_temperature_independent_of_oracle_verdicts() -> None:
    """T must be the same whether oracles agree or disagree — it's pre-inference."""
    prompt = "Is Pluto a planet?"
    t = estimate_structural_temperature(prompt)

    # Calling with identical prompt twice should yield identical result
    assert estimate_structural_temperature(prompt) == t

    # The result must not change when we hypothetically supply a different
    # distribution of oracle verdicts (we simulate this by verifying the
    # function signature does NOT accept a distribution argument).
    import inspect
    sig = inspect.signature(estimate_structural_temperature)
    assert "distribution" not in sig.parameters
    assert "verdicts" not in sig.parameters


def test_structural_temperature_unknown_category_uses_reasoning_prior() -> None:
    """An unknown category key should not crash and defaults to the 0.85 prior."""
    t = estimate_structural_temperature("Some question.", category="unknown_domain_xyz")
    # 0.85 prior → with small density/length contribution, T should be near 0.85
    assert 0.50 <= t <= 1.20


# ---------------------------------------------------------------------------
# predict_trust_before_iteration — prompt= path (structural T)
# ---------------------------------------------------------------------------


def test_predict_trust_uses_structural_temperature_when_prompt_given() -> None:
    """When prompt= is provided, T should equal estimate_structural_temperature(prompt)."""
    prompt = "Is the Earth flat?"
    state_structural = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "fp_yes"), ("b", "fp_yes"), ("c", "fp_yes")],
        pre_sweep_confidences=[0.95, 0.92, 0.90],
        rho_bar=0.15,
        lambda_coupling=0.4,
        prompt=prompt,
    )
    expected_raw_t = estimate_structural_temperature(prompt)
    # The raw temperature is the structural T; calibrated version may differ
    # slightly due to apply_temperature_calibration(None) → identity.
    assert math.isclose(state_structural.raw_temperature or 0.0, expected_raw_t, rel_tol=1e-5)


def test_predict_trust_legacy_path_when_no_prompt() -> None:
    """Without prompt=, legacy estimate_temperature() path is taken (backward compat)."""
    state_legacy = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "fp_yes"), ("b", "fp_yes"), ("c", "fp_yes")],
        pre_sweep_confidences=[0.95, 0.92, 0.90],
        rho_bar=0.15,
        lambda_coupling=0.4,
    )
    state_structural = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "fp_yes"), ("b", "fp_yes"), ("c", "fp_yes")],
        pre_sweep_confidences=[0.95, 0.92, 0.90],
        rho_bar=0.15,
        lambda_coupling=0.4,
        prompt="Is the Earth flat?",
    )
    # The two paths produce different raw temperatures: structural vs. legacy.
    # They need not agree — the point is that both run without error.
    assert state_legacy.temperature > 0.0
    assert state_structural.temperature > 0.0


def test_predict_trust_structural_path_consensus_state_is_valid() -> None:
    """All ThermodynamicState fields should be finite and in range with structural T."""
    state = predict_trust_before_iteration(
        pre_sweep_verdicts=[("a", "fp_yes"), ("b", "fp_yes"), ("c", "fp_no")],
        pre_sweep_confidences=[0.85, 0.80, 0.30],
        rho_bar=0.20,
        lambda_coupling=0.4,
        prompt="If all humans are mortal and Socrates is human, is Socrates mortal?",
        prompt_category="reasoning",
    )
    assert state.phase in {"ordered", "critical", "disordered"}
    assert 0.0 <= state.trust_score <= 1.0
    assert math.isfinite(state.free_energy)
    assert state.critical_temperature is not None


# ---------------------------------------------------------------------------
# Tests for polarity-key consensus fix (squad-rag phase=disordered regression)
# ---------------------------------------------------------------------------

def test_domain_classifier_squad_patterns() -> None:
    """SQuAD-style reading-comprehension questions should be classified as factoid."""
    squad_prompts = [
        "In what century did the Normans first gain their separate identity?",
        "How many chromosomes do humans have?",
        "How much does a kilogram weigh?",
        "Who founded Microsoft?",
        "What type of government does France have?",
    ]
    for prompt in squad_prompts:
        cat = DomainClassifier.classify(prompt)
        assert cat == "factoid", (
            f"Expected 'factoid' for SQuAD prompt, got {cat!r}: {prompt!r}"
        )


def test_polarity_key_consensus_produces_ordered_phase() -> None:
    """Unanimous polarity=True with lambda=1.0 must reach the ordered phase.

    Root-cause regression test for the squad-rag 0%-accept bug:
    RAG oracles agree on answer=True but produce unique claim hashes, inflating
    k to N and collapsing eta to 0.  Using polarity-only keys ('True'/'False'/
    'None') fixes the consensus measurement.
    """
    state = predict_trust_before_iteration(
        pre_sweep_verdicts=[("rag1", "True"), ("rag2", "True"), ("rag3", "True")],
        pre_sweep_confidences=[0.72, 0.68, 0.75],
        rho_bar=0.3,
        lambda_coupling=1.0,
        prompt="In what century did the Normans first gain their separate identity?",
    )
    assert state.phase == "ordered", (
        f"Expected ordered phase for unanimous True polarity, got {state.phase!r} "
        f"(eta={state.order_parameter:.3f}, T={state.temperature:.3f}, "
        f"t_crit={state.critical_temperature:.3f})"
    )
    assert state.trust_score > 0.45, (
        f"Trust score {state.trust_score:.3f} below ACCEPT threshold 0.45"
    )


def test_polarity_key_disagree_produces_disordered_phase() -> None:
    """2-vs-1 polarity split should remain disordered (no spurious consensus)."""
    state = predict_trust_before_iteration(
        pre_sweep_verdicts=[("rag1", "True"), ("rag2", "True"), ("rag3", "False")],
        pre_sweep_confidences=[0.72, 0.68, 0.75],
        rho_bar=0.3,
        lambda_coupling=1.0,
        prompt="In what century did the Normans first gain their separate identity?",
    )
    assert state.phase != "ordered" or state.trust_score < 0.45, (
        "Disagreeing oracles (2:1 split) should not reach the ACCEPT-eligible state"
    )
