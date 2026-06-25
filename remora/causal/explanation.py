"""Structured causal explanation for REMORA policy decisions.

Generates CausalExplanation objects that describe why a policy decision
was made and what actionable changes would produce a different outcome.

Language requirements (from CLAUDE.md / Bjøru 2026):
- Use "policy-modelled counterfactual", not "formal causal proof"
- Use "actionable policy requirement", not "fix"
- Use "bounded by documented assumptions"
- Never use "formal guarantee", "proven safe", "real-world causal proof"
  or "causally safe" — these overstate the scope of policy-only analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from remora.causal.intervention import PolicyIntervention
from remora.causal.schema import CausalDecisionModel
from remora.policy.observation import PolicyObservation

if TYPE_CHECKING:
    from remora.causal.counterfactual import CounterfactualResult
    from remora.policy.decision_engine import RemoraDecisionEngine


# ---------------------------------------------------------------------------
# Human-readable labels for DecisionReason values
# ---------------------------------------------------------------------------

_REASON_TO_LABEL: dict[str, str] = {
    "rollback_unavailable":      "No verified rollback plan for high/critical-risk action",
    "tainted_argument_verify":   "Action arguments derive from untrusted source (provenance unverified)",
    "admission_firewall_blocked": "Adversarial content detected in action request",
    "malformed_call_blocked":    "Tool call is malformed (fails schema validation)",
    "forbidden_tool_blocked":    "Proposed tool is on the task's forbidden list",
    "coercion_blocked":          "Coercion pattern detected in request",
    "blackmail_blocked":         "Blackmail pattern detected in request",
    "state_transition_uncertain": "Uncertain state transition on high/critical-risk action",
    "evidence_insufficient":     "Evidence is insufficient for this risk tier",
    "critical_phase":            "Decision is in critical consensus phase",
    "evidence_contradicted":     "Evidence contradicts the proposed action",
    "counterfactual_failed":     "Counterfactual safety check failed",
    "distribution_shift":        "Distribution shift detected (action is out-of-distribution)",
    "env_mismatch_escalate":     "Target environment mismatch detected",
    "minimax_escalate":          "Worst-case risk estimate exceeds policy threshold",
    "trap_escalate":             "High-impact irreversible pattern detected (trap gate)",
    "trap_verify":               "Moderate-impact irreversible pattern detected (trap gate)",
    "schema_unverified_verify":  "Schema validation was not run for this mutating action",
    "counterfactual_unknown_verify": "Counterfactual check was not run for high/critical evidence path",
    "low_trust":                 "Trust score below ABSTAIN threshold",
    "disordered_no_evidence":    "Disordered phase with no evidence support",
    "default_safe_abstain":      "No accept path matched; conservative default is ABSTAIN",
    "evidence_supported":        "Evidence supports action (context: why ACCEPT was not reached)",
}

# Maps DecisionReason values to the PolicyObservation field(s) that trigger them.
# Used to identify which concepts address which blockers.
_REASON_TO_OBS_FIELDS: dict[str, list[str]] = {
    "rollback_unavailable":      ["rollback_available"],
    "tainted_argument_verify":   ["argument_tainted"],
    "admission_firewall_blocked": ["adversarial_detected"],
    "malformed_call_blocked":    ["schema_valid"],
    "forbidden_tool_blocked":    ["tool_forbidden"],
    "coercion_blocked":          ["coercion_detected"],
    "blackmail_blocked":         ["blackmail_pattern_detected"],
    "state_transition_uncertain": ["state_transition_uncertain"],
    "evidence_insufficient":     ["evidence_action", "risk_tier"],
    "critical_phase":            ["phase"],
    "evidence_contradicted":     ["evidence_contradictions"],
    "counterfactual_failed":     ["counterfactual_passed"],
    "distribution_shift":        ["distribution_shift_detected"],
    "env_mismatch_escalate":     ["environment_mismatch_detected"],
}

# What every CausalExplanation must disclaim.
_DEFAULT_NON_CLAIMS: list[str] = [
    "This explanation does not establish real-world causal effect.",
    "Policy-modelled counterfactuals do not predict safety outcomes in the world.",
    "These findings are bounded by documented assumptions and the policy model scope (decision_scope='policy_only').",
    "Changing policy inputs does not guarantee the corresponding real-world conditions have been met.",
    "This analysis does not constitute a formal causal proof or safety guarantee.",
]


# ---------------------------------------------------------------------------
# CausalExplanation dataclass
# ---------------------------------------------------------------------------

@dataclass
class CausalExplanation:
    """Structured causal explanation for a REMORA policy decision.

    All explanations are bounded to the policy model (decision_scope="policy_only").
    The non_claims field must be inspected before citing any finding externally.

    Parameters
    ----------
    decision_scope:
        Always "policy_only".  The explanation covers the policy decision
        model only, not real-world causal effects.
    policy_model_id:
        Model ID of the CausalDecisionModel used.
    policy_model_version:
        Version of the CausalDecisionModel.
    policy_version:
        Version string from RemoraDecisionEngine.
    direct_policy_causes:
        Human-readable labels of DecisionReasons that produced the factual verdict.
    actionable_requirements:
        Operational conditions that, if established, would remove one or more
        of the direct policy causes.  Expressed in operational vocabulary.
    non_actionable_context:
        Observed signals that influenced the decision but cannot be changed
        directly (e.g., asset_criticality, blast_radius, target_environment).
    counterfactual_paths:
        Results of counterfactual replays.  Each entry shows what the policy
        engine would decide under a specific set of interventions.
    remaining_blockers:
        Policy reasons that still fire after the most recent counterfactual
        interventions were applied.  Empty iff the counterfactual reached ACCEPT.
    assumptions:
        Explicit assumptions from the CausalDecisionModel.  Bounds the
        validity of this explanation.
    non_claims:
        What this explanation explicitly does NOT claim.  Must be present.
    interventions_tried:
        The PolicyInterventions used in the counterfactual replay, if any.
    original_verdict:
        The factual policy verdict.
    counterfactual_verdict:
        The policy verdict after interventions, or None if no replay was run.
    """
    decision_scope: str                           # always "policy_only"
    policy_model_id: str
    policy_model_version: str
    policy_version: str
    direct_policy_causes: list[str]
    actionable_requirements: list[str]
    non_actionable_context: list[str]
    counterfactual_paths: list[Any]               # list[CounterfactualResult]
    remaining_blockers: list[str]
    assumptions: list[str]
    non_claims: list[str]
    interventions_tried: list[PolicyIntervention]
    original_verdict: str
    counterfactual_verdict: str | None = None


# ---------------------------------------------------------------------------
# Explanation generator
# ---------------------------------------------------------------------------

def generate_explanation(
    obs: PolicyObservation,
    engine: "RemoraDecisionEngine",
    model: CausalDecisionModel,
    interventions: list[PolicyIntervention] | None = None,
) -> CausalExplanation:
    """Generate a structured causal explanation for a policy decision.

    Parameters
    ----------
    obs:
        The PolicyObservation for which to generate an explanation.
    engine:
        The RemoraDecisionEngine to use for factual and counterfactual decisions.
    model:
        The CausalDecisionModel defining concepts and their policy mappings.
    interventions:
        Optional list of PolicyInterventions to run as a counterfactual.
        If provided, a counterfactual replay is run and added to
        counterfactual_paths.  All must target actionable variables.

    Returns
    -------
    CausalExplanation with:
    - direct_policy_causes: reasons that triggered in the factual case
    - actionable_requirements: concepts that would remove those reasons
    - counterfactual_paths: replay result (if interventions provided)
    - non_claims: standard disclaimer list (always present)
    """
    from remora.causal.counterfactual import CounterfactualReplay

    factual_report = engine.decide(obs)
    factual_reasons = [r.value for r in factual_report.reasons]

    # Direct policy causes → human-readable labels
    direct_causes = [_REASON_TO_LABEL.get(r, r) for r in factual_reasons]

    # Identify which actionable concepts address which blocking reasons
    actionable_requirements: list[str] = []
    seen_concepts: set[str] = set()
    for reason in factual_reasons:
        blocking_fields = _REASON_TO_OBS_FIELDS.get(reason, [])
        for concept in model.actionable_variables():
            if concept.name in seen_concepts:
                continue
            if any(f in concept.signal_mapping for f in blocking_fields):
                reason_label = _REASON_TO_LABEL.get(reason, reason)
                actionable_requirements.append(
                    f"{concept.label}: addresses '{reason_label}'"
                )
                seen_concepts.add(concept.name)

    # Non-actionable context
    non_actionable_context = [
        f"{v.label} (provenance: {v.provenance.value})"
        for v in model.variables
        if not v.actionable and v.type.value in ("observed", "outcome")
    ]

    # Counterfactual replay
    counterfactual_paths: list[Any] = []
    counterfactual_verdict: str | None = None
    remaining_blockers: list[str] = []

    if interventions:
        replay = CounterfactualReplay(engine, model)
        cf_result = replay.replay(obs, interventions)
        counterfactual_paths.append(cf_result)
        counterfactual_verdict = cf_result.counterfactual_verdict
        remaining_blockers = cf_result.remaining_blockers

    return CausalExplanation(
        decision_scope="policy_only",
        policy_model_id=model.model_id,
        policy_model_version=model.version,
        policy_version=factual_report.policy_version,
        direct_policy_causes=direct_causes,
        actionable_requirements=actionable_requirements,
        non_actionable_context=non_actionable_context,
        counterfactual_paths=counterfactual_paths,
        remaining_blockers=remaining_blockers,
        assumptions=list(model.assumptions),
        non_claims=list(_DEFAULT_NON_CLAIMS),
        interventions_tried=list(interventions or []),
        original_verdict=factual_report.action.value,
        counterfactual_verdict=counterfactual_verdict,
    )
