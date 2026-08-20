# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA conservative decision engine — maps PolicyObservation → DecisionReport.

Design goals
------------
1. **No false accepts on critical or adversarial inputs** — hard blocks fire first.
2. **Every path is traceable** — ``explain()`` documents the full rule evaluation tree.
3. **Calibrated thresholds** — temperature and conformal paths load from offline
   artifacts so in-sample optimism cannot inflate runtime safety claims.
4. **Machine-verifiable** — combine with ``remora.policy.invariants`` to assert
   safety properties hold on every decision.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace

from remora.credal import (
    MINIMAX_ESCALATE_THRESHOLD,
    CredalEnvelope,
    compute_from_obs,
)
from remora.policy.invariants import InvariantResult, check_all_invariants
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport
from remora.policy.resolution import ResolutionPlan
from remora.policy.trap_classifier import (
    TRAP_ESCALATE_THRESHOLD,
    TRAP_VERIFY_THRESHOLD,
)
from remora.policy.trap_classifier import (
    score as trap_score,
)
# Heuristic decision thresholds moved to remora/policy/thresholds.py
# (2026-07-29). Re-imported into THIS module namespace so the
# _CONDITIONAL_GATES lambdas below (which close over these as engine-module
# globals) and the de.<NAME> references pinned by
# tests/test_policy_threshold_constants.py keep resolving. VALUES are
# unchanged; see thresholds.py for the CALIBRATED-vs-HEURISTIC provenance
# note. Calibrated thresholds stay constructor-injected, never imported here.
from remora.policy.thresholds import (  # noqa: F401  (re-exported for gate closures + tests)
    MIN_REQUIRED_ORACLE_VOTES,
    ORDERED_HIGH_TRUST_MIN,
    EVIDENCE_CONFIDENCE_MIN,
    LOW_TRUST_ABSTAIN_MAX,
    MINIMAX_AMBIGUITY_WIDTH_MIN,
    ENV_CONFIDENCE_MIN,
    CLASSIFICATION_CONFIDENCE_MIN,
    MISSPECIFICATION_RISK_MAX,
    SESSION_CUMULATIVE_RISK_MAX,
    SESSION_ACTION_COUNT_MAX,
    POLICY_GENERALIZATION_RISK_MAX,
    SIMILAR_ACTION_FLOOD_MAX,
)

# Action types that are inherently safe to classify conservatively.
# Misspecification gates skip these to avoid blocking obviously read-only actions.
_READ_ONLY_TYPES: frozenset[str] = frozenset({
    "read", "shell_read", "list", "query", "inspect",
})

# Action types that are explicitly mutating. When risk_tier is unknown/absent,
# these require VERIFY even without explicit risk context. Unknown action_type
# (None / unrecognised string) is NOT in this set — it falls through to existing
# logic rather than being conservatively blocked, to avoid over-blocking tools
# that declare no action_type. Production-environment targeting overrides this.
_MUTATING_TYPES: frozenset[str] = frozenset({
    "write", "shell_write", "delete",
    "permission_change", "config_change",
    "production_write", "destructive_write", "emergency_write", "financial_write",
    "network_change", "prod_deploy", "data_exfiltration", "irreversible_delete",
})

# Non-actuating action types the engine recognizes as safe to route normally
# (question-answering and read-only work). Combined with the mutating and
# read-only sets, this defines the KNOWN action-type vocabulary. A non-empty
# action_type outside this vocabulary is treated as an unknown actuation type
# and floored to VERIFY (external security audit finding: "unknown must mean
# not authorized", not "possibly benign"). action_type=None is the pure QA /
# no-tool-call case and is intentionally NOT floored.
_NON_ACTUATING_TYPES: frozenset[str] = frozenset({
    "qa", "answer", "question", "chat", "classify", "read_only", "noop",
    "unspecified", "none",
})

# Action types that warrant ESCALATE when found as classification alternatives.
_CRITICAL_ALT_TYPES: frozenset[str] = frozenset({
    "destructive_write", "privilege_escalation",
    "data_exfiltration", "irreversible_delete",
    "prod_deploy", "network_change",
})

# Action types that warrant VERIFY when found as classification alternatives.
_HIGH_RISK_ALT_TYPES: frozenset[str] = frozenset({
    "write", "shell_write", "delete",
    "permission_change", "config_change",
})

# Production environment aliases — canonical set used across all env-sensitive gates.
_PROD_ENVS: frozenset[str] = frozenset({"prod", "production", "live"})

# Recognised risk tier values. Any other value (including None, empty, or typo)
# is treated as "unknown" and routes mutating/production actions to VERIFY.
_KNOWN_RISK_TIERS: frozenset[str] = frozenset({"low", "medium", "high", "critical"})


def _normalize_risk_tier(tier: str | None) -> str:
    """Normalise risk_tier to a canonical lowercase value or 'unknown'.

    Case and surrounding whitespace are normalised first, so "CRITICAL" and
    " critical " resolve to the accepted tier "critical". Only genuinely
    unrecognised values (e.g. "high_risk", None, "") become 'unknown', which
    the engine treats conservatively — typos cannot silently bypass safety
    gates by reading as a milder tier.
    """
    if tier is None:
        return "unknown"
    normalised = tier.strip().lower()
    return normalised if normalised in _KNOWN_RISK_TIERS else "unknown"


#: Argument roles through which controlling a value confers authority rather
#: than information: where an action lands, what it runs, and what it
#: authenticates with. Matched as whole tokens against the argument name, so
#: `to`, `to_address` and `recipient_email` all count while `photo` does not.
_SENSITIVE_ARGUMENT_ROLES: frozenset[str] = frozenset({
    "recipient", "recipients", "to", "cc", "bcc", "destination", "dest",
    "target", "address", "email", "account", "iban", "payee",
    "command", "cmd", "script", "exec", "shell", "query_command",
    "credential", "credentials", "password", "secret", "token", "key",
    "apikey", "api_key", "auth", "url", "uri", "endpoint", "webhook",
    "host", "path", "principal", "role", "permission", "rights",
})


def _unresolvable_gap(obs: PolicyObservation) -> bool:
    """True when a required argument is missing and nothing can supply it."""
    return bool(obs.missing_required_arguments) and (
        not obs.argument_resolver_tools or obs.arguments_satisfiable is False
    )


def _controls_sensitive_argument(names: tuple[str, ...] | None) -> bool:
    """True when any named argument occupies a sensitive role."""
    for name in names or ():
        tokens = {tok for tok in str(name).lower().replace("-", "_").split("_") if tok}
        if tokens & _SENSITIVE_ARGUMENT_ROLES:
            return True
    return False


def hard_guard_floor(
    obs: PolicyObservation,
) -> tuple[DecisionAction, DecisionReason] | None:
    """Evaluate the unconditional hard guards, in the engine's priority order.

    This is the single source of truth for the hard-block floor. It is used
    by ``RemoraDecisionEngine.decide()`` as the first evaluation stage, and by
    external policy adapters (e.g. ``remora.policy.opa_adapter``) to enforce
    decision monotonicity: no external policy result may downgrade below the
    action returned here (REM-003 extended to adapters).

    Only guards that depend purely on boolean/count security signals belong
    here — trust routing, credal gates, and risk-tier flooring are engine
    policy and intentionally excluded, so an external PDP can legitimately
    differ in the probabilistic band without violating the floor.

    Returns ``None`` when no hard guard fires.
    """
    if obs.adversarial_detected:
        return DecisionAction.ESCALATE, DecisionReason.ADMISSION_FIREWALL_BLOCKED
    if obs.schema_valid is False:
        return DecisionAction.ESCALATE, DecisionReason.MALFORMED_CALL_BLOCKED
    if obs.tool_forbidden:
        return DecisionAction.ESCALATE, DecisionReason.FORBIDDEN_TOOL_BLOCKED
    if obs.coercion_detected:
        return DecisionAction.ESCALATE, DecisionReason.COERCION_BLOCKED
    if obs.blackmail_pattern_detected:
        return DecisionAction.ESCALATE, DecisionReason.BLACKMAIL_BLOCKED
    if obs.counterfactual_passed is False:
        return DecisionAction.ESCALATE, DecisionReason.COUNTERFACTUAL_FAILED
    if obs.evidence_contradictions is not None and obs.evidence_contradictions > 0:
        action = (
            DecisionAction.ESCALATE
            if (obs.contradiction_cycles or 0) > 0
            else DecisionAction.ABSTAIN
        )
        return action, DecisionReason.EVIDENCE_CONTRADICTED
    if obs.argument_tainted:
        # Untrusted content that *controls* a sensitive argument is
        # authorising, not informing. Deciding where money goes, what command
        # runs, or which credential is used is exactly the authority untrusted
        # content must never hold, so this escalates regardless of the declared
        # risk tier — a caller-supplied "low" must not buy autonomy for an
        # attacker-chosen recipient. §23 recorded ESCALATE recall at 0% before
        # this existed. Untrusted provenance alone stays at the VERIFY floor
        # below: escalating every tainted call would send a summary of an email
        # to a human, which is friction with no decision to make.
        if _controls_sensitive_argument(obs.untrusted_controlled_arguments):
            return (
                DecisionAction.ESCALATE,
                DecisionReason.UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT,
            )
        # Issue #40 decision (2026-07-30): at CRITICAL risk a tainted
        # argument is never an approvable VERIFY — it escalates, so no
        # reviewer can wave through an unsanitized critical write. The
        # target state (option b: sanitize + revalidate before approval is
        # grantable) is tracked in #40; until that machinery exists the
        # floor fails toward ESCALATE for the critical tier.
        if _normalize_risk_tier(obs.risk_tier) == "critical":
            return DecisionAction.ESCALATE, DecisionReason.TAINTED_ARGUMENT_ESCALATE
        return DecisionAction.VERIFY, DecisionReason.TAINTED_ARGUMENT_VERIFY
    return None


#: Action types whose execution is bounded and reversible. Membership is by
#: exact match: an unrecognised or missing action_type is unknown, not read-only,
#: and must never qualify.
_READ_ONLY_ACTION_TYPES: frozenset[str] = frozenset(
    {"read", "read_only", "search", "list", "get", "query", "lookup"}
)


def _is_read_only_action(obs: PolicyObservation) -> bool:
    """True only on a positively declared read-only action type.

    Unknown or unrecognised is not read-only. A goal mismatch on something we
    cannot confirm is harmless must escalate, not abstain.
    """
    return (obs.action_type or "").strip().lower() in _READ_ONLY_ACTION_TYPES


def _is_low_consequence(obs: PolicyObservation) -> bool:
    """True when the action is read-only and carries no negative safety signal.

    Every condition is a *confirmed negative* check written so that ``None``
    (unknown) never satisfies it. The path permits only on positive evidence of
    read-only semantics plus the absence of any recorded concern.
    """
    if (obs.action_type or "").strip().lower() not in _READ_ONLY_ACTION_TYPES:
        return False

    if obs.argument_tainted or obs.tool_forbidden:
        return False
    if obs.adversarial_detected or obs.coercion_detected:
        return False
    if obs.blackmail_pattern_detected or obs.distribution_shift_detected:
        return False
    if obs.schema_valid is False or obs.counterfactual_passed is False:
        return False
    if obs.evidence_contradictions:
        return False

    # A call whose required arguments cannot be sourced is one an agent would
    # have to fabricate arguments for. Bounded consequence does not cover a
    # fabricated call: unit_conversion is pure arithmetic and still wrong when
    # there is no amount to convert. Confirmed-unsatisfiable only — an
    # unregistered tool is unknown and must not be disqualified.
    if obs.arguments_satisfiable is False:
        return False

    # An identifier the system of record does not contain means the call would
    # operate on a record that does not exist. Confirmed-absent only.
    if obs.argument_values_supported is False:
        return False

    # Production is excluded even for reads: blast radius there includes
    # disclosure of live data, which no read-only guarantee covers.
    if (obs.target_environment or "").strip().lower() in {"prod", "production"}:
        return False

    return True


#: Every grounding signal that must be POSITIVELY confirmed before a read can
#: execute without a human. Listed as attribute names so the check below cannot
#: quietly stop covering one of them.
_GROUNDING_SIGNALS: tuple[str, ...] = (
    "tool_matches_goal",
    "expected_effect_matches",
    "argument_values_supported",
    "argument_values_grounded",
)


def _is_grounded_read(obs: PolicyObservation) -> bool:
    """True when a read is confirmed to be *this* task's read, on real data.

    The policy-only execution kernel has no oracle and no trust score, so the
    probabilistic ACCEPT path cannot fire there — every call fell to
    VERIFY/ABSTAIN regardless of how well-founded it was. This is the
    deterministic alternative: not "we estimate this is safe", but "every
    question we can answer from declared data has been answered, positively".

    All of these must hold:

    - ``_is_low_consequence``: positively declared read-only semantics and no
      recorded safety concern (taint, coercion, adversarial detection, invalid
      schema, contradicted evidence, unsatisfiable arguments);
    - ``risk_tier`` is ``low`` — declared by REMORA or by the deployment, and
      folded into the policy bundle hash either way;
    - the target environment is not production, for which no read-only
      guarantee covers the disclosure blast radius;
    - an intent authority resolved server-side: the call is made under a work
      order the deployment recognises, not under text the agent supplied;
    - the four grounding signals are all ``True`` — the tool matches the goal,
      its declared effect matches the requested one, every argument value
      exists in the system of record, and every value traces to this context;
    - nothing required is missing or unvalidated.

    ``None`` never satisfies any clause. Unknown is not grounded.

    What this does NOT assert: that the read returns a correct answer, or that
    reading is free. It asserts that the call is the declared call for a
    declared authority over declared data — which is what makes a human
    approval on it ceremony rather than control.
    """
    if not _is_low_consequence(obs):
        return False
    if _normalize_risk_tier(obs.risk_tier) != "low":
        return False
    # _is_low_consequence already excludes prod/production; "live" is the
    # third alias in the canonical set and must not slip through here.
    if (obs.target_environment or "").strip().lower() in _PROD_ENVS:
        return False
    if obs.intent_authority_present is not True:
        return False
    if any(getattr(obs, signal) is not True for signal in _GROUNDING_SIGNALS):
        return False
    if obs.missing_required_arguments or obs.unvalidated_required_arguments:
        return False
    return True


def _normalize_observation(obs: PolicyObservation) -> PolicyObservation:
    """Return a copy of *obs* with context fields normalised for fail-closed handling.

    - risk_tier: lowercased and validated; unrecognised → 'unknown'
    - action_type / target_environment: lowercased (stripped) for consistent lookups

    The original frozen dataclass is unchanged; a new instance is returned.
    """
    normalised_tier = _normalize_risk_tier(obs.risk_tier)
    normalised_action = (obs.action_type or "").strip().lower() or None
    normalised_env = (obs.target_environment or "").strip().lower() or None
    if (
        normalised_tier == obs.risk_tier
        and normalised_action == obs.action_type
        and normalised_env == obs.target_environment
    ):
        return obs
    return dataclasses.replace(
        obs,
        risk_tier=normalised_tier,
        action_type=normalised_action,
        target_environment=normalised_env,
    )


# ---------------------------------------------------------------------------
# PolicyTrace — structured explanation returned by explain()
# ---------------------------------------------------------------------------

# PolicyTrace / PolicyRuleEvaluation moved to remora/policy/trace.py
# (2026-07-29) and re-exported here so remora/__init__.py and the test suite
# keep importing them from remora.policy.decision_engine unchanged.
from remora.policy.trace import (  # noqa: E402, F401  (re-exported)
    PolicyRuleEvaluation,
    PolicyTrace,
)


# ---------------------------------------------------------------------------
# Conditional-gate inventory (single source of truth for decide + explain)
# ---------------------------------------------------------------------------
#
# The uniform conditional gates that run AFTER the hard-guard floor and BEFORE
# the schema/ACCEPT-tail logic used to be encoded twice: as if/return in
# decide() and as a hand-maintained r(...) mirror in explain(). Adding a gate
# in one place and forgetting the other let the audit trace drift from the
# decision (Grok review P1, 2026-07-25). They now live here once; decide()
# returns on the first gate whose ``evaluate`` yields an action, and explain()
# records every gate. Each ``evaluate`` is self-contained (does not rely on an
# earlier gate having returned), so the same predicate is correct for both the
# first-match decision and the record-all trace.
#
# NOT included here (deliberately kept literal): the hard-guard floor (already
# centralised in hard_guard_floor()), the two-phase schema-unverified handling
# (its reason is appended before the floor return but VERIFY is returned late),
# the unknown-action-type floor, and the ACCEPT/VERIFY/ABSTAIN tail (which has
# ambiguity-penalty side-reasons and engine-config-dependent branches).

from collections.abc import Callable  # noqa: E402


@dataclass(frozen=True)
class _ConditionalGate:
    """One conditional policy gate, shared by decide() and explain().

    evaluate:   returns the DecisionAction to take when the gate fires, else
                None. This is the single source of "does it fire, and to what".
    idle_label: the trace outcome label shown when the gate is NOT triggered
                (a constant for fixed-outcome gates; "NONE" for the dynamic
                production-write gate). When triggered, the label is derived
                from the evaluated action, so the trace output is unchanged.
    describe:   the human-readable condition string for the audit trace.
    """

    name: str
    reason: DecisionReason
    evaluate: Callable[["RemoraDecisionEngine", PolicyObservation, "CredalEnvelope", float], DecisionAction | None]
    idle_label: str
    describe: Callable[[PolicyObservation, "CredalEnvelope", float], str]

    def outcome_label(self, action: DecisionAction | None) -> str:
        return action.value.upper() if action is not None else self.idle_label


_CONDITIONAL_GATES: tuple[_ConditionalGate, ...] = (
    _ConditionalGate(
        "tool_does_not_match_goal", DecisionReason.TOOL_DOES_NOT_MATCH_GOAL,
        lambda e, o, c, t: (
            None if o.tool_matches_goal is not False
            else (DecisionAction.ABSTAIN if _is_read_only_action(o)
                  else DecisionAction.ESCALATE)
        ),
        "ABSTAIN/ESCALATE",
        lambda o, c, t: (
            f"tool_matches_goal={o.tool_matches_goal}, action_type={o.action_type!r}"
        ),
    ),
    _ConditionalGate(
        # Same shape and same severity as tool_does_not_match_goal: a refuted
        # effect is the same class of defect (right form, wrong outcome), so it
        # earns the same response rather than a softer one. Only an established
        # False fires; None changes nothing, which is what keeps an undeclared
        # contract from tightening the route on absence of information.
        "expected_effect_contradicted", DecisionReason.EXPECTED_EFFECT_CONTRADICTED,
        lambda e, o, c, t: (
            None if o.expected_effect_matches is not False
            else (DecisionAction.ABSTAIN if _is_read_only_action(o)
                  else DecisionAction.ESCALATE)
        ),
        "ABSTAIN/ESCALATE",
        lambda o, c, t: (
            f"expected_effect_matches={o.expected_effect_matches}, "
            f"action_type={o.action_type!r}"
        ),
    ),
    _ConditionalGate(
        "refuse_parametric", DecisionReason.THERMO_REQUIRE_EVIDENCE,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.refuse_parametric_verdict and o.evidence_action != "answer") else None,
        "VERIFY",
        lambda o, c, t: f"refuse_parametric={o.refuse_parametric_verdict}, evidence_action={o.evidence_action!r}",
    ),
    _ConditionalGate(
        "distribution_shift", DecisionReason.DISTRIBUTION_SHIFT,
        lambda e, o, c, t: DecisionAction.VERIFY if o.distribution_shift_detected else None,
        "VERIFY",
        lambda o, c, t: f"distribution_shift_detected={o.distribution_shift_detected}",
    ),
    _ConditionalGate(
        "critical_phase_critical_risk", DecisionReason.CRITICAL_PHASE,
        lambda e, o, c, t: DecisionAction.ESCALATE
        if (o.phase == "critical" and o.risk_tier == "critical") else None,
        "ESCALATE",
        lambda o, c, t: f"phase={o.phase!r}, risk_tier={o.risk_tier!r}",
    ),
    _ConditionalGate(
        "rollback_unavailable", DecisionReason.ROLLBACK_UNAVAILABLE,
        lambda e, o, c, t: DecisionAction.ESCALATE
        if (o.rollback_available is False and o.risk_tier in ("high", "critical")) else None,
        "ESCALATE",
        lambda o, c, t: f"rollback_available={o.rollback_available!r}, risk_tier={o.risk_tier!r}",
    ),
    _ConditionalGate(
        "state_transition_uncertain", DecisionReason.STATE_TRANSITION_UNCERTAIN,
        lambda e, o, c, t: DecisionAction.ESCALATE
        if (o.state_transition_uncertain and o.risk_tier in ("high", "critical")) else None,
        "ESCALATE",
        lambda o, c, t: f"state_transition_uncertain={o.state_transition_uncertain}, risk_tier={o.risk_tier!r}",
    ),
    _ConditionalGate(
        "production_write_high_or_critical", DecisionReason.EVIDENCE_INSUFFICIENT,
        lambda e, o, c, t: e._production_write_outcome(o),
        "NONE",
        lambda o, c, t: (
            f"action_type={o.action_type!r}, "
            f"target_environment={o.target_environment!r}, "
            f"risk_tier={o.risk_tier!r}"
        ),
    ),
    _ConditionalGate(
        "high_risk_no_evidence", DecisionReason.EVIDENCE_INSUFFICIENT,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.risk_tier in ("high", "critical") and o.evidence_action is None) else None,
        "VERIFY",
        lambda o, c, t: f"risk_tier={o.risk_tier!r}, evidence_action=None",
    ),
    _ConditionalGate(
        "critical_risk_hard_verify", DecisionReason.EVIDENCE_INSUFFICIENT,
        lambda e, o, c, t: DecisionAction.VERIFY if o.risk_tier == "critical" else None,
        "VERIFY",
        lambda o, c, t: f"risk_tier={o.risk_tier!r}",
    ),
    _ConditionalGate(
        "oracle_quorum_gate", DecisionReason.INSUFFICIENT_ORACLE_VOTES,
        lambda e, o, c, t: DecisionAction.VERIFY
        if ((o.valid_oracle_count > 0 or o.oracle_failures > 0)
            and o.valid_oracle_count < MIN_REQUIRED_ORACLE_VOTES) else None,
        "VERIFY",
        lambda o, c, t: (
            f"valid_oracle_count={o.valid_oracle_count}, "
            f"oracle_failures={o.oracle_failures}, "
            f"min_required={MIN_REQUIRED_ORACLE_VOTES}"
        ),
    ),
    _ConditionalGate(
        "minimax_gate", DecisionReason.MINIMAX_ESCALATE,
        lambda e, o, c, t: DecisionAction.ESCALATE
        if (c.minimax_should_escalate(MINIMAX_ESCALATE_THRESHOLD)
            and c.ambiguity_width >= MINIMAX_AMBIGUITY_WIDTH_MIN) else None,
        "ESCALATE",
        lambda o, c, t: (
            f"worst_case_loss={c.worst_case_loss:.4f}, "
            f"ambiguity_width={c.ambiguity_width:.4f}, "
            f"threshold={MINIMAX_ESCALATE_THRESHOLD}"
        ),
    ),
    _ConditionalGate(
        "trap_escalate", DecisionReason.TRAP_ESCALATE,
        lambda e, o, c, t: DecisionAction.ESCALATE if t >= TRAP_ESCALATE_THRESHOLD else None,
        "ESCALATE",
        lambda o, c, t: f"trap_score={t:.4f}, threshold={TRAP_ESCALATE_THRESHOLD}",
    ),
    _ConditionalGate(
        "trap_verify", DecisionReason.TRAP_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (TRAP_VERIFY_THRESHOLD <= t < TRAP_ESCALATE_THRESHOLD) else None,
        "VERIFY",
        lambda o, c, t: f"trap_score={t:.4f}, [{TRAP_VERIFY_THRESHOLD}, {TRAP_ESCALATE_THRESHOLD})",
    ),
    _ConditionalGate(
        "unknown_risk_tier_verify", DecisionReason.UNKNOWN_RISK_TIER_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.risk_tier == "unknown"
            and ((o.action_type or "") in _MUTATING_TYPES
                 or (o.target_environment or "") in _PROD_ENVS)) else None,
        "VERIFY",
        lambda o, c, t: (
            f"risk_tier={o.risk_tier!r}, action_type={o.action_type!r}, "
            f"target_environment={o.target_environment!r}"
        ),
    ),
    _ConditionalGate(
        "env_mismatch_escalate", DecisionReason.ENV_MISMATCH_ESCALATE,
        lambda e, o, c, t: DecisionAction.ESCALATE if o.environment_mismatch_detected else None,
        "ESCALATE",
        lambda o, c, t: f"environment_mismatch_detected={o.environment_mismatch_detected}",
    ),
    _ConditionalGate(
        "env_confidence_verify", DecisionReason.ENV_CONFIDENCE_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.target_environment in _PROD_ENVS
            and o.environment_confidence is not None
            and o.environment_confidence < ENV_CONFIDENCE_MIN
            and o.action_type not in _READ_ONLY_TYPES) else None,
        "VERIFY",
        lambda o, c, t: f"target_environment={o.target_environment!r}, env_confidence={o.environment_confidence}",
    ),
    _ConditionalGate(
        "critical_alternative", DecisionReason.CRITICAL_ALTERNATIVE,
        lambda e, o, c, t: DecisionAction.ESCALATE
        if (o.classification_alternatives and any(
            a in _CRITICAL_ALT_TYPES for a in o.classification_alternatives)) else None,
        "ESCALATE",
        lambda o, c, t: f"classification_alternatives={o.classification_alternatives!r}",
    ),
    _ConditionalGate(
        "high_risk_alternative", DecisionReason.HIGH_RISK_ALTERNATIVE,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.classification_alternatives and any(
            a in _HIGH_RISK_ALT_TYPES for a in o.classification_alternatives)) else None,
        "VERIFY",
        lambda o, c, t: f"classification_alternatives={o.classification_alternatives!r}",
    ),
    _ConditionalGate(
        "low_classification_conf", DecisionReason.LOW_CLASSIFICATION_CONF,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.classification_confidence is not None
            and o.classification_confidence < CLASSIFICATION_CONFIDENCE_MIN
            and o.action_type not in _READ_ONLY_TYPES) else None,
        "VERIFY",
        lambda o, c, t: f"classification_confidence={o.classification_confidence}, action_type={o.action_type!r}",
    ),
    _ConditionalGate(
        "misspecification_verify", DecisionReason.MISSPECIFICATION_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.model_misspecification_risk is not None
            and o.model_misspecification_risk > MISSPECIFICATION_RISK_MAX
            and o.action_type not in _READ_ONLY_TYPES) else None,
        "VERIFY",
        lambda o, c, t: f"model_misspecification_risk={o.model_misspecification_risk}, action_type={o.action_type!r}",
    ),
    _ConditionalGate(
        "session_risk_verify", DecisionReason.SESSION_RISK_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.session_cumulative_risk is not None
            and o.session_cumulative_risk > SESSION_CUMULATIVE_RISK_MAX) else None,
        "VERIFY",
        lambda o, c, t: f"session_cumulative_risk={o.session_cumulative_risk}",
    ),
    _ConditionalGate(
        "session_flood_verify", DecisionReason.SESSION_FLOOD_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.session_action_count is not None
            and o.session_action_count > SESSION_ACTION_COUNT_MAX) else None,
        "VERIFY",
        lambda o, c, t: f"session_action_count={o.session_action_count}",
    ),
    _ConditionalGate(
        "fleet_systemic_verify", DecisionReason.FLEET_SYSTEMIC_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if o.fleet_level_effect in ("systemic", "critical_mass") else None,
        "VERIFY",
        lambda o, c, t: f"fleet_level_effect={o.fleet_level_effect!r}",
    ),
    _ConditionalGate(
        "policy_generalization_verify", DecisionReason.POLICY_GENERALIZATION_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.policy_generalization_risk is not None
            and o.policy_generalization_risk > POLICY_GENERALIZATION_RISK_MAX) else None,
        "VERIFY",
        lambda o, c, t: f"policy_generalization_risk={o.policy_generalization_risk}",
    ),
    _ConditionalGate(
        "similar_action_flood_verify", DecisionReason.SIMILAR_ACTION_FLOOD_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.similar_action_seen_count is not None
            and o.similar_action_seen_count > SIMILAR_ACTION_FLOOD_MAX) else None,
        "VERIFY",
        lambda o, c, t: f"similar_action_seen_count={o.similar_action_seen_count}",
    ),
    _ConditionalGate(
        "counterfactual_unknown_verify", DecisionReason.COUNTERFACTUAL_UNKNOWN_VERIFY,
        lambda e, o, c, t: DecisionAction.VERIFY
        if (o.risk_tier in ("high", "critical")
            and o.evidence_action in ("answer", "evidence_accept")
            and o.counterfactual_passed is None) else None,
        "VERIFY",
        lambda o, c, t: (
            f"risk_tier={o.risk_tier!r}, evidence_action={o.evidence_action!r}, "
            f"counterfactual_passed={o.counterfactual_passed}"
        ),
    ),
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RemoraDecisionEngine:
    """Conservative policy engine mapping PolicyObservation → DecisionReport.

    Parameters
    ----------
    temperature_threshold:
        Temperature upper bound for the TEMPERATURE_ACCEPT path (in-sample
        optimum from N=500 artifact, T*≈0.1972).
    conformal_trust_threshold:
        Trust-score lower bound from offline conformal calibration.
        Load from a ``GuardrailReport`` artifact — not from the evaluation set.
    conformal_phase_thresholds:
        Per-phase Mondrian conformal thresholds ``{phase: threshold}``.
    """

    # Recommended conformal trust threshold for AROMER-managed deployments.
    # When set, ACCEPT fires for trust >= this value before the critical-phase
    # VERIFY check. Only inject this via AromerOrchestrator.decide() once the
    # world model is calibrated (shadow_mode=False). Default is None so the
    # base engine is unchanged for non-AROMER callers.
    AROMER_CONFORMAL_TRUST_THRESHOLD: float = 0.72

    def __init__(
        self,
        temperature_threshold: float | None = None,
        conformal_trust_threshold: float | None = None,
        conformal_phase_thresholds: dict[str, float] | None = None,
        low_consequence_accept: bool = False,
        grounded_read_accept: bool = False,
        execution_profile: bool = False,
        semantic_authority_floor: bool = False,
        verify_invariants: bool = True,
    ) -> None:
        # ON by default and deliberately not an "opt-in ACCEPT path" flag:
        # it can only ever make a decision stricter. Every decision is checked
        # against CORE_INVARIANTS at the single build choke point, and a
        # violation is converted to ESCALATE. Turn it off only to measure the
        # cost of the check itself; a deployment that disables it is running
        # unverified decisions.
        self.verify_invariants = verify_invariants
        # Opt-in: lets bounded, reversible action semantics reach ACCEPT without
        # an oracle consensus signal. Off by default — see the path itself for
        # what it does and does not assert.
        self.low_consequence_accept = low_consequence_accept
        # Opt-in: the deterministic ACCEPT for a read whose every grounding
        # signal is confirmed under a server-resolved intent authority. Off by
        # default because it is only meaningful once a deployment has declared
        # tool contracts, a state index and an intent source; enabling it
        # without those declarations grounds nothing and accepts nothing.
        self.grounded_read_accept = grounded_read_accept
        # Issue #35: the execution profile makes it STRUCTURALLY impossible
        # for a probabilistic signal (conformal/temperature/evidence/
        # ordered-trust) to directly produce ACCEPT — those paths route to
        # VERIFY instead. Deterministic opt-in ACCEPTs (grounded read,
        # low consequence) are unaffected: they read registry/state facts,
        # not model output.
        self.execution_profile = execution_profile
        # Semantic-authority floor (opt-in): for a proposed tool call,
        # tool_matches_goal / expected_effect_matches must be POSITIVELY
        # established before any ACCEPT path may run - False already stops
        # via the conditional gates; None (nothing establishes the fit)
        # routes to VERIFY instead of silently passing through to
        # low_consequence_accept. FALSE -> stop, UNKNOWN -> verify,
        # TRUE -> the ordinary gates decide.
        self.semantic_authority_floor = semantic_authority_floor
        self.temperature_threshold = temperature_threshold
        self.conformal_trust_threshold = conformal_trust_threshold
        self.conformal_phase_thresholds = conformal_phase_thresholds

    _PROD_ENVIRONMENTS = {"prod", "production", "live"}
    _PROD_WRITE_ACTION_TYPES = {
        "production_write",
        "destructive_write",
        "emergency_write",
        "financial_write",
        "delete",
    }

    @classmethod
    def _is_production_write(cls, obs: PolicyObservation) -> bool:
        action_type = (obs.action_type or "").strip().lower()
        target_environment = (obs.target_environment or "").strip().lower()
        return (
            action_type in cls._PROD_WRITE_ACTION_TYPES
            and target_environment in cls._PROD_ENVIRONMENTS
        )

    @classmethod
    def _production_write_outcome(cls, obs: PolicyObservation) -> DecisionAction | None:
        """Explicit risk/action/environment policy matrix for production writes."""
        if not cls._is_production_write(obs):
            return None
        if obs.risk_tier == "critical":
            return DecisionAction.ESCALATE
        if obs.risk_tier == "high":
            return DecisionAction.VERIFY
        return None

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------


    def _probabilistic_accept(
        self,
        reasons: list[DecisionReason],
        obs: PolicyObservation,
        *,
        credal: CredalEnvelope | None,
        raw_obs: PolicyObservation | None,
    ) -> DecisionReport:
        """A probabilistic path concluded ACCEPT. In the execution profile
        that conclusion is advisory only: the call routes to VERIFY with an
        explicit reason (issue #35 invariant: PROBABILISTIC_SIGNAL can never
        directly produce ACCEPT)."""
        if self.execution_profile:
            reasons.append(DecisionReason.EXECUTION_PROFILE_PROBABILISTIC_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs,
                               credal=credal, raw_obs=raw_obs)
        return self._build(DecisionAction.ACCEPT, reasons, obs,
                           credal=credal, raw_obs=raw_obs)

    def decide(
        self, obs: PolicyObservation, *, _skip_hard_floor: bool = False
    ) -> DecisionReport:
        """Gate a proposed action and return an authoritative DecisionReport.

        ``_skip_hard_floor`` is a private ablation hook for shadow-mode
        counterfactual replay ONLY (the ``no_hard_guards`` baseline arm in
        ``remora.shadow.replay``): it skips the hard-guard floor while every
        other stage — including risk-tier flooring, so critical actions are
        still never autonomously accepted — runs unchanged on the untouched
        observation. It must never be set on any enforcement path; the
        authoritative decision semantics are the default.
        """
        # ── FAIL-CLOSED NORMALISATION ────────────────────────────────────────
        # Normalise risk_tier, action_type, and target_environment before any
        # rule evaluation so that typos, mixed-case strings, or absent values
        # cannot silently bypass safety gates.  Keep the original for the report's
        # raw_observation field so callers see what they sent, not what we rewrote.
        _raw_obs = obs
        obs = _normalize_observation(obs)
        reasons: list[DecisionReason] = []

        # ── CREDAL RISK ENVELOPE ─────────────────────────────────────────────
        # Computed once; used by minimax gate, trap gate, ambiguity penalty,
        # and attached to every DecisionReport for audit consumers.
        _credal: CredalEnvelope = compute_from_obs(obs)
        _trap: float = trap_score(obs)

        # ── HARD BLOCKS (priority order) ────────────────────────────────────
        # Single source of truth: hard_guard_floor(). The same function backs
        # the OPA adapter's monotonicity floor, so an external PDP can never
        # downgrade below what this stage would return. The tainted-argument
        # floor is intentionally last in hard_guard_floor() and is
        # tier-dependent (issue #40, 2026-07-30): CRITICAL risk escalates
        # (TAINTED_ARGUMENT_ESCALATE — never an approvable VERIFY), other
        # tiers yield the VERIFY floor. Both block autonomous execution and
        # set human_review_required.

        _floor = None if _skip_hard_floor else hard_guard_floor(obs)

        # Adversarial and malformed-schema guards fire before the
        # schema-unverified annotation below (preserves reason ordering).
        if _floor is not None and _floor[1] in (
            DecisionReason.ADMISSION_FIREWALL_BLOCKED,
            DecisionReason.MALFORMED_CALL_BLOCKED,
        ):
            reasons.append(_floor[1])
            return self._build(_floor[0], reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # GAP B: schema_valid=None means the validator did not run — UNVERIFIED.
        # Mark as a floor check (prevents ACCEPT for mutating actions) without
        # preempting higher-priority ESCALATE paths. The actual VERIFY return is
        # placed just before the ACCEPT paths below.
        _schema_unverified_mutating = (
            obs.schema_valid is None and (obs.action_type or "") in _MUTATING_TYPES
        )
        if _schema_unverified_mutating:
            reasons.append(DecisionReason.SCHEMA_UNVERIFIED_VERIFY)

        if _floor is not None:
            reasons.append(_floor[1])
            return self._build(_floor[0], reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── CONDITIONAL GATES (single source: _CONDITIONAL_GATES) ───────────
        # These uniform gates run after the hard-guard floor and before the
        # schema/ACCEPT-tail logic. First gate whose evaluate() yields an action
        # wins. The same ordered inventory backs explain(), so the audit trace
        # can never drift from the decision (Grok review P1). Each gate's reason
        # semantics and comments live at the _CONDITIONAL_GATES definition above:
        # rollback/state-transition escalate before the evidence gates; the
        # oracle-quorum, minimax, trap, unknown-risk-tier, misspecification,
        # session, and fleet/generalization gates follow in priority order.
        for _gate in _CONDITIONAL_GATES:
            _outcome = _gate.evaluate(self, obs, _credal, _trap)
            if _outcome is not None:
                reasons.append(_gate.reason)
                # A VERIFY whose information gap is already known to be
                # unclosable is a false promise, whichever gate produced it.
                # The §23 contract — VERIFY means a specific bounded step is
                # expected to establish the missing information — has to hold
                # for upstream gates too, or a mutating call with an unknown
                # schema is told to verify something the engine has already
                # established nobody can supply. Both outcomes block execution,
                # so this is a statement about honesty, not a safety change.
                # ESCALATE and ABSTAIN are untouched: a block outranks it.
                if _outcome is DecisionAction.VERIFY and _unresolvable_gap(obs):
                    reasons.append(DecisionReason.NO_RESOLVER_AVAILABLE)
                    return self._build(
                        DecisionAction.ABSTAIN, reasons, obs,
                        credal=_credal, raw_obs=_raw_obs,
                    )
                return self._build(_outcome, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── SCHEMA UNVERIFIED FLOOR ─────────────────────────────────────────
        # All higher-priority ESCALATE/VERIFY paths (adversarial, malformed,
        # forbidden, production-write, critical risk, etc.) have been checked.
        # If schema was not validated for a mutating action, force VERIFY here
        # rather than letting the action reach an ACCEPT outcome.
        if _schema_unverified_mutating:
            if _unresolvable_gap(obs):
                reasons.append(DecisionReason.NO_RESOLVER_AVAILABLE)
                return self._build(DecisionAction.ABSTAIN, reasons, obs,
                                   credal=_credal, raw_obs=_raw_obs)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── UNKNOWN ACTION-TYPE FLOOR ───────────────────────────────────────
        # A non-empty action_type outside the known vocabulary (mutating,
        # read-only, or non-actuating) is an unrecognised actuation type: it
        # must not reach ACCEPT via the conformal/temperature/evidence/
        # ordered-trust paths on a low/medium declared risk tier. Deny-by-
        # default for actuation — route to VERIFY. action_type=None (pure QA /
        # no tool call) is intentionally allowed through. For tool-calling
        # operations, an empty action_type is treated as unclassified actuation
        # and floored to VERIFY.
        _action_norm = (obs.action_type or "").strip().lower()
        _is_unclassified_actuation = (
            obs.proposed_tool_name is not None
            and obs.proposed_tool_name.strip() != ""
            and not _action_norm
        )
        _is_unknown_action_type = (
            _is_unclassified_actuation or (
                bool(_action_norm)
                and _action_norm not in _READ_ONLY_TYPES
                and _action_norm not in _MUTATING_TYPES
                and _action_norm not in _NON_ACTUATING_TYPES
            )
        )
        if _is_unknown_action_type:
            reasons.append(DecisionReason.UNKNOWN_ACTION_TYPE_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── TOOL-SET MEMBERSHIP FLOOR ────────────────────────────────────────
        # True means the integration layer confirmed the proposed tool is absent
        # from the declared available_tools set. This is a caller-observable,
        # deterministic signal; None (set not supplied) passes through.
        if obs.tool_not_in_available_set is True:
            reasons.append(DecisionReason.TOOL_NOT_IN_AVAILABLE_SET)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── SEMANTIC-AUTHORITY FLOOR (opt-in) ───────────────────────────────
        # Low consequence is not the same thing as correct purpose: a cheap
        # read to the wrong tool is still a wrong execution. False fit was
        # already refused by the conditional gates above; here an UNKNOWN fit
        # for a proposed tool refuses to reach any ACCEPT path.
        if (
            self.semantic_authority_floor
            and obs.proposed_tool_name
            and (obs.tool_matches_goal is None
                 or obs.expected_effect_matches is None)
        ):
            reasons.append(DecisionReason.SEMANTIC_AUTHORITY_UNKNOWN_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs,
                               credal=_credal, raw_obs=_raw_obs)

        # ── MONDRIAN PER-PHASE CONFORMAL ────────────────────────────────────

        if (
            self.conformal_phase_thresholds is not None
            and obs.phase in self.conformal_phase_thresholds
            and obs.trust_score is not None
        ):
            thresh = self.conformal_phase_thresholds[obs.phase]
            if obs.trust_score >= thresh:
                reasons.append(DecisionReason.CONFORMAL_ACCEPT)
                return self._probabilistic_accept(reasons, obs, credal=_credal, raw_obs=_raw_obs)
            else:
                reasons.append(DecisionReason.CONFORMAL_ABSTAIN)
                return self._build(DecisionAction.ABSTAIN, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── ACCEPT PATHS ────────────────────────────────────────────────────

        # Marginal (phase-blind) conformal ACCEPT must not apply to the
        # critical phase: trust anti-correlates with correctness there
        # (ARCHITECTURE.md §8, CLAIM-005), so a phase-blind trust threshold
        # would accept exactly the items most likely to be wrong. Critical-
        # phase routing is handled by the Mondrian per-phase path above and
        # the critical-phase VERIFY below.
        if (
            self.conformal_trust_threshold is not None
            and obs.trust_score is not None
            and obs.trust_score >= self.conformal_trust_threshold
            and obs.phase != "critical"
            and obs.counterfactual_passed is not False
            and not (obs.evidence_contradictions or 0)
        ):
            reasons.append(DecisionReason.CONFORMAL_ACCEPT)
            return self._probabilistic_accept(reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # Temperature ACCEPT carries the same critical-phase exclusion as the
        # marginal conformal path above, and for the same reason: temperature
        # is a phase-blind aggregate of the oracle distribution, so in the
        # critical phase a low value selects the items where trust
        # anti-correlates with correctness. Without this guard a low
        # temperature silently overrides critical-phase VERIFY routing.
        if (
            self.temperature_threshold is not None
            and obs.temperature is not None
            and obs.temperature <= self.temperature_threshold
            and obs.phase != "critical"
            and obs.counterfactual_passed is not False
            and not (obs.evidence_contradictions or 0)
        ):
            reasons.append(DecisionReason.TEMPERATURE_ACCEPT)
            return self._probabilistic_accept(reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (
            obs.evidence_action in ("answer", "evidence_accept")
            and obs.evidence_confidence is not None
            and obs.evidence_confidence >= EVIDENCE_CONFIDENCE_MIN
            and not (obs.evidence_contradictions or 0)
            and obs.counterfactual_passed is not False
        ):
            reasons.append(DecisionReason.EVIDENCE_SUPPORTED)
            if obs.phase == "ordered" or (obs.trust_score or 0) >= ORDERED_HIGH_TRUST_MIN:
                return self._probabilistic_accept(reasons, obs, credal=_credal, raw_obs=_raw_obs)
            reasons.append(DecisionReason.CRITICAL_PHASE)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # Ordered high-trust accept path: use ambiguity-penalised trust so that
        # high oracle disagreement prevents ACCEPT even when raw trust is above
        # threshold.  Conformal and temperature paths retain raw trust (their
        # calibration already accounts for uncertainty).
        _effective_trust = (
            _credal.adjusted_trust
            if _credal.adjusted_trust is not None
            else (obs.trust_score or 0.0)
        )
        if (
            obs.phase == "ordered"
            and _effective_trust >= ORDERED_HIGH_TRUST_MIN
            and obs.counterfactual_passed is not False
            and not (obs.evidence_contradictions or 0)
        ):
            if _credal.adjusted_trust is not None and _credal.adjusted_trust < (obs.trust_score or 0):
                reasons.append(DecisionReason.AMBIGUITY_PENALTY)
            reasons.append(DecisionReason.ORDERED_HIGH_TRUST)
            return self._probabilistic_accept(reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── VERIFY PATHS ────────────────────────────────────────────────────

        # If ambiguity penalty prevented ordered_high_trust ACCEPT (raw trust ≥ 0.72
        # but adjusted_trust dropped below threshold), route to VERIFY rather than
        # falling through to ABSTAIN.  The disagreement warrants human review.
        if (
            obs.phase == "ordered"
            and (obs.trust_score or 0) >= ORDERED_HIGH_TRUST_MIN
            and _credal.adjusted_trust is not None
            and _credal.adjusted_trust < ORDERED_HIGH_TRUST_MIN
            and obs.counterfactual_passed is not False
            and not (obs.evidence_contradictions or 0)
        ):
            reasons.append(DecisionReason.AMBIGUITY_PENALTY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.phase == "critical":
            reasons.append(DecisionReason.CRITICAL_PHASE)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.require_rag and obs.evidence_action is None:
            reasons.append(DecisionReason.THERMO_REQUIRE_EVIDENCE)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (obs.claim_graph_betti_1 or 0) > 0:
            reasons.append(DecisionReason.HIGH_CONTRADICTION)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── ABSTAIN PATHS ────────────────────────────────────────────────────

        if obs.phase == "disordered" and obs.evidence_action != "answer":
            reasons.append(DecisionReason.DISORDERED_NO_EVIDENCE)
            return self._build(DecisionAction.ABSTAIN, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # trust_score=0.0 is a real (minimal) trust signal and must fire this
        # rule; only a missing signal (None) falls through to the default.
        if (
            obs.trust_score is not None
            and obs.trust_score < LOW_TRUST_ABSTAIN_MAX
            and obs.evidence_action != "answer"
        ):
            reasons.append(DecisionReason.LOW_TRUST)
            return self._build(DecisionAction.ABSTAIN, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── ARGUMENT RESOLUTION (2026-07-31) ─────────────────────────────
        # Note: the unresolvable half of this rule also runs *before* the
        # conditional gates, in decide(), because a VERIFY produced upstream
        # would otherwise outlive the fact that its gap cannot be closed.
        # §22 measured obtainable VERIFY recall at 0%: a call missing an
        # argument an available tool could supply was accepted rather than
        # routed to a bounded fetch. This is the gate that distinguishes
        # "resolvable gap" from "unresolvable gap", which §21 showed the router
        # could not do. Inert until the caller populates the fields, so default
        # behaviour is unchanged.
        #
        # Placed after every blocking gate, so it can only convert a
        # fall-through — a forbidden tool still escalates on re-entry.
        if obs.missing_required_arguments:
            if obs.argument_resolver_tools and obs.arguments_satisfiable is not False:
                reasons.append(DecisionReason.ARGUMENT_RESOLUTION_REQUIRED)
                return self._build(
                    DecisionAction.VERIFY, reasons, obs,
                    credal=_credal, raw_obs=_raw_obs,
                    resolution_plan=ResolutionPlan(
                        resolver="argument_resolution",
                        target_arguments=tuple(obs.missing_required_arguments),
                        source_tools=tuple(obs.argument_resolver_tools),
                    ),
                )
            # No bounded step can close the gap. Promising a verification that
            # cannot happen is worse than stopping.
            reasons.append(DecisionReason.NO_RESOLVER_AVAILABLE)
            return self._build(DecisionAction.ABSTAIN, reasons, obs,
                               credal=_credal, raw_obs=_raw_obs)

        # ── VALIDATION REQUIRED (2026-07-31) ─────────────────────────────
        # §27 left UNKNOWN falling through to autonomy, so an uncovered domain
        # accepted 61.5% of corrupted identifiers. An argument that steers where
        # the action lands must be confirmed before autonomous execution — and
        # only such arguments, because routing every UNKNOWN here would rebuild
        # the constant blocker of §21 one level up.
        #
        # Placed after every blocking gate, so it can only convert a
        # fall-through. Inert until the caller populates the field.
        if obs.unvalidated_required_arguments:
            if obs.argument_resolver_tools:
                reasons.append(DecisionReason.ARGUMENT_VALIDATION_REQUIRED)
                return self._build(
                    DecisionAction.VERIFY, reasons, obs,
                    credal=_credal, raw_obs=_raw_obs,
                    resolution_plan=ResolutionPlan(
                        resolver="argument_validation",
                        target_arguments=tuple(obs.unvalidated_required_arguments),
                        source_tools=tuple(obs.argument_resolver_tools),
                    ),
                )
            # Nothing authoritative can confirm it, so autonomy is unavailable.
            reasons.append(DecisionReason.NO_RESOLVER_AVAILABLE)
            return self._build(DecisionAction.ABSTAIN, reasons, obs,
                               credal=_credal, raw_obs=_raw_obs)

        # ── UNGROUNDED ARGUMENT VALUES (2026-07-31) ──────────────────────
        # §34 measured the open autonomy risk: 86.8% of well-formed foreign
        # calls accepted, because every structural signal was satisfied. The
        # tell is provenance-shaped — the values are traceable to nothing in
        # this context — so autonomy withdraws to VERIFY. Placed after every
        # blocking gate (it can only convert a fall-through, never preempt a
        # block) and before the low-consequence accept it exists to guard.
        # None never triggers it: a call with nothing to judge keeps its lane.
        if obs.argument_values_grounded is False:
            reasons.append(DecisionReason.UNGROUNDED_ARGUMENT_VALUES_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs,
                               credal=_credal, raw_obs=_raw_obs)

        # ── LOW-CONSEQUENCE ACCEPT (opt-in, 2026-07-31) ─────────────────────
        # Placed here deliberately: every hard guard and every blocking gate has
        # already run, so this can only convert a fall-through that would
        # otherwise abstain. It can never preempt a block —
        # tests/test_low_consequence_accept.py asserts that over a grid.
        #
        # What it asserts is CONSEQUENCE, not correctness. The engine cannot
        # tell a correct read from an incorrect one from observable data; the
        # claim is only that executing this call is cheap to get wrong. That is
        # why it is restricted to read-only semantics with no negative safety
        # signal, and why it is off by default.
        #
        # Known cost, measured on the routing benchmark: it also accepts
        # read-only calls that are the *wrong* call for the task, including
        # cases another source annotates as unanswerable. A deployment that
        # cannot tolerate a wasted or mildly disclosing read must leave it off.
        # ── GROUNDED READ ACCEPT (opt-in, 2026-08-06) ───────────────────────
        # Checked before the low-consequence path because it is strictly
        # stronger and deserves its own reason in the audit record: a decision
        # that says "grounded_read_accept" states which signals carried it,
        # where "low_consequence_accept" only states that nothing objected.
        #
        # Same placement guarantee as that path — after every hard guard and
        # blocking gate, so it can only convert a fall-through and can never
        # preempt a block.
        if self.grounded_read_accept and _is_grounded_read(obs):
            reasons.append(DecisionReason.GROUNDED_READ_ACCEPT)
            return self._build(DecisionAction.ACCEPT, reasons, obs,
                               credal=_credal, raw_obs=_raw_obs)

        if self.low_consequence_accept and _is_low_consequence(obs):
            reasons.append(DecisionReason.LOW_CONSEQUENCE_ACCEPT)
            return self._build(DecisionAction.ACCEPT, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── DEFAULT ─────────────────────────────────────────────────────────

        reasons.append(DecisionReason.DEFAULT_SAFE_ABSTAIN)
        return self._build(DecisionAction.ABSTAIN, reasons, obs, credal=_credal, raw_obs=_raw_obs)

    def explain(self, obs: PolicyObservation) -> PolicyTrace:
        """Return a full structured explanation of the governance decision.

        Evaluates every rule in the decision tree and records which fired,
        which were skipped, and what outcome each would produce.  Use this
        to produce human-readable audit trails, debug unexpected decisions,
        and generate explainability reports for compliance.

        Parameters
        ----------
        obs:
            The observation to explain.

        Returns
        -------
        PolicyTrace
            Ordered rule evaluations + decision path + observation summary.

        Example::

            trace = engine.explain(obs)
            print(trace.decision_path)
            for step in trace.rule_evaluations:
                marker = "✓" if step.triggered else "·"
                print(f"  {marker} [{step.rule}] {step.condition}")
        """
        obs = _normalize_observation(obs)
        report = self.decide(obs)
        steps: list[PolicyRuleEvaluation] = []

        def r(name: str, fired: bool, cond: str, out: str | None = None) -> None:
            steps.append(PolicyRuleEvaluation(rule=name, triggered=fired, condition=cond, outcome=out))

        # Mirror every rule — read-only, no early exits
        r("adversarial_firewall",
          obs.adversarial_detected,
          f"adversarial_detected={obs.adversarial_detected}",
          "ESCALATE")

        r("malformed_call_check",
          obs.schema_valid is False,
          f"schema_valid={obs.schema_valid}",
          "ESCALATE")

        r("forbidden_tool_check",
          obs.tool_forbidden,
          f"tool_forbidden={obs.tool_forbidden}",
          "ESCALATE")

        r("coercion_blocked",
          obs.coercion_detected,
          f"coercion_detected={obs.coercion_detected}",
          "ESCALATE")

        r("blackmail_blocked",
          obs.blackmail_pattern_detected,
          f"blackmail_pattern_detected={obs.blackmail_pattern_detected}",
          "ESCALATE")

        r("counterfactual_check",
          obs.counterfactual_passed is False,
          f"counterfactual_passed={obs.counterfactual_passed}",
          "ESCALATE")

        contradictions = obs.evidence_contradictions or 0
        r("evidence_contradiction",
          contradictions > 0,
          f"evidence_contradictions={obs.evidence_contradictions}",
          "ESCALATE" if (obs.contradiction_cycles or 0) > 0 else "ABSTAIN")

        r("tainted_argument_check",
          obs.argument_tainted,
          f"argument_tainted={obs.argument_tainted} risk_tier={obs.risk_tier}",
          "ESCALATE" if _normalize_risk_tier(obs.risk_tier) == "critical" else "VERIFY")

        # ── CONDITIONAL GATES (single source: _CONDITIONAL_GATES) ───────────
        # Record every conditional gate from the same ordered inventory decide()
        # returns on. Because each gate's evaluate() is self-contained, the row
        # a gate produces here is exactly the outcome decide() would take were
        # this the first gate to fire — so the trace can never drift from the
        # decision (Grok review P1).
        _explain_credal = compute_from_obs(obs)
        _explain_trap   = trap_score(obs)
        for _gate in _CONDITIONAL_GATES:
            _gate_action = _gate.evaluate(self, obs, _explain_credal, _explain_trap)
            r(_gate.name,
              _gate_action is not None,
              _gate.describe(obs, _explain_credal, _explain_trap),
              _gate.outcome_label(_gate_action))

        _schema_unverified_mutating = (
            obs.schema_valid is None and (obs.action_type or "") in _MUTATING_TYPES
        )
        r("schema_unverified_floor",
          _schema_unverified_mutating,
          f"schema_valid={obs.schema_valid}, action_type={obs.action_type!r}",
          "VERIFY")

        _explain_action_norm = (obs.action_type or "").strip().lower()
        _is_explain_unclassified_actuation = (
            obs.proposed_tool_name is not None
            and obs.proposed_tool_name.strip() != ""
            and not _explain_action_norm
        )
        _is_explain_unknown_action_type = (
            _is_explain_unclassified_actuation or (
                bool(_explain_action_norm)
                and _explain_action_norm not in _READ_ONLY_TYPES
                and _explain_action_norm not in _MUTATING_TYPES
                and _explain_action_norm not in _NON_ACTUATING_TYPES
            )
        )
        r("unknown_action_type_floor",
          _is_explain_unknown_action_type,
          f"action_type={obs.action_type!r} (not in known vocabulary, or unclassified tool call)",
          "VERIFY")

        # Issue #35: in the execution profile the probabilistic rules
        # conclude VERIFY, and the trace must say so.
        _paccept = "VERIFY" if self.execution_profile else "ACCEPT"

        r("tool_not_in_available_set",
          obs.tool_not_in_available_set is True,
          f"proposed_tool={obs.proposed_tool_name!r} not in declared available_tools",
          "VERIFY")

        r("semantic_authority_unknown_floor",
          bool(self.semantic_authority_floor and obs.proposed_tool_name
               and (obs.tool_matches_goal is None
                    or obs.expected_effect_matches is None)),
          f"tool_matches_goal={obs.tool_matches_goal}, "
          f"expected_effect_matches={obs.expected_effect_matches}",
          "VERIFY")


        if (
            self.conformal_phase_thresholds is not None
            and obs.phase in self.conformal_phase_thresholds
            and obs.trust_score is not None
        ):
            thresh = self.conformal_phase_thresholds[obs.phase]
            above = obs.trust_score >= thresh
            r("mondrian_conformal",
              True,
              f"phase={obs.phase!r}, trust={obs.trust_score:.3f}, threshold={thresh:.3f}",
              _paccept if above else "ABSTAIN")

        if self.conformal_trust_threshold is not None:
            above_marginal = (
                obs.trust_score is not None
                and obs.trust_score >= self.conformal_trust_threshold
                and obs.phase != "critical"
                and obs.counterfactual_passed is not False
                and not contradictions
            )
            r("marginal_conformal",
              above_marginal,
              f"trust={obs.trust_score}, threshold={self.conformal_trust_threshold}, "
              f"phase={obs.phase!r}",
              _paccept if above_marginal else None)

        if self.temperature_threshold is not None:
            below_temp = (
                obs.temperature is not None
                and obs.temperature <= self.temperature_threshold
                and obs.counterfactual_passed is not False
                and not contradictions
            )
            r("temperature_accept",
              bool(below_temp),
              f"temperature={obs.temperature}, threshold={self.temperature_threshold}",
              _paccept if below_temp else None)

        ev_accept = (
            obs.evidence_action in ("answer", "evidence_accept")
            and obs.evidence_confidence is not None
            and obs.evidence_confidence >= EVIDENCE_CONFIDENCE_MIN
            and not contradictions
            and obs.counterfactual_passed is not False
        )
        ev_outcome = (
            _paccept
            if (obs.phase == "ordered" or (obs.trust_score or 0) >= ORDERED_HIGH_TRUST_MIN)
            else "VERIFY"
        )
        r("evidence_supported_accept",
          ev_accept,
          f"evidence_action={obs.evidence_action!r}, confidence={obs.evidence_confidence}, "
          f"phase={obs.phase!r}, trust={obs.trust_score}",
          ev_outcome)

        _effective_trust = (
            _explain_credal.adjusted_trust
            if _explain_credal.adjusted_trust is not None
            else (obs.trust_score or 0.0)
        )
        ordered_trust = (
            obs.phase == "ordered"
            and _effective_trust >= ORDERED_HIGH_TRUST_MIN
            and obs.counterfactual_passed is not False
            and not contradictions
        )
        r("ordered_high_trust",
          ordered_trust,
          f"phase={obs.phase!r}, trust={obs.trust_score}, "
          f"ambiguity_adjusted_trust={_effective_trust:.3f}",
          _paccept)

        r("ambiguity_penalty_verify",
          obs.phase == "ordered"
          and (obs.trust_score or 0) >= ORDERED_HIGH_TRUST_MIN
          and _explain_credal.adjusted_trust is not None
          and _explain_credal.adjusted_trust < ORDERED_HIGH_TRUST_MIN
          and obs.counterfactual_passed is not False
          and not contradictions,
          f"trust={obs.trust_score}, "
          f"ambiguity_adjusted_trust={_explain_credal.adjusted_trust}",
          "VERIFY")

        r("critical_phase_verify",
          obs.phase == "critical",
          f"phase={obs.phase!r}",
          "VERIFY")

        r("require_rag_verify",
          bool(obs.require_rag and obs.evidence_action is None),
          f"require_rag={obs.require_rag}, evidence_action=None",
          "VERIFY")

        r("claim_graph_betti_verify",
          (obs.claim_graph_betti_1 or 0) > 0,
          f"claim_graph_betti_1={obs.claim_graph_betti_1}",
          "VERIFY")

        r("disordered_no_evidence",
          obs.phase == "disordered" and obs.evidence_action != "answer",
          f"phase={obs.phase!r}, evidence_action={obs.evidence_action!r}",
          "ABSTAIN")

        r("low_trust_abstain",
          obs.trust_score is not None
          and obs.trust_score < LOW_TRUST_ABSTAIN_MAX
          and obs.evidence_action != "answer",
          f"trust={obs.trust_score}",
          "ABSTAIN")

        r("grounded_read_accept",
          DecisionReason.GROUNDED_READ_ACCEPT in report.reasons,
          f"intent_authority_present={obs.intent_authority_present}, "
          f"tool_matches_goal={obs.tool_matches_goal}, "
          f"expected_effect_matches={obs.expected_effect_matches}, "
          f"argument_values_supported={obs.argument_values_supported}, "
          f"argument_values_grounded={obs.argument_values_grounded}, "
          f"risk_tier={obs.risk_tier!r}, action_type={obs.action_type!r}",
          "ACCEPT")

        r("default_safe_abstain",
          DecisionReason.DEFAULT_SAFE_ABSTAIN in report.reasons,
          "no prior rule matched",
          "ABSTAIN")

        # Runtime invariant enforcement overrides the ladder, so it belongs at
        # the FRONT of the trace: a reader must not see conformal_accept fire
        # and conclude the action was ACCEPT when the decision was withdrawn.
        if DecisionReason.INVARIANT_VIOLATION_ESCALATE in report.reasons:
            steps.insert(0, PolicyRuleEvaluation(
                rule="invariant_enforcement",
                triggered=True,
                condition="a CORE_INVARIANTS check failed for this decision; "
                          "the ladder's outcome was withdrawn",
                outcome="ESCALATE",
            ))

        # Decision path: first triggered rule that matches the final action
        final_action = report.action.value.upper()
        fired = [s for s in steps if s.triggered and s.outcome == final_action]
        decision_path = f"{fired[0].rule} → {final_action}" if fired else f"default → {final_action}"

        return PolicyTrace(
            action=report.action.value,
            reasons=tuple(r.value for r in report.reasons),
            decision_path=decision_path,
            rule_evaluations=tuple(steps),
            observation_summary={
                k: v for k, v in {
                    "phase": obs.phase,
                    "trust_score": obs.trust_score,
                    "risk_tier": obs.risk_tier,
                    "action_type": obs.action_type,
                    "adversarial_detected": obs.adversarial_detected,
                    "evidence_action": obs.evidence_action,
                    "evidence_contradictions": obs.evidence_contradictions,
                    "final_H": obs.final_H,
                    "final_D": obs.final_D,
                }.items() if v is not None
            },
            policy_version=report.policy_version,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build(
        self,
        action: DecisionAction,
        reasons: list[DecisionReason],
        obs: PolicyObservation,
        *,
        credal: CredalEnvelope | None = None,
        raw_obs: PolicyObservation | None = None,
        resolution_plan: ResolutionPlan | None = None,
        _invariant_recheck: bool = False,
    ) -> DecisionReport:
        if obs.assurance_root is not None and DecisionReason.TRACE_ATTACHED not in reasons:
            reasons = list(reasons) + [DecisionReason.TRACE_ATTACHED]

        source = self._source_of_decision(reasons)

        # Compute credal envelope if not supplied by caller (e.g. in tests
        # that call _build() directly).
        if credal is None:
            credal = compute_from_obs(obs)

        if action == DecisionAction.ACCEPT:
            if DecisionReason.TEMPERATURE_ACCEPT in reasons and obs.temperature is not None:
                thresh = self.temperature_threshold or max(obs.temperature, 1e-9)
                base = max(0.0, min(1.0, 1.0 - obs.temperature / max(thresh * 2.0, 1e-9)))
            else:
                # Use ambiguity-penalised trust so risk_estimate reflects disagreement.
                base = (
                    credal.adjusted_trust
                    if credal.adjusted_trust is not None
                    else (obs.trust_score if obs.trust_score is not None else (obs.weighted_support or 0.5))
                )
            risk_estimate: float | None = 1.0 - base
        # NOTE (external review 2026-07-25): the non-ACCEPT risk_estimate values
        # below are RELATIVE decision labels for ordering/telemetry, NOT
        # calibrated error probabilities. VERIFY=0.3 marks "hold for review",
        # ESCALATE=1.0 marks a hard/policy failure, ABSTAIN=None means "no
        # estimate offered". Do not consume them as probabilities; the only
        # calibrated quantity is the ACCEPT-path 1.0-base above.
        elif action == DecisionAction.VERIFY:
            risk_estimate = 0.3
        elif action == DecisionAction.ABSTAIN:
            risk_estimate = None
        else:
            risk_estimate = 1.0

        if action == DecisionAction.ACCEPT:
            confidence: float | None = (
                obs.trust_score if obs.trust_score is not None
                else obs.evidence_confidence
            )
        elif action == DecisionAction.VERIFY:
            confidence = 0.5
        elif action == DecisionAction.ABSTAIN:
            confidence = None
        else:
            confidence = 0.0

        evidence_required = (
            action in {DecisionAction.VERIFY, DecisionAction.ABSTAIN, DecisionAction.ESCALATE}
            and obs.evidence_action != "answer"
        )
        if DecisionReason.THERMO_REQUIRE_EVIDENCE in reasons:
            evidence_required = True
        if DecisionReason.DISTRIBUTION_SHIFT in reasons:
            evidence_required = True

        human_review_required = (
            action in {DecisionAction.ESCALATE, DecisionAction.VERIFY}
            or obs.risk_tier == "critical"
        )

        explanation_map = {
            DecisionAction.ACCEPT: "Action accepted based on available evidence and trust signal.",
            DecisionAction.VERIFY: "Action held for external verification before execution.",
            DecisionAction.ABSTAIN: "Insufficient evidence to authorise autonomous execution.",
            DecisionAction.ESCALATE: "Hard failure detected — routing to human review.",
        }

        report = DecisionReport(
            action=action,
            reasons=tuple(reasons),
            risk_estimate=risk_estimate,
            confidence=confidence,
            coverage_policy=(
                # The low-consequence path reaches ACCEPT with no evidence or
                # trust signal at all, so the generic ACCEPT wording would be a
                # false statement about why the action was permitted.
                "bounded consequence — read-only action, no evidence/trust signal used"
                if DecisionReason.LOW_CONSEQUENCE_ACCEPT in reasons
                # Also not evidence/trust based, but for the opposite reason:
                # it asserts more than the generic wording, not less. Saying
                # "accepted based on evidence/trust state" would name signals
                # this path deliberately does not consult.
                else "grounded declaration — read confirmed against declared "
                     "contracts, system of record and a resolved intent "
                     "authority; no evidence/trust signal used"
                if DecisionReason.GROUNDED_READ_ACCEPT in reasons
                else {
                    DecisionAction.ACCEPT: "selective — accepted based on evidence/trust state",
                    DecisionAction.VERIFY: "held for verification",
                    DecisionAction.ABSTAIN: "abstained — insufficient evidence",
                    DecisionAction.ESCALATE: "escalated — hard failure detected",
                }[action]
            ),
            evidence_required=evidence_required,
            human_review_required=human_review_required,
            audit_root=obs.assurance_root,
            explanation=explanation_map[action],
            raw_observation=raw_obs if raw_obs is not None else obs,
            source_of_decision=source,
            # v5 (2026-07-31): temperature ACCEPT excludes the critical phase.
            # v4 (2026-07-30): tier-dependent tainted floor (issue #40).
            policy_version="RemoraDecisionEngine-v5",
            in_sample_calibration_warning=(
                "temperature threshold may be in-sample if derived from evaluation artifact"
                if DecisionReason.TEMPERATURE_ACCEPT in reasons and self.temperature_threshold is not None
                else None
            ),
            credal=credal,
            resolution_plan=resolution_plan,
        )

        # ── RUNTIME INVARIANT ENFORCEMENT ───────────────────────────────────
        # _build is the single choke point every decision passes through, so
        # this is the one place that can hold the whole engine to the
        # invariants. They were previously evaluated only in tests, which made
        # them a description of intended behaviour rather than a guarantee:
        # the same safety properties were implemented a second time inside
        # decide(), and nothing would have noticed the two drifting apart.
        #
        # A violation fails CLOSED to ESCALATE rather than raising, so the
        # decision stays inside the audit record instead of surfacing as an
        # unhandled error with no trail. The recheck guard prevents recursion:
        # the escalation itself is built with enforcement off.
        if self.verify_invariants and not _invariant_recheck:
            violations = [
                r for r in check_all_invariants(obs, report) if r.violated
            ]
            if violations:
                return self._escalate_invariant_violation(
                    violations, obs, credal=credal, raw_obs=raw_obs
                )
        return report

    def _escalate_invariant_violation(
        self,
        violations: list["InvariantResult"],
        obs: PolicyObservation,
        *,
        credal: CredalEnvelope | None,
        raw_obs: PolicyObservation | None,
    ) -> DecisionReport:
        """Replace a decision that broke an invariant with a human escalation.

        The violated invariant names are carried in the report's explanation so
        the audit record says which guarantee failed, not merely that one did.
        """
        names = ", ".join(sorted(v.invariant_name for v in violations))
        report = self._build(
            DecisionAction.ESCALATE,
            [DecisionReason.INVARIANT_VIOLATION_ESCALATE],
            obs,
            credal=credal,
            raw_obs=raw_obs,
            _invariant_recheck=True,
        )
        return replace(
            report,
            explanation=(
                "Decision withdrawn: policy invariant violated "
                f"({names}). Routed to human review."
            ),
        )

    def _source_of_decision(self, reasons: list[DecisionReason]) -> str:
        priority = [
            (DecisionReason.COUNTERFACTUAL_FAILED,       "hard_block"),
            (DecisionReason.EVIDENCE_CONTRADICTED,       "hard_block"),
            (DecisionReason.ADMISSION_FIREWALL_BLOCKED,  "hard_block"),
            (DecisionReason.MALFORMED_CALL_BLOCKED,      "hard_block"),
            (DecisionReason.FORBIDDEN_TOOL_BLOCKED,      "hard_block"),
            (DecisionReason.COERCION_BLOCKED,             "coercion"),
            (DecisionReason.BLACKMAIL_BLOCKED,            "coercion"),
            (DecisionReason.MINIMAX_ESCALATE,            "credal_minimax"),
            (DecisionReason.TRAP_ESCALATE,               "trap_avoidance"),
            (DecisionReason.TRAP_VERIFY,                 "trap_avoidance"),
            (DecisionReason.ROLLBACK_UNAVAILABLE,       "misspecification"),
            (DecisionReason.STATE_TRANSITION_UNCERTAIN, "misspecification"),
            (DecisionReason.ENV_MISMATCH_ESCALATE,      "misspecification"),
            (DecisionReason.ENV_CONFIDENCE_VERIFY,      "misspecification"),
            (DecisionReason.CRITICAL_ALTERNATIVE,       "misspecification"),
            (DecisionReason.HIGH_RISK_ALTERNATIVE,      "misspecification"),
            (DecisionReason.LOW_CLASSIFICATION_CONF,    "misspecification"),
            (DecisionReason.MISSPECIFICATION_VERIFY,    "misspecification"),
            (DecisionReason.SESSION_RISK_VERIFY,          "session_risk"),
            (DecisionReason.SESSION_FLOOD_VERIFY,         "session_risk"),
            (DecisionReason.FLEET_SYSTEMIC_VERIFY,        "policy_generalization"),
            (DecisionReason.POLICY_GENERALIZATION_VERIFY, "policy_generalization"),
            (DecisionReason.SIMILAR_ACTION_FLOOD_VERIFY,  "policy_generalization"),
            (DecisionReason.TAINTED_ARGUMENT_VERIFY,     "taint_floor"),
            (DecisionReason.TOOL_NOT_IN_AVAILABLE_SET,   "tool_set_membership"),
            (DecisionReason.TEMPERATURE_ACCEPT,          "temperature_threshold"),
            (DecisionReason.CONFORMAL_ACCEPT,            "conformal"),
            (DecisionReason.DISTRIBUTION_SHIFT,          "calibration_shift"),
            (DecisionReason.EVIDENCE_SUPPORTED,          "evidence"),
            (DecisionReason.CRITICAL_PHASE,              "phase"),
            (DecisionReason.DISORDERED_NO_EVIDENCE,      "phase"),
            (DecisionReason.THERMO_REQUIRE_EVIDENCE,     "evidence"),
            (DecisionReason.ORDERED_HIGH_TRUST,          "trust"),
            (DecisionReason.AMBIGUITY_PENALTY,           "credal_ambiguity"),
        ]
        for reason, source in priority:
            if reason in reasons:
                return source
        return "default"
