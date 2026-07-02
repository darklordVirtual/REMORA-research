"""Tests for remora.causal — policy-only counterfactual explanation module.

All tests are bounded to the policy model (decision_scope="policy_only").
No test asserts real-world safety properties.

Domain: network_change_management_v1
Baseline scenario: production network change without any operational approvals.
"""
import pytest

from remora.causal import (
    CounterfactualReplay,
    PolicyIntervention,
    generate_explanation,
    validate_intervention,
)
from remora.causal.domains import load_domain
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> RemoraDecisionEngine:
    return RemoraDecisionEngine()


@pytest.fixture
def model():
    return load_domain("network_change_management_v1")


@pytest.fixture
def escalate_obs() -> PolicyObservation:
    """Network change blocked by ROLLBACK_UNAVAILABLE → ESCALATE.

    argument_tainted=False ensures the taint gate (VERIFY) does not fire first
    and obscure the rollback gate (ESCALATE).  This fixture is the reference for
    testing that interventions can improve an ESCALATE to VERIFY.
    """
    return PolicyObservation(
        question="Deploy BGP route change to core router in prod",
        risk_tier="critical",
        action_type="network_change",
        target_environment="prod",
        rollback_available=False,
        argument_tainted=False,
        evidence_action=None,
        state_transition_uncertain=False,
        counterfactual_passed=None,
        schema_valid=True,
    )


@pytest.fixture
def tainted_obs() -> PolicyObservation:
    """Network change blocked by TAINTED_ARGUMENT_VERIFY → VERIFY.

    argument_tainted=True models unverified source provenance.
    Used to test that source_provenance_verified clears this blocker.
    """
    return PolicyObservation(
        question="Deploy BGP route change to core router in prod",
        risk_tier="high",
        action_type="network_change",
        target_environment="prod",
        rollback_available=True,
        argument_tainted=True,
        evidence_action=None,
        state_transition_uncertain=False,
        counterfactual_passed=None,
        schema_valid=True,
    )


# ---------------------------------------------------------------------------
# 1. Non-actionable variables cannot be intervened
# ---------------------------------------------------------------------------

def test_cannot_intervene_nonactionable_asset_criticality(model):
    """asset_criticality is observed (actionable=False); must reject intervention."""
    iv = PolicyIntervention(variable="asset_criticality", value=True)
    with pytest.raises(ValueError, match="not actionable"):
        validate_intervention(iv, model)


def test_cannot_intervene_nonactionable_blast_radius(model):
    """blast_radius is observed (actionable=False); must reject intervention."""
    iv = PolicyIntervention(variable="blast_radius", value=True)
    with pytest.raises(ValueError, match="not actionable"):
        validate_intervention(iv, model)


def test_cannot_intervene_undefined_variable(model):
    """trust_score and risk_tier are not in the domain model at all."""
    for name in ("trust_score", "entropy", "risk_tier"):
        iv = PolicyIntervention(variable=name, value=True)
        with pytest.raises(ValueError, match="not defined in model"):
            validate_intervention(iv, model)


# ---------------------------------------------------------------------------
# 2. approved_change_window + dual_control + rollback → ESCALATE becomes VERIFY
# ---------------------------------------------------------------------------

def test_three_interventions_change_escalate_to_verify(engine, model, escalate_obs):
    """Applying change_window + dual_control + rollback must change ESCALATE to VERIFY.

    VERIFY (not ACCEPT) because argument_tainted is still True (source provenance
    not verified).  This is the reference example from the spec.
    """
    replay = CounterfactualReplay(engine, model)
    result = replay.replay(
        escalate_obs,
        interventions=[
            PolicyIntervention("approved_change_window", True),
            PolicyIntervention("dual_control_verified", True),
            PolicyIntervention("rollback_plan_verified", True),
        ],
    )
    assert result.factual_verdict == DecisionAction.ESCALATE.value
    assert result.counterfactual_verdict == DecisionAction.VERIFY.value


def test_three_interventions_changed_concepts(engine, model, escalate_obs):
    """changed_concepts must list exactly the three intervened concepts."""
    replay = CounterfactualReplay(engine, model)
    result = replay.replay(
        escalate_obs,
        interventions=[
            PolicyIntervention("approved_change_window", True),
            PolicyIntervention("dual_control_verified", True),
            PolicyIntervention("rollback_plan_verified", True),
        ],
    )
    assert set(result.changed_concepts) == {
        "approved_change_window",
        "dual_control_verified",
        "rollback_plan_verified",
    }


# ---------------------------------------------------------------------------
# 3. source_provenance_verified clears the argument_tainted blocker
# ---------------------------------------------------------------------------

def test_tainted_obs_produces_verify(engine, tainted_obs):
    """Baseline with argument_tainted=True must produce VERIFY (taint gate)."""
    report = engine.decide(tainted_obs)
    assert report.action == DecisionAction.VERIFY


def test_missing_provenance_blocks_better_outcome(engine, model, tainted_obs):
    """Without source_provenance_verified, VERIFY persists even after other interventions."""
    replay = CounterfactualReplay(engine, model)
    result = replay.replay(
        tainted_obs,
        interventions=[
            PolicyIntervention("approved_change_window", True),
            PolicyIntervention("rollback_plan_verified", True),
        ],
    )
    # argument_tainted is not cleared → still VERIFY (or lower)
    assert result.counterfactual_verdict != DecisionAction.ACCEPT.value


def test_remaining_blockers_mention_provenance_for_tainted_obs(engine, model, tainted_obs):
    """remaining_blockers after partial interventions must surface the provenance issue."""
    replay = CounterfactualReplay(engine, model)
    result = replay.replay(
        tainted_obs,
        interventions=[
            PolicyIntervention("approved_change_window", True),
            PolicyIntervention("rollback_plan_verified", True),
        ],
    )
    assert result.remaining_blockers, "Expected at least one remaining blocker"
    combined = " ".join(result.remaining_blockers).lower()
    assert any(
        kw in combined
        for kw in ("provenance", "untrusted", "tainted", "argument")
    ), f"Expected provenance-related blocker, got: {result.remaining_blockers}"


def test_three_interventions_remaining_blockers_non_empty(engine, model, escalate_obs):
    """After three interventions on escalate_obs, remaining_blockers must be non-empty
    (the counterfactual reaches VERIFY, not ACCEPT)."""
    replay = CounterfactualReplay(engine, model)
    result = replay.replay(
        escalate_obs,
        interventions=[
            PolicyIntervention("approved_change_window", True),
            PolicyIntervention("dual_control_verified", True),
            PolicyIntervention("rollback_plan_verified", True),
        ],
    )
    assert result.counterfactual_verdict != DecisionAction.ACCEPT.value
    assert result.remaining_blockers, "Expected remaining blockers when not ACCEPT"


# ---------------------------------------------------------------------------
# 4. Counterfactual replay is deterministic
# ---------------------------------------------------------------------------

def test_replay_is_deterministic(engine, model, tainted_obs):
    """Same inputs must always produce the same counterfactual result."""
    interventions = [
        PolicyIntervention("approved_change_window", True),
        PolicyIntervention("rollback_plan_verified", True),
    ]
    replay = CounterfactualReplay(engine, model)
    r1 = replay.replay(tainted_obs, interventions)
    r2 = replay.replay(tainted_obs, interventions)

    assert r1.factual_verdict == r2.factual_verdict
    assert r1.counterfactual_verdict == r2.counterfactual_verdict
    assert r1.remaining_blockers == r2.remaining_blockers
    assert r1.is_deterministic is True


# ---------------------------------------------------------------------------
# 5. Explanation is faithful to the actual policy result
# ---------------------------------------------------------------------------

def test_explanation_faithful_to_factual_verdict(engine, model, escalate_obs):
    """original_verdict in the explanation must match engine.decide() directly."""
    direct_report = engine.decide(escalate_obs)
    explanation = generate_explanation(escalate_obs, engine, model)

    assert explanation.original_verdict == direct_report.action.value


def test_explanation_faithfulness_with_interventions(engine, model, tainted_obs):
    """counterfactual_verdict must match the replay engine.decide() directly."""
    interventions = [
        PolicyIntervention("source_provenance_verified", True),
        PolicyIntervention("approved_change_window", True),
    ]
    explanation = generate_explanation(tainted_obs, engine, model, interventions=interventions)

    # Apply same interventions manually and compare
    import dataclasses
    overrides = {}
    for iv in interventions:
        var = model.get_variable(iv.variable)
        if var and iv.value:
            overrides.update(var.signal_mapping)
    cf_obs = dataclasses.replace(tainted_obs, **overrides)
    direct_cf_report = engine.decide(cf_obs)

    assert explanation.counterfactual_verdict == direct_cf_report.action.value


# ---------------------------------------------------------------------------
# 6. causal_explanation must not assert real-world safety
# ---------------------------------------------------------------------------

def test_decision_scope_is_policy_only(engine, model, escalate_obs):
    """decision_scope must always be 'policy_only'."""
    explanation = generate_explanation(escalate_obs, engine, model)
    assert explanation.decision_scope == "policy_only"


def test_non_claims_present_and_non_empty(engine, model, escalate_obs):
    """non_claims must be present and non-empty in every explanation."""
    explanation = generate_explanation(escalate_obs, engine, model)
    assert explanation.non_claims, "non_claims must not be empty"
    assert isinstance(explanation.non_claims, list)


def test_non_claims_do_not_assert_real_world_safety(engine, model, escalate_obs):
    """non_claims must explicitly disclaim real-world causal effect."""
    explanation = generate_explanation(escalate_obs, engine, model)
    combined = " ".join(explanation.non_claims).lower()
    assert "real-world causal effect" in combined or "real-world" in combined, (
        "non_claims must disclaim real-world causal effect"
    )
    for forbidden in ("formal guarantee", "proven safe", "causally safe"):
        assert forbidden not in combined, (
            f"non_claims must not contain forbidden phrase: '{forbidden}'"
        )


# ---------------------------------------------------------------------------
# 7. All explanations have non_claims (regardless of interventions)
# ---------------------------------------------------------------------------

def test_non_claims_present_without_interventions(engine, model, escalate_obs):
    """non_claims must be present even when no interventions are provided."""
    explanation = generate_explanation(escalate_obs, engine, model)
    assert len(explanation.non_claims) >= 3


def test_non_claims_present_with_interventions(engine, model, escalate_obs):
    """non_claims must be present when interventions are provided."""
    explanation = generate_explanation(
        escalate_obs,
        engine,
        model,
        interventions=[PolicyIntervention("rollback_plan_verified", True)],
    )
    assert len(explanation.non_claims) >= 3


# ---------------------------------------------------------------------------
# 8. Domain model consistency checks
# ---------------------------------------------------------------------------

def test_domain_loads_without_error(model):
    """network_change_management_v1 must load without errors."""
    assert model.model_id == "network_change_management_v1"
    assert len(model.variables) > 0
    assert len(model.assumptions) > 0


def test_domain_has_required_concepts(model):
    """Required concepts must be present and actionable."""
    required = {
        "approved_change_window",
        "dual_control_verified",
        "rollback_plan_verified",
        "source_provenance_verified",
    }
    present = {v.name for v in model.variables}
    assert required <= present, f"Missing concepts: {required - present}"
    for name in required:
        var = model.get_variable(name)
        assert var.actionable, f"Concept '{name}' must be actionable"


def test_nonactionable_variables_have_empty_signal_mapping(model):
    """Non-actionable variables must not have signal_mappings."""
    for v in model.variables:
        if not v.actionable:
            assert not v.signal_mapping, (
                f"Non-actionable variable '{v.name}' must have empty signal_mapping"
            )


# ---------------------------------------------------------------------------
# 9. DecisionEnvelope causal_explanation field
# ---------------------------------------------------------------------------

def test_envelope_causal_explanation_defaults_to_none():
    """DecisionEnvelope.causal_explanation must default to None."""
    from remora.governance.envelope import (
        AssessmentBlock,
        DecisionEnvelope,
        GateBlock,
        RequestBlock,
    )
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="test-1",
            domain="network",
            risk_tier="critical",
            proposed_action="route change",
            action_type="network_change",
            target_environment="prod",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[],
            thermodynamic={},
            evidence_quality={},
            policy_triggers=[],
        ),
        gate=GateBlock(outcome="escalate"),
    )
    assert env.causal_explanation is None
