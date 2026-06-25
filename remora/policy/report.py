from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from remora.policy.observation import PolicyObservation

if TYPE_CHECKING:
    from remora.credal import CredalEnvelope


class DecisionAction(str, Enum):
    ACCEPT = "accept"
    VERIFY = "verify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


class DecisionReason(str, Enum):
    CONFORMAL_ACCEPT = "conformal_accept"
    CONFORMAL_VERIFY = "conformal_verify"
    CONFORMAL_ABSTAIN = "conformal_abstain"
    THERMO_REQUIRE_EVIDENCE = "thermo_require_evidence"
    LOW_TRUST = "low_trust"
    HIGH_CONTRADICTION = "high_contradiction"
    EVIDENCE_SUPPORTED = "evidence_supported"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    EVIDENCE_CONTRADICTED = "evidence_contradicted"
    COUNTERFACTUAL_FAILED = "counterfactual_failed"
    DISTRIBUTION_SHIFT = "distribution_shift"
    TEMPERATURE_ACCEPT = "temperature_accept"
    GAINABILITY_ROUTE = "gainability_route"
    DEFAULT_SAFE_ABSTAIN = "default_safe_abstain"
    TRACE_ATTACHED = "trace_attached"
    ORDERED_HIGH_TRUST = "ordered_high_trust"
    DISORDERED_NO_EVIDENCE = "disordered_no_evidence"
    CRITICAL_PHASE = "critical_phase"
    ADMISSION_FIREWALL_BLOCKED = "admission_firewall_blocked"
    MALFORMED_CALL_BLOCKED = "malformed_call_blocked"
    FORBIDDEN_TOOL_BLOCKED = "forbidden_tool_blocked"
    TAINTED_ARGUMENT_VERIFY = "tainted_argument_verify"
    # Credal risk gates (v0.9)
    MINIMAX_ESCALATE = "minimax_escalate"       # worst_case_loss >= threshold
    TRAP_ESCALATE    = "trap_escalate"          # trap_score >= 0.70
    TRAP_VERIFY      = "trap_verify"            # trap_score in [0.30, 0.70)
    AMBIGUITY_PENALTY = "ambiguity_penalty"     # adjusted_trust used in accept path
    # Misspecification gates (v0.9)
    ENV_MISMATCH_ESCALATE      = "env_mismatch_escalate"      # environment_mismatch_detected
    ENV_CONFIDENCE_VERIFY      = "env_confidence_verify"      # low environment_confidence on prod
    ROLLBACK_UNAVAILABLE       = "rollback_unavailable"       # rollback_available=False + high risk
    STATE_TRANSITION_UNCERTAIN = "state_transition_uncertain" # state_transition_uncertain + high risk
    CRITICAL_ALTERNATIVE       = "critical_alternative"       # critical type in classification_alternatives
    HIGH_RISK_ALTERNATIVE      = "high_risk_alternative"      # high-risk type in classification_alternatives
    LOW_CLASSIFICATION_CONF    = "low_classification_conf"    # classification_confidence < 0.60
    MISSPECIFICATION_VERIFY    = "misspecification_verify"    # model_misspecification_risk > 0.60
    # Coercion hard blocks (v0.9)
    COERCION_BLOCKED             = "coercion_blocked"              # coercion_detected
    BLACKMAIL_BLOCKED            = "blackmail_blocked"             # blackmail_pattern_detected
    # Session sequential risk gates (v0.9)
    SESSION_RISK_VERIFY          = "session_risk_verify"           # session_cumulative_risk > 0.80
    SESSION_FLOOD_VERIFY         = "session_flood_verify"          # session_action_count > 100
    # Policy generalization gates (v0.9)
    FLEET_SYSTEMIC_VERIFY        = "fleet_systemic_verify"         # fleet_level_effect systemic/critical_mass
    POLICY_GENERALIZATION_VERIFY = "policy_generalization_verify"  # policy_generalization_risk > 0.70
    SIMILAR_ACTION_FLOOD_VERIFY  = "similar_action_flood_verify"   # similar_action_seen_count > 50
    # Fail-closed normalization (PR 1)
    UNKNOWN_RISK_TIER_VERIFY     = "unknown_risk_tier_verify"       # risk_tier absent, unknown, or unrecognised
    # None-is-unknown-not-safe (PR 2)
    SCHEMA_UNVERIFIED_VERIFY      = "schema_unverified_verify"      # schema_valid=None + mutating action
    COUNTERFACTUAL_UNKNOWN_VERIFY = "counterfactual_unknown_verify" # counterfactual=None + high/critical evidence path


@dataclass(frozen=True)
class DecisionReport:
    action: DecisionAction
    reasons: tuple[DecisionReason, ...]
    risk_estimate: float | None
    confidence: float | None
    coverage_policy: str
    evidence_required: bool
    human_review_required: bool
    audit_root: str | None
    explanation: str
    raw_observation: PolicyObservation
    source_of_decision: str = "default"
    policy_version: str = "RemoraDecisionEngine-v3"
    in_sample_calibration_warning: str | None = None
    # True when the OPA daemon was unreachable and the Python engine was used
    # as fallback.  Consumers should surface this in audit records.
    fallback_used: bool = False
    # Credal risk envelope — interval-valued harm/utility estimate.
    # Attached to every report produced by RemoraDecisionEngine.decide().
    credal: CredalEnvelope | None = None
