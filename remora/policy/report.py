# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from remora.policy.observation import PolicyObservation

if TYPE_CHECKING:
    from remora.credal import CredalEnvelope


class DecisionAction(str, Enum):
    ACCEPT = "accept"
    VERIFY = "verify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


class DecisionReason(str, Enum):
    # CONFORMAL_VERIFY was removed 2026-08-05: both conformal branches in
    # decide() only ever emit ACCEPT or ABSTAIN, and the member had never
    # been produced, tested, or documented — a reason that cannot occur is
    # contract noise, not coverage.
    CONFORMAL_ACCEPT = "conformal_accept"
    # Issue #35: in the execution profile a probabilistic signal can never
    # directly produce ACCEPT; the would-be ACCEPT routes to VERIFY with
    # this reason so the trace states WHY the profile intervened.
    EXECUTION_PROFILE_PROBABILISTIC_VERIFY = "execution_profile_probabilistic_verify"
    # Semantic-authority floor (NEGATIVE_RESULTS section 34/36 remediation):
    # a proposed tool whose fit to the goal or expected effect is UNKNOWN
    # routes to VERIFY - low consequence is not the same thing as correct
    # purpose, and a cheap read to the wrong tool is still a wrong execution.
    SEMANTIC_AUTHORITY_UNKNOWN_VERIFY = "semantic_authority_unknown_verify"
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
    LOW_CONSEQUENCE_ACCEPT = "low_consequence_accept"
    # A read whose every grounding signal is positively confirmed under a
    # signed intent authority. Strictly stronger than LOW_CONSEQUENCE_ACCEPT,
    # and specifically closes that path's measured cost: it cannot accept a
    # read-only call that is the wrong call for the task, because
    # tool_matches_goal and expected_effect_matches must both be True.
    GROUNDED_READ_ACCEPT = "grounded_read_accept"
    ARGUMENT_RESOLUTION_REQUIRED = "argument_resolution_required"
    NO_RESOLVER_AVAILABLE = "no_resolver_available"
    # An argument policy requires validated is unconfirmed, and a bounded
    # authoritative lookup is expected to settle it.
    ARGUMENT_VALIDATION_REQUIRED = "argument_validation_required"
    # The call's argument values are traceable to nothing in this context —
    # not the task text, not the system of record. A well-formed foreign call
    # (§34) withdraws from autonomy; verification must establish where its
    # values came from.
    UNGROUNDED_ARGUMENT_VALUES_VERIFY = "ungrounded_argument_values_verify"
    # §34 residue: the call is well-formed and its values are grounded, but the
    # declared tool contract contradicts the task's goal — wrong resource, or
    # right resource and wrong effect.
    TOOL_DOES_NOT_MATCH_GOAL = "tool_does_not_match_goal"
    EXPECTED_EFFECT_CONTRADICTED = "expected_effect_contradicted"
    TRACE_ATTACHED = "trace_attached"
    ORDERED_HIGH_TRUST = "ordered_high_trust"
    DISORDERED_NO_EVIDENCE = "disordered_no_evidence"
    CRITICAL_PHASE = "critical_phase"
    ADMISSION_FIREWALL_BLOCKED = "admission_firewall_blocked"
    MALFORMED_CALL_BLOCKED = "malformed_call_blocked"
    FORBIDDEN_TOOL_BLOCKED = "forbidden_tool_blocked"
    TAINTED_ARGUMENT_VERIFY = "tainted_argument_verify"
    # Issue #40 decision (2026-07-30): tainted arguments at CRITICAL risk are
    # never an approvable VERIFY — they escalate (option c; option b,
    # sanitize-and-revalidate before approval, is the tracked target state).
    TAINTED_ARGUMENT_ESCALATE = "tainted_argument_escalate"
    # Untrusted content controls a recipient/command/credential/egress target:
    # authorising, not informing. Escalates at any declared risk tier.
    UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT = "untrusted_controls_sensitive_argument"
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
    # Runtime invariant enforcement (2026-08-20)
    INVARIANT_VIOLATION_ESCALATE = "invariant_violation_escalate"
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
    UNKNOWN_ACTION_TYPE_VERIFY    = "unknown_action_type_verify"    # non-empty, unrecognised action_type (deny-by-default for actuation)
    COUNTERFACTUAL_UNKNOWN_VERIFY = "counterfactual_unknown_verify" # counterfactual=None + high/critical evidence path
    # Oracle quorum gate (PR 3)
    INSUFFICIENT_ORACLE_VOTES     = "insufficient_oracle_votes"     # valid_oracle_count < MIN_REQUIRED_ORACLE_VOTES
    # Tool-set membership gate (open risk B)
    TOOL_NOT_IN_AVAILABLE_SET     = "tool_not_in_available_set"     # proposed tool absent from declared available_tools


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
    # v5 (2026-07-31): the temperature ACCEPT path excludes the critical
    # phase, matching the marginal conformal path.
    # v4 (2026-07-30): tainted-argument floor is tier-dependent — critical
    # risk escalates instead of the approvable VERIFY (issue #40 decision).
    policy_version: str = "RemoraDecisionEngine-v5"
    in_sample_calibration_warning: str | None = None
    # True when the OPA daemon was unreachable and the Python engine was used
    # as fallback.  Consumers should surface this in audit records.
    fallback_used: bool = False
    # Credal risk envelope — interval-valued harm/utility estimate.
    # Attached to every report produced by RemoraDecisionEngine.decide().
    credal: CredalEnvelope | None = None
    # ── Resolution (2026-07-31) ──────────────────────────────────────────
    # A VERIFY produced by the argument-resolution gate always carries a plan
    # naming the bounded machine step expected to close the gap. VERIFY without
    # a plan from that gate is a contract violation, not a softer outcome.
    resolution_plan: Any = None
