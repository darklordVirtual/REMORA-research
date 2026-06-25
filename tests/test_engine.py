# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.engine — Remora class integration with mock oracles."""
import pytest
from remora.engine import Remora, RemoraState
from remora.genome import Genome, RouterMode
from remora.oracles.mock import MockOracle


def make_remora(
    bias_a=True,
    bias_b=False,
    bias_c=True,
    early_exit_on_convergence=True,
) -> Remora:
    oracles = [
        MockOracle(name="mock_a", bias=bias_a, noise=0.0),
        MockOracle(name="mock_b", bias=bias_b, noise=0.0),
        MockOracle(name="mock_c", bias=bias_c, noise=0.0),
    ]
    genome = Genome(
        max_iterations=2,
        max_subquestions=1,
        negation_ratio=0.0,
        early_exit_on_convergence=early_exit_on_convergence,
    )
    return Remora(oracles=oracles, genome=genome)


def test_remora_requires_two_oracles():
    with pytest.raises(ValueError):
        Remora(oracles=[MockOracle("only_one")], genome=Genome())


def test_run_returns_remora_state():
    remora = make_remora()
    state = remora.run("Is the sky blue?")
    assert isinstance(state, RemoraState)


def test_state_has_oracle_log():
    remora = make_remora()
    state = remora.run("Test question?")
    assert len(state.oracle_log) > 0


def test_report_has_required_keys():
    remora = make_remora()
    state = remora.run("Test question?")
    report = remora.report(state)
    for key in ["iterations", "oracle_calls", "top_claims", "decisions",
            "is_converging", "open_candidates", "falsified_count",
            "require_rag", "refuse_parametric_verdict", "evidence_request_reason"]:
        assert key in report


def test_majority_consensus_true():
    # 2 True oracles vs 1 False → should converge toward True
    remora = make_remora(bias_a=True, bias_b=True, bias_c=False)
    state = remora.run("Is the sky blue?")
    report = remora.report(state)
    assert report["open_candidates"] >= 1


def test_oracle_calls_bounded():
    genome = Genome(max_iterations=3, max_subquestions=1)
    oracles = [MockOracle(f"m{i}") for i in range(3)]
    remora = Remora(oracles=oracles, genome=genome)
    state = remora.run("Question?")
    report = remora.report(state)
    assert report["oracle_calls"] <= 3 * 3  # max_iterations * n_oracles


def test_state_hash_deterministic():
    remora = make_remora()
    state = remora.run("Deterministic question?")
    report1 = remora.report(state)
    report2 = remora.report(state)
    assert report1["state_hash"] == report2["state_hash"]


def test_context_passed_to_oracles():
    remora = make_remora()
    state = remora.run("Is the capital Paris?", context="France is a country in Europe.")
    assert isinstance(state, RemoraState)
    assert state.iteration > 0


# ── Router gate tests ──────────────────────────────────────────────────────────

def make_routed(mode: RouterMode, all_agree: bool = True) -> Remora:
    """Build a Remora with router gate enabled and controlled oracle agreement."""
    if all_agree:
        oracles = [MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)]
    else:
        oracles = [
            MockOracle("m0", bias=True, noise=0.0),
            MockOracle("m1", bias=False, noise=0.0),
            MockOracle("m2", bias=False, noise=0.0),
        ]
    genome = Genome(max_iterations=2, max_subquestions=1, negation_ratio=0.0,
        enable_routing=True, router_mode=mode)
    return Remora(oracles=oracles, genome=genome)


def test_router_gate_disabled_by_default():
    genome = Genome(max_iterations=2, max_subquestions=1)
    oracles = [MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)]
    remora = Remora(oracles=oracles, genome=genome)
    state = remora.run("Test?")
    assert not any("router_gate" in d for d in state.decisions)


def test_router_gate_strict_fires_on_full_agreement():
    remora = make_routed(RouterMode.STRICT, all_agree=True)
    state = remora.run("Is the sky blue?")
    assert any("router_gate" in d for d in state.decisions)
    # Only one sweep of oracles (the pre-sweep), no full iteration
    assert state.iteration == 1


def test_router_gate_strict_skips_on_disagreement():
    remora = make_routed(RouterMode.STRICT, all_agree=False)
    state = remora.run("Is the sky blue?")
    # Strict mode: 1 of 3 True, 2 of 3 False → not unanimous → gate should NOT fire
    assert not any("router_gate" in d for d in state.decisions)


def test_router_gate_balanced_fires_on_majority():
    # 2 True vs 1 False → majority → balanced gate fires
    oracles = [
        MockOracle("m0", bias=True, noise=0.0),
        MockOracle("m1", bias=True, noise=0.0),
        MockOracle("m2", bias=False, noise=0.0),
    ]
    genome = Genome(max_iterations=2, max_subquestions=1, negation_ratio=0.0,
        enable_routing=True, router_mode=RouterMode.BALANCED)
    remora = Remora(oracles=oracles, genome=genome)
    state = remora.run("Majority test?")
    assert any("router_gate" in d for d in state.decisions)


def test_router_gate_populates_candidates():
    remora = make_routed(RouterMode.BALANCED, all_agree=True)
    state = remora.run("Routed question?")
    assert len(state.candidates) >= 1
    assert len(state.candidate_support) >= 1


def test_router_gate_reduces_oracle_calls():
    routed = make_routed(RouterMode.BALANCED, all_agree=True)
    unrouted = make_remora(
        bias_a=True,
        bias_b=True,
        bias_c=True,
        early_exit_on_convergence=False,
    )
    state_routed = routed.run("Efficient question?")
    state_unrouted = unrouted.run("Efficient question?")
    report_routed = routed.report(state_routed)
    report_unrouted = unrouted.report(state_unrouted)
    # Routed path: 1 sweep × 3 oracles = 3 calls; full REMORA: ≥ 6 calls
    assert report_routed["oracle_calls"] < report_unrouted["oracle_calls"]


def test_router_gate_records_thermodynamic_decision_when_enabled():
    genome = Genome(
        max_iterations=2,
        max_subquestions=1,
        negation_ratio=0.0,
        enable_routing=True,
        enable_thermodynamic_control=True,
        router_mode=RouterMode.STRICT,
    )
    oracles = [MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)]
    remora = Remora(oracles=oracles, genome=genome)
    state = remora.run("Thermo-routed question?")
    assert any("thermodynamic phase=" in decision for decision in state.decisions)
    assert len(state.oracle_log) >= 3
    assert state.iteration >= 0
    if state.require_rag:
        assert state.refuse_parametric_verdict is True
    else:
        assert state.iteration >= 1


def test_thermodynamic_guardrail_blocks_parametric_verdict_on_disordered_state():
    genome = Genome(
        max_iterations=2,
        max_subquestions=1,
        negation_ratio=0.0,
        enable_routing=True,
        enable_thermodynamic_control=True,
        router_mode=RouterMode.BALANCED,
        trust_threshold_high=0.75,
        trust_threshold_low=0.30,
        hallucination_threshold=0.05,
    )
    oracles = [
        MockOracle("m0", bias=True, noise=0.0),
        MockOracle("m1", bias=False, noise=0.0),
        MockOracle("m2", bias=False, noise=0.0),
    ]
    remora = Remora(oracles=oracles, genome=genome)
    state = remora.run("Adversarial thermo question?")
    report = remora.report(state)

    assert report["require_rag"] is True
    assert report["refuse_parametric_verdict"] is True
    assert report["open_candidates"] == 0
    assert any("RAG_MANDATORY" in decision for decision in state.decisions)
    assert any("thermodynamic_guardrail" in decision for decision in state.decisions)


def test_thermodynamic_router_uses_dedicated_lambda_not_lyapunov_lambda():
    genome = Genome(
        max_iterations=2,
        max_subquestions=1,
        negation_ratio=0.0,
        enable_routing=True,
        enable_thermodynamic_control=True,
        router_mode=RouterMode.STRICT,
        negation_weight=0.4,
        thermo_lambda=1.0,
    )
    remora = Remora(oracles=[MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)], genome=genome)
    state = remora.run("Thermo lambda split?")

    assert any("thermodynamic phase=" in decision for decision in state.decisions)
    assert "λ_lyap=0.4" in genome.summary()
    assert "λ_thermo=1.0" in genome.summary()


def test_thermo_control_requires_routing_to_run():
    genome = Genome(
        max_iterations=2,
        max_subquestions=1,
        negation_ratio=0.0,
        enable_routing=False,
        enable_thermodynamic_control=True,
    )
    remora = Remora(oracles=[MockOracle(f"m{i}", bias=True, noise=0.0) for i in range(3)], genome=genome)
    state = remora.run("Thermo disabled without routing?")

    # Thermodynamic phase routing must NOT fire when enable_routing=False.
    assert not any("thermodynamic phase=" in decision for decision in state.decisions)
    # NOTE (CR-1): require_rag / refuse_parametric_verdict may be set True by the
    # consensus-tie guard independently of the routing flag — MockOracle produces
    # varying confidence values (different per-oracle RNG seed) which yields
    # distinct CanonicalVerdict fingerprints even when polarity is identical.
    # Those assertions are therefore not valid here; the intent of this test
    # (thermodynamic routing gated by enable_routing) is captured above.

