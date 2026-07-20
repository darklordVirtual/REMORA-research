# Author: Stian Skogbrott
# License: Apache-2.0
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
from dataclasses import dataclass
from typing import Any

from remora.credal import (
    MINIMAX_ESCALATE_THRESHOLD,
    CredalEnvelope,
    compute_from_obs,
)
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport
from remora.policy.trap_classifier import (
    TRAP_ESCALATE_THRESHOLD,
    TRAP_VERIFY_THRESHOLD,
)
from remora.policy.trap_classifier import (
    score as trap_score,
)

# Minimum number of independent oracle votes required to trust consensus.
# Fewer votes means the oracle pool may be degraded or partially compromised.
# If oracle consultation was attempted (valid_oracle_count > 0 or oracle_failures > 0)
# but fewer than this number of oracles responded, route to human review.
MIN_REQUIRED_ORACLE_VOTES: int = 2

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

    Treats None, empty string, and any unrecognised value as 'unknown' so that
    typos (e.g. "CRITICAL", "high_risk") cannot silently bypass safety gates.
    """
    if tier is None:
        return "unknown"
    normalised = tier.strip().lower()
    return normalised if normalised in _KNOWN_RISK_TIERS else "unknown"


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
        return DecisionAction.VERIFY, DecisionReason.TAINTED_ARGUMENT_VERIFY
    return None


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

@dataclass(frozen=True)
class PolicyRuleEvaluation:
    """Evaluation record for one rule in the decision tree."""
    rule: str
    triggered: bool
    condition: str
    outcome: str | None = None


@dataclass(frozen=True)
class PolicyTrace:
    """Full decision audit trail produced by :meth:`RemoraDecisionEngine.explain`.

    Example::

        trace = engine.explain(obs)
        print(trace.decision_path)          # "ordered_high_trust → ACCEPT"
        for step in trace.rule_evaluations:
            marker = "✓" if step.triggered else "·"
            print(f"  {marker} {step.rule}: {step.condition}")
    """
    action: str
    reasons: tuple[str, ...]
    decision_path: str
    rule_evaluations: tuple[PolicyRuleEvaluation, ...]
    observation_summary: dict[str, Any]
    policy_version: str = "RemoraDecisionEngine-v3"


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
    ) -> None:
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

    def decide(self, obs: PolicyObservation) -> DecisionReport:
        """Gate a proposed action and return an authoritative DecisionReport."""
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
        # VERIFY floor is intentionally last in hard_guard_floor(): the
        # conditional ESCALATE gates further down (critical-phase+critical-risk,
        # rollback, state-transition, production-write matrix) are NOT given
        # priority over it — a tainted critical production write yields VERIFY,
        # not ESCALATE; both block autonomous execution and set
        # human_review_required.

        _floor = hard_guard_floor(obs)

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

        if obs.refuse_parametric_verdict and obs.evidence_action != "answer":
            reasons.append(DecisionReason.THERMO_REQUIRE_EVIDENCE)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.distribution_shift_detected:
            reasons.append(DecisionReason.DISTRIBUTION_SHIFT)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.phase == "critical" and obs.risk_tier == "critical":
            reasons.append(DecisionReason.CRITICAL_PHASE)
            return self._build(DecisionAction.ESCALATE, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # Early misspecification hard blocks — placed before evidence gates so that
        # rollback-unavailable and state-transition-uncertain signals on high/critical
        # risk tiers always escalate even when evidence_action is absent.
        if obs.rollback_available is False and obs.risk_tier in ("high", "critical"):
            reasons.append(DecisionReason.ROLLBACK_UNAVAILABLE)
            return self._build(DecisionAction.ESCALATE, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.state_transition_uncertain and obs.risk_tier in ("high", "critical"):
            reasons.append(DecisionReason.STATE_TRANSITION_UNCERTAIN)
            return self._build(DecisionAction.ESCALATE, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        prod_write_action = self._production_write_outcome(obs)
        if prod_write_action is not None:
            reasons.append(DecisionReason.EVIDENCE_INSUFFICIENT)
            return self._build(prod_write_action, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.risk_tier in ("high", "critical") and obs.evidence_action is None:
            reasons.append(DecisionReason.EVIDENCE_INSUFFICIENT)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.risk_tier == "critical":
            reasons.append(DecisionReason.EVIDENCE_INSUFFICIENT)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── ORACLE QUORUM GATE ───────────────────────────────────────────────
        # Route to human review when oracle consultation was attempted but fewer
        # than MIN_REQUIRED_ORACLE_VOTES independent oracles responded. A partial
        # oracle pool (1 of 3 responding) provides no meaningful consensus signal
        # and cannot be distinguished from a degraded or compromised oracle pool.
        _oracle_attempted = obs.valid_oracle_count > 0 or obs.oracle_failures > 0
        if _oracle_attempted and obs.valid_oracle_count < MIN_REQUIRED_ORACLE_VOTES:
            reasons.append(DecisionReason.INSUFFICIENT_ORACLE_VOTES)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── MINIMAX GATE ─────────────────────────────────────────────────────
        # Escalate when worst-case loss exceeds threshold AND the credal interval
        # is genuinely wide (ambiguity_width >= 0.15) due to oracle disagreement.
        # The width guard prevents escalating on low-trust observations with
        # zero H/D — those are handled correctly by existing ABSTAIN paths.
        if _credal.minimax_should_escalate(MINIMAX_ESCALATE_THRESHOLD) and _credal.ambiguity_width >= 0.15:
            reasons.append(DecisionReason.MINIMAX_ESCALATE)
            return self._build(DecisionAction.ESCALATE, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── TRAP GATE ────────────────────────────────────────────────────────
        # Block or hold irreversible/high-impact actions not caught by the
        # production-write matrix (e.g. disable_security, dns_change, bulk_delete).
        if _trap >= TRAP_ESCALATE_THRESHOLD:
            reasons.append(DecisionReason.TRAP_ESCALATE)
            return self._build(DecisionAction.ESCALATE, reasons, obs, credal=_credal, raw_obs=_raw_obs)
        if _trap >= TRAP_VERIFY_THRESHOLD:
            reasons.append(DecisionReason.TRAP_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── UNKNOWN RISK TIER GATE ───────────────────────────────────────────
        # Actions whose risk tier is absent, a typo, or otherwise unrecognised
        # must not silently reach ACCEPT for explicitly mutating or production-
        # targeting actions.  Actions with an unrecognised/absent action_type are
        # NOT flagged (we can't know if they're mutating), but production-env
        # targeting is always flagged regardless of action_type.
        if obs.risk_tier == "unknown":
            _action_norm = obs.action_type or ""
            _env_norm = obs.target_environment or ""
            if _action_norm in _MUTATING_TYPES or _env_norm in _PROD_ENVS:
                reasons.append(DecisionReason.UNKNOWN_RISK_TIER_VERIFY)
                return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── MISSPECIFICATION GATES ───────────────────────────────────────────
        # P1: Environment misspecification
        if obs.environment_mismatch_detected:
            reasons.append(DecisionReason.ENV_MISMATCH_ESCALATE)
            return self._build(DecisionAction.ESCALATE, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (
            obs.target_environment in _PROD_ENVS
            and obs.environment_confidence is not None
            and obs.environment_confidence < 0.80
            and obs.action_type not in _READ_ONLY_TYPES
        ):
            reasons.append(DecisionReason.ENV_CONFIDENCE_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # P2: Alternative classification
        if obs.classification_alternatives and any(
            a in _CRITICAL_ALT_TYPES for a in obs.classification_alternatives
        ):
            reasons.append(DecisionReason.CRITICAL_ALTERNATIVE)
            return self._build(DecisionAction.ESCALATE, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if obs.classification_alternatives and any(
            a in _HIGH_RISK_ALT_TYPES for a in obs.classification_alternatives
        ):
            reasons.append(DecisionReason.HIGH_RISK_ALTERNATIVE)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (
            obs.classification_confidence is not None
            and obs.classification_confidence < 0.60
            and obs.action_type not in _READ_ONLY_TYPES
        ):
            reasons.append(DecisionReason.LOW_CLASSIFICATION_CONF)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # P3: Misspecification guard
        if (
            obs.model_misspecification_risk is not None
            and obs.model_misspecification_risk > 0.60
            and obs.action_type not in _READ_ONLY_TYPES
        ):
            reasons.append(DecisionReason.MISSPECIFICATION_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── SESSION SEQUENTIAL RISK GATE ────────────────────────────────────
        # Guards against "boiling frog" attacks: individually low-risk actions
        # that accumulate into a critical session-level threat.
        if (obs.session_cumulative_risk is not None
                and obs.session_cumulative_risk > 0.80):
            reasons.append(DecisionReason.SESSION_RISK_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (obs.session_action_count is not None
                and obs.session_action_count > 100):
            reasons.append(DecisionReason.SESSION_FLOOD_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── POLICY GENERALIZATION GATE ───────────────────────────────────────
        # Guards against fleet-scale risk: an action safe for one agent may be
        # dangerous when the same policy fires across many agents or repeated cases.
        if obs.fleet_level_effect in ("systemic", "critical_mass"):
            reasons.append(DecisionReason.FLEET_SYSTEMIC_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (obs.policy_generalization_risk is not None
                and obs.policy_generalization_risk > 0.70):
            reasons.append(DecisionReason.POLICY_GENERALIZATION_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (obs.similar_action_seen_count is not None
                and obs.similar_action_seen_count > 50):
            reasons.append(DecisionReason.SIMILAR_ACTION_FLOOD_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── GAP A+C: EVIDENCE BYPASS WITH INCOMPLETE PIPELINE ───────────────
        # For high/critical risk where evidence_action is set (bypassing the
        # evidence-insufficient gate), the counterfactual gate MUST have run.
        # counterfactual_passed=None means the test was not executed — this is
        # unknown, not safe.  Also covers evidence_contradictions=None (the
        # contradiction-check pipeline did not run) for the same risk tiers.
        if (
            obs.risk_tier in ("high", "critical")
            and obs.evidence_action in ("answer", "evidence_accept")
            and obs.counterfactual_passed is None
        ):
            reasons.append(DecisionReason.COUNTERFACTUAL_UNKNOWN_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── SCHEMA UNVERIFIED FLOOR ─────────────────────────────────────────
        # All higher-priority ESCALATE/VERIFY paths (adversarial, malformed,
        # forbidden, production-write, critical risk, etc.) have been checked.
        # If schema was not validated for a mutating action, force VERIFY here
        # rather than letting the action reach an ACCEPT outcome.
        if _schema_unverified_mutating:
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── UNKNOWN ACTION-TYPE FLOOR ───────────────────────────────────────
        # A non-empty action_type outside the known vocabulary (mutating,
        # read-only, or non-actuating) is an unrecognised actuation type: it
        # must not reach ACCEPT via the conformal/temperature/evidence/
        # ordered-trust paths on a low/medium declared risk tier. Deny-by-
        # default for actuation — route to VERIFY. action_type=None (pure QA /
        # no tool call) is intentionally allowed through.
        _action_norm = (obs.action_type or "").strip().lower()
        if (
            _action_norm
            and _action_norm not in _READ_ONLY_TYPES
            and _action_norm not in _MUTATING_TYPES
            and _action_norm not in _NON_ACTUATING_TYPES
        ):
            reasons.append(DecisionReason.UNKNOWN_ACTION_TYPE_VERIFY)
            return self._build(DecisionAction.VERIFY, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── MONDRIAN PER-PHASE CONFORMAL ────────────────────────────────────

        if (
            self.conformal_phase_thresholds is not None
            and obs.phase in self.conformal_phase_thresholds
            and obs.trust_score is not None
        ):
            thresh = self.conformal_phase_thresholds[obs.phase]
            if obs.trust_score >= thresh:
                reasons.append(DecisionReason.CONFORMAL_ACCEPT)
                return self._build(DecisionAction.ACCEPT, reasons, obs, credal=_credal, raw_obs=_raw_obs)
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
            return self._build(DecisionAction.ACCEPT, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (
            self.temperature_threshold is not None
            and obs.temperature is not None
            and obs.temperature <= self.temperature_threshold
            and obs.counterfactual_passed is not False
            and not (obs.evidence_contradictions or 0)
        ):
            reasons.append(DecisionReason.TEMPERATURE_ACCEPT)
            return self._build(DecisionAction.ACCEPT, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        if (
            obs.evidence_action in ("answer", "evidence_accept")
            and obs.evidence_confidence is not None
            and obs.evidence_confidence >= 0.7
            and not (obs.evidence_contradictions or 0)
            and obs.counterfactual_passed is not False
        ):
            reasons.append(DecisionReason.EVIDENCE_SUPPORTED)
            if obs.phase == "ordered" or (obs.trust_score or 0) >= 0.72:
                return self._build(DecisionAction.ACCEPT, reasons, obs, credal=_credal, raw_obs=_raw_obs)
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
            and _effective_trust >= 0.72
            and obs.counterfactual_passed is not False
            and not (obs.evidence_contradictions or 0)
        ):
            if _credal.adjusted_trust is not None and _credal.adjusted_trust < (obs.trust_score or 0):
                reasons.append(DecisionReason.AMBIGUITY_PENALTY)
            reasons.append(DecisionReason.ORDERED_HIGH_TRUST)
            return self._build(DecisionAction.ACCEPT, reasons, obs, credal=_credal, raw_obs=_raw_obs)

        # ── VERIFY PATHS ────────────────────────────────────────────────────

        # If ambiguity penalty prevented ordered_high_trust ACCEPT (raw trust ≥ 0.72
        # but adjusted_trust dropped below threshold), route to VERIFY rather than
        # falling through to ABSTAIN.  The disagreement warrants human review.
        if (
            obs.phase == "ordered"
            and (obs.trust_score or 0) >= 0.72
            and _credal.adjusted_trust is not None
            and _credal.adjusted_trust < 0.72
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
            and obs.trust_score < 0.2
            and obs.evidence_action != "answer"
        ):
            reasons.append(DecisionReason.LOW_TRUST)
            return self._build(DecisionAction.ABSTAIN, reasons, obs, credal=_credal, raw_obs=_raw_obs)

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
          f"argument_tainted={obs.argument_tainted}",
          "VERIFY")

        r("refuse_parametric",
          bool(obs.refuse_parametric_verdict and obs.evidence_action != "answer"),
          f"refuse_parametric={obs.refuse_parametric_verdict}, evidence_action={obs.evidence_action!r}",
          "VERIFY")

        r("distribution_shift",
          obs.distribution_shift_detected,
          f"distribution_shift_detected={obs.distribution_shift_detected}",
          "VERIFY")

        r("critical_phase_critical_risk",
          obs.phase == "critical" and obs.risk_tier == "critical",
          f"phase={obs.phase!r}, risk_tier={obs.risk_tier!r}",
          "ESCALATE")

        r("rollback_unavailable",
          obs.rollback_available is False and obs.risk_tier in ("high", "critical"),
          f"rollback_available={obs.rollback_available!r}, risk_tier={obs.risk_tier!r}",
          "ESCALATE")

        r("state_transition_uncertain",
          obs.state_transition_uncertain and obs.risk_tier in ("high", "critical"),
          f"state_transition_uncertain={obs.state_transition_uncertain}, risk_tier={obs.risk_tier!r}",
          "ESCALATE")

        write_action = self._production_write_outcome(obs)
        write_outcome = write_action.value.upper() if write_action is not None else "NONE"
        r(
            "production_write_high_or_critical",
            write_action is not None,
            (
                f"action_type={obs.action_type!r}, "
                f"target_environment={obs.target_environment!r}, "
                f"risk_tier={obs.risk_tier!r}"
            ),
            write_outcome,
        )

        r("high_risk_no_evidence",
          obs.risk_tier in ("high", "critical") and obs.evidence_action is None,
          f"risk_tier={obs.risk_tier!r}, evidence_action=None",
          "VERIFY")

        r("critical_risk_hard_verify",
          obs.risk_tier == "critical",
          f"risk_tier={obs.risk_tier!r}",
          "VERIFY")

        _oracle_attempted = obs.valid_oracle_count > 0 or obs.oracle_failures > 0
        r("oracle_quorum_gate",
          _oracle_attempted and obs.valid_oracle_count < MIN_REQUIRED_ORACLE_VOTES,
          f"valid_oracle_count={obs.valid_oracle_count}, "
          f"oracle_failures={obs.oracle_failures}, "
          f"min_required={MIN_REQUIRED_ORACLE_VOTES}",
          "VERIFY")

        _explain_credal = compute_from_obs(obs)
        _explain_trap   = trap_score(obs)

        r("minimax_gate",
          _explain_credal.minimax_should_escalate(MINIMAX_ESCALATE_THRESHOLD)
          and _explain_credal.ambiguity_width >= 0.15,
          f"worst_case_loss={_explain_credal.worst_case_loss:.4f}, "
          f"ambiguity_width={_explain_credal.ambiguity_width:.4f}, "
          f"threshold={MINIMAX_ESCALATE_THRESHOLD}",
          "ESCALATE")

        r("trap_escalate",
          _explain_trap >= TRAP_ESCALATE_THRESHOLD,
          f"trap_score={_explain_trap:.4f}, threshold={TRAP_ESCALATE_THRESHOLD}",
          "ESCALATE")

        r("trap_verify",
          TRAP_VERIFY_THRESHOLD <= _explain_trap < TRAP_ESCALATE_THRESHOLD,
          f"trap_score={_explain_trap:.4f}, "
          f"[{TRAP_VERIFY_THRESHOLD}, {TRAP_ESCALATE_THRESHOLD})",
          "VERIFY")

        r("unknown_risk_tier_verify",
          obs.risk_tier == "unknown"
          and ((obs.action_type or "") in _MUTATING_TYPES
               or (obs.target_environment or "") in _PROD_ENVS),
          f"risk_tier={obs.risk_tier!r}, action_type={obs.action_type!r}, "
          f"target_environment={obs.target_environment!r}",
          "VERIFY")

        r("env_mismatch_escalate",
          obs.environment_mismatch_detected,
          f"environment_mismatch_detected={obs.environment_mismatch_detected}",
          "ESCALATE")

        r("env_confidence_verify",
          (obs.target_environment in _PROD_ENVS
           and obs.environment_confidence is not None
           and obs.environment_confidence < 0.80
           and obs.action_type not in _READ_ONLY_TYPES),
          f"target_environment={obs.target_environment!r}, env_confidence={obs.environment_confidence}",
          "VERIFY")

        r("critical_alternative",
          bool(obs.classification_alternatives and any(
              a in _CRITICAL_ALT_TYPES for a in obs.classification_alternatives)),
          f"classification_alternatives={obs.classification_alternatives!r}",
          "ESCALATE")

        r("high_risk_alternative",
          bool(obs.classification_alternatives and any(
              a in _HIGH_RISK_ALT_TYPES for a in obs.classification_alternatives)),
          f"classification_alternatives={obs.classification_alternatives!r}",
          "VERIFY")

        r("low_classification_conf",
          (obs.classification_confidence is not None
           and obs.classification_confidence < 0.60
           and obs.action_type not in _READ_ONLY_TYPES),
          f"classification_confidence={obs.classification_confidence}, action_type={obs.action_type!r}",
          "VERIFY")

        r("misspecification_verify",
          (obs.model_misspecification_risk is not None
           and obs.model_misspecification_risk > 0.60
           and obs.action_type not in _READ_ONLY_TYPES),
          f"model_misspecification_risk={obs.model_misspecification_risk}, action_type={obs.action_type!r}",
          "VERIFY")

        r("session_risk_verify",
          obs.session_cumulative_risk is not None and obs.session_cumulative_risk > 0.80,
          f"session_cumulative_risk={obs.session_cumulative_risk}",
          "VERIFY")

        r("session_flood_verify",
          obs.session_action_count is not None and obs.session_action_count > 100,
          f"session_action_count={obs.session_action_count}",
          "VERIFY")

        r("fleet_systemic_verify",
          obs.fleet_level_effect in ("systemic", "critical_mass"),
          f"fleet_level_effect={obs.fleet_level_effect!r}",
          "VERIFY")

        r("policy_generalization_verify",
          obs.policy_generalization_risk is not None and obs.policy_generalization_risk > 0.70,
          f"policy_generalization_risk={obs.policy_generalization_risk}",
          "VERIFY")

        r("similar_action_flood_verify",
          obs.similar_action_seen_count is not None and obs.similar_action_seen_count > 50,
          f"similar_action_seen_count={obs.similar_action_seen_count}",
          "VERIFY")

        r("counterfactual_unknown_verify",
          obs.risk_tier in ("high", "critical")
          and obs.evidence_action in ("answer", "evidence_accept")
          and obs.counterfactual_passed is None,
          f"risk_tier={obs.risk_tier!r}, evidence_action={obs.evidence_action!r}, "
          f"counterfactual_passed={obs.counterfactual_passed}",
          "VERIFY")

        _schema_unverified_mutating = (
            obs.schema_valid is None and (obs.action_type or "") in _MUTATING_TYPES
        )
        r("schema_unverified_floor",
          _schema_unverified_mutating,
          f"schema_valid={obs.schema_valid}, action_type={obs.action_type!r}",
          "VERIFY")

        _explain_action_norm = (obs.action_type or "").strip().lower()
        r("unknown_action_type_floor",
          bool(_explain_action_norm)
          and _explain_action_norm not in _READ_ONLY_TYPES
          and _explain_action_norm not in _MUTATING_TYPES
          and _explain_action_norm not in _NON_ACTUATING_TYPES,
          f"action_type={obs.action_type!r} (not in known vocabulary)",
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
              "ACCEPT" if above else "ABSTAIN")

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
              "ACCEPT" if above_marginal else None)

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
              "ACCEPT" if below_temp else None)

        ev_accept = (
            obs.evidence_action in ("answer", "evidence_accept")
            and obs.evidence_confidence is not None
            and obs.evidence_confidence >= 0.7
            and not contradictions
            and obs.counterfactual_passed is not False
        )
        ev_outcome = (
            "ACCEPT"
            if (obs.phase == "ordered" or (obs.trust_score or 0) >= 0.72)
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
            and _effective_trust >= 0.72
            and obs.counterfactual_passed is not False
            and not contradictions
        )
        r("ordered_high_trust",
          ordered_trust,
          f"phase={obs.phase!r}, trust={obs.trust_score}, "
          f"ambiguity_adjusted_trust={_effective_trust:.3f}",
          "ACCEPT")

        r("ambiguity_penalty_verify",
          obs.phase == "ordered"
          and (obs.trust_score or 0) >= 0.72
          and _explain_credal.adjusted_trust is not None
          and _explain_credal.adjusted_trust < 0.72
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
          and obs.trust_score < 0.2
          and obs.evidence_action != "answer",
          f"trust={obs.trust_score}",
          "ABSTAIN")

        r("default_safe_abstain",
          DecisionReason.DEFAULT_SAFE_ABSTAIN in report.reasons,
          "no prior rule matched",
          "ABSTAIN")

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

        return DecisionReport(
            action=action,
            reasons=tuple(reasons),
            risk_estimate=risk_estimate,
            confidence=confidence,
            coverage_policy={
                DecisionAction.ACCEPT: "selective — accepted based on evidence/trust state",
                DecisionAction.VERIFY: "held for verification",
                DecisionAction.ABSTAIN: "abstained — insufficient evidence",
                DecisionAction.ESCALATE: "escalated — hard failure detected",
            }[action],
            evidence_required=evidence_required,
            human_review_required=human_review_required,
            audit_root=obs.assurance_root,
            explanation=explanation_map[action],
            raw_observation=raw_obs if raw_obs is not None else obs,
            source_of_decision=source,
            policy_version="RemoraDecisionEngine-v3",
            in_sample_calibration_warning=(
                "temperature threshold may be in-sample if derived from evaluation artifact"
                if DecisionReason.TEMPERATURE_ACCEPT in reasons and self.temperature_threshold is not None
                else None
            ),
            credal=credal,
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
