"""OPA/Rego integration adapter for enterprise multi-team policy governance.

Why OPA
-------
REMORA's Python decision engine is authoritative for single-team deployments,
but enterprises running dozens of Claude agents across different business units
need policy-as-code that:

1. Lives in a version-controlled Rego repository, not inside Python.
2. Is evaluated by a hardened, audited policy daemon (OPA) — not application
   logic that can be patched or bypassed by developers.
3. Produces a structured JSON decision that can be audited, replayed, and
   diffed against policy changes without re-running the model.

This module provides a drop-in adapter that:
- Serialises a ``PolicyObservation`` into an OPA input document.
- POSTs to the OPA REST API (``/v1/data/remora/policy/decision``).
- Maps the OPA result back to a ``DecisionReport`` understood by the rest of
  REMORA's pipeline.
- Falls back to the Python engine if the OPA server is unreachable, so the
  system stays live during a policy daemon outage.

Usage
-----
::

    from remora.policy.opa_adapter import OPAAdapter
    from remora.policy.decision_engine import RemoraDecisionEngine

    adapter = OPAAdapter(
        opa_url="http://opa.internal:8181",
        fallback_engine=RemoraDecisionEngine(conformal_trust_threshold=0.72),
    )
    report, fallback_used = adapter.evaluate(obs)
    if fallback_used:
        logger.warning("OPA unavailable — used Python fallback")

OPA Rego skeleton
-----------------
See ``artifacts/credibility-pack/policy-model.md`` for the complete Rego
package that mirrors the Python decision engine logic, and
``datasets/remora_knowledge_v1/policies/rego_examples/remora_action_gate.rego``
for a runnable example.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclasses_fields
from typing import Any

from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport


# PolicyObservation fields that are deliberately NOT exported to OPA.
# These are audit/correlation metadata with no role in policy evaluation.
# tests/test_opa_parity.py enforces that every field the decision path reads
# is either exported by OPAContext or listed here with a justification.
OPA_EXPORT_EXCLUSIONS: frozenset[str] = frozenset({
    "session_id",               # audit correlation only — engine docstring: not used in gate logic
    "evidence_provenance",      # free-form provenance dict; audit only
    "evidence_timestamp",       # audit only
    "evidence_request_reason",  # human-readable annotation; audit only
    "gainability_score",        # v4 routing signal; not read by the decision engine
})


@dataclass(frozen=True)
class OPAContext:
    """JSON-serialisable input document for OPA policy evaluation.

    This is the canonical "input" object that the Rego package receives.
    It exports every ``PolicyObservation`` field the decision path
    (``decision_engine``, ``credal``, ``trap_classifier``) reads, so a Rego
    policy can express any guard the Python engine can. Audit-only fields are
    excluded and enumerated in ``OPA_EXPORT_EXCLUSIONS``. Parity is enforced
    structurally by ``tests/test_opa_parity.py`` — a new engine guard on an
    unexported field fails CI.

    Optional fields use ``None`` so the Rego policy can distinguish
    "not provided" from "zero". Note the Rego idiom: ``not input.flag``
    succeeds when a field is absent — policies must therefore be written
    against this full contract, and the adapter additionally enforces the
    hard-guard floor (see ``OPAAdapter.evaluate``) so a policy that ignores
    a security signal can never downgrade below the Python engine's
    hard-block verdict.
    """

    # Proposed action (also used by keyword-gating policies)
    question: str
    tool_call_hash: str | None

    # Thermodynamic / consensus state
    trust_score: float | None
    phase: str | None
    temperature: float | None
    order_parameter: float | None
    susceptibility: float | None
    hallucination_bound: float | None
    weighted_support: float | None
    majority_support: float | None
    final_V: float | None
    final_H: float | None
    final_D: float | None

    # Policy flags
    require_rag: bool
    refuse_parametric_verdict: bool
    distribution_shift_detected: bool
    conformal_score: float | None

    # Evidence pipeline
    evidence_action: str | None
    evidence_confidence: float | None
    evidence_supporters: int | None
    evidence_contradictions: int | None
    evidence_signal_source: str

    # Claim-graph topology
    claim_graph_betti_0: int | None
    claim_graph_betti_1: int | None
    contradiction_cycles: int | None

    # Counterfactual gate
    counterfactual_passed: bool | None

    # Assurance trace anchor — lets a Rego policy require a committed audit
    # trace before permitting high-risk actions.
    assurance_root: str | None

    # Operational context
    risk_tier: str | None
    domain: str | None
    action_type: str | None
    target_environment: str | None

    # Oracle health
    oracle_failures: int
    valid_oracle_count: int

    # Security hard-block signals — absence of any of these previously allowed
    # an OPA policy to approve actions the Python engine hard-blocks.
    adversarial_detected: bool
    schema_valid: bool | None
    tool_forbidden: bool
    argument_tainted: bool
    coercion_detected: bool
    blackmail_pattern_detected: bool

    # Misspecification context
    environment_confidence: float | None
    environment_mismatch_detected: bool
    rollback_available: bool | None
    state_transition_uncertain: bool
    classification_confidence: float | None
    classification_alternatives: list[str] | None
    model_misspecification_risk: float | None

    # Fleet / session risk
    similar_action_seen_count: int | None
    policy_generalization_risk: float | None
    fleet_level_effect: str | None
    session_action_count: int | None
    session_cumulative_risk: float | None

    def to_opa_input(self) -> dict[str, Any]:
        """Return the ``{"input": {...}}`` envelope expected by the OPA REST API."""
        return {"input": asdict(self)}


def export_opa_context(obs: PolicyObservation) -> OPAContext:
    """Extract a JSON-serialisable OPAContext from a PolicyObservation.

    Built field-by-field from the observation; the field set is the full
    decision-path contract (see ``OPAContext`` docstring). Structural parity
    with the engine is enforced by ``tests/test_opa_parity.py``.
    """
    field_names = {f.name for f in dataclasses_fields(OPAContext)}
    values = {name: getattr(obs, name) for name in field_names}
    return OPAContext(**values)


class OPAAdapter:
    """Evaluates REMORA policy via OPA, with Python fallback.

    Parameters
    ----------
    opa_url:
        Base URL of the OPA REST API (e.g. ``http://localhost:8181``).
    policy_path:
        OPA API path for the decision rule.  Defaults to
        ``/v1/data/remora/policy/decision``.
    timeout_seconds:
        HTTP connect+read timeout.  Keep below 0.5 s for latency-sensitive
        paths — OPA is designed to respond in < 1 ms for compiled bundles.
    fallback_engine:
        ``RemoraDecisionEngine`` instance used when OPA is unreachable.
        If ``None``, a default engine is constructed on first use.
    """

    DEFAULT_POLICY_PATH = "/v1/data/remora/policy/decision"

    # SEC-4: Restrict OPA URL to safe schemes and reject cloud-metadata endpoints.
    # This prevents SSRF attacks where an attacker could provide a crafted opa_url
    # pointing to internal cloud infrastructure (169.254.169.254, etc.).
    _ALLOWED_SCHEMES = {"http", "https"}
    _BLOCKED_HOSTS = {
        "169.254.169.254",   # AWS/GCP/Azure instance metadata
        "metadata.google.internal",
        "169.254.170.2",     # ECS metadata
        "fd00:ec2::254",     # IPv6 metadata
    }

    def __init__(
        self,
        opa_url: str = "http://localhost:8181",
        policy_path: str | None = None,
        timeout_seconds: float = 1.0,
        fallback_engine: Any = None,
        fail_closed_risk_tiers: tuple[str, ...] = ("high", "critical"),
    ) -> None:
        self._validate_opa_url(opa_url)
        self.opa_url = opa_url.rstrip("/")
        self.policy_path = policy_path or self.DEFAULT_POLICY_PATH
        self.timeout_seconds = timeout_seconds
        self._fallback = fallback_engine
        self._fail_closed_risk_tiers = {tier.lower() for tier in fail_closed_risk_tiers}

    @classmethod
    def _validate_opa_url(cls, url: str) -> None:
        """SEC-4: Validate OPA URL against allowed schemes and blocked hosts."""
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in cls._ALLOWED_SCHEMES:
            raise ValueError(
                f"OPA URL scheme '{scheme}' not allowed. Use http or https."
            )
        host = parsed.hostname or ""
        if host.lower() in cls._BLOCKED_HOSTS:
            raise ValueError(
                f"OPA URL host '{host}' is blocked (cloud metadata endpoint)."
            )

    @property
    def endpoint(self) -> str:
        return self.opa_url + self.policy_path

    def evaluate(self, obs: PolicyObservation) -> tuple[DecisionReport, bool]:
        """Evaluate policy for a ``PolicyObservation``.

        Returns
        -------
        report : DecisionReport
        fallback_used : bool
            ``True`` when the Python engine was used because OPA was unavailable.
        """
        ctx = export_opa_context(obs)
        payload = json.dumps(ctx.to_opa_input()).encode("utf-8")

        try:
            req = urllib.request.Request(
                self.endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            # Fail closed on structurally malformed responses: valid JSON that
            # is not an object (list, string, number) must not raise an
            # uncaught AttributeError — route into the outage/fallback path.
            if not isinstance(body, dict):
                raise ValueError(f"OPA response is not an object: {type(body).__name__}")
            result = body.get("result") or {}
            if not isinstance(result, dict):
                raise ValueError(f"OPA result is not an object: {type(result).__name__}")
            report = self._opa_result_to_report(result, obs)
            return self._apply_decision_floor(report, obs), False
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            pass

        from remora.policy.decision_engine import _normalize_risk_tier
        if _normalize_risk_tier(obs.risk_tier) in self._fail_closed_risk_tiers:
            return self._fail_closed_on_opa_outage(obs), True

        report = self._python_fallback(obs)
        # Stamp fallback_used on the report so audit consumers can see it.
        from dataclasses import replace as _replace
        return _replace(report, fallback_used=True), True

    # Severity ordering for decision monotonicity (REM-003 extended to
    # adapters): an external policy result may tighten but never loosen
    # relative to the Python engine's hard-guard floor.
    _ACTION_SEVERITY = {
        DecisionAction.ACCEPT: 0,
        DecisionAction.VERIFY: 1,
        DecisionAction.ABSTAIN: 2,
        DecisionAction.ESCALATE: 3,
    }

    def _apply_decision_floor(
        self, report: DecisionReport, obs: PolicyObservation
    ) -> DecisionReport:
        """Enforce decision monotonicity over an OPA result, in two tiers.

        1. **Hard-guard floor (all risk tiers):** ``hard_guard_floor`` is the
           same function the engine's own decide() uses as its first stage,
           so this cannot drift from engine behaviour. A Rego policy that
           predates a security signal can tighten but never loosen.
        2. **Full-engine floor (high/critical risk):** for the fail-closed
           risk tiers, the *entire* Python decision — including conditional
           gates such as the production-write matrix, missing rollback,
           oracle quorum, and misspecification checks — is a monotone floor.
           An external policy may therefore only relax decisions in the
           low/medium band; on high/critical risk it can only tighten.

        If the OPA action is at least as severe as the applicable floor, the
        OPA result stands unchanged. Otherwise the floor wins and the
        override is recorded in the report for audit consumers.
        """
        from dataclasses import replace as _replace

        from remora.policy.decision_engine import (
            _normalize_risk_tier,
            hard_guard_floor,
        )

        floor = hard_guard_floor(obs)
        floor_action: DecisionAction | None = floor[0] if floor else None
        floor_desc = floor[1].value if floor else None
        floor_reasons: tuple = (floor[1],) if floor else ()
        floor_source = "opa_hard_guard_floor"

        # Same fail-closed normalisation as the engine: strips whitespace and
        # maps unknown values to "unknown", so ' HIGH ' cannot bypass the floor.
        risk_tier = _normalize_risk_tier(obs.risk_tier)
        if risk_tier in self._fail_closed_risk_tiers:
            engine_report = self._python_fallback(obs)
            if (
                floor_action is None
                or self._ACTION_SEVERITY[engine_report.action]
                > self._ACTION_SEVERITY[floor_action]
            ):
                floor_action = engine_report.action
                floor_desc = ", ".join(r.value for r in engine_report.reasons)
                floor_reasons = engine_report.reasons
                floor_source = "opa_engine_floor"

        if floor_action is None:
            return report
        if self._ACTION_SEVERITY[report.action] >= self._ACTION_SEVERITY[floor_action]:
            return report
        return _replace(
            report,
            action=floor_action,
            reasons=floor_reasons + report.reasons,
            evidence_required=True,
            human_review_required=(
                floor_action in {DecisionAction.ESCALATE, DecisionAction.VERIFY}
                or risk_tier == "critical"
            ),
            source_of_decision=floor_source,
            explanation=(
                f"OPA returned '{report.action.value}' but the decision floor "
                f"requires '{floor_action.value}' ({floor_desc}). "
                "Decision monotonicity: an external policy cannot downgrade "
                "below the engine's hard blocks (any risk tier) or below the "
                "full engine decision (high/critical risk). "
                "Original OPA explanation: " + report.explanation
            ),
        )

    def _fail_closed_on_opa_outage(self, obs: PolicyObservation) -> DecisionReport:
        """Conservative fail-closed path for high-stakes OPA outages."""
        from remora.policy.decision_engine import _normalize_risk_tier
        critical = _normalize_risk_tier(obs.risk_tier) == "critical"
        action = DecisionAction.ESCALATE if critical else DecisionAction.VERIFY
        return DecisionReport(
            action=action,
            reasons=(DecisionReason.DEFAULT_SAFE_ABSTAIN,),
            risk_estimate=1.0 if critical else 0.8,
            confidence=0.0,
            coverage_policy=f"opa:{self.endpoint}",
            evidence_required=True,
            human_review_required=True,
            audit_root=obs.assurance_root,
            explanation=(
                "OPA unavailable; fail-closed policy enforced for "
                f"risk_tier='{obs.risk_tier or 'unknown'}'."
            ),
            raw_observation=obs,
            source_of_decision="opa_fail_closed",
            policy_version="opa-fallback-fail-closed-v1",
            fallback_used=True,
        )

    def _python_fallback(self, obs: PolicyObservation) -> DecisionReport:
        if self._fallback is not None:
            return self._fallback.decide(obs)
        from remora.policy.decision_engine import RemoraDecisionEngine
        return RemoraDecisionEngine().decide(obs)

    def _opa_result_to_report(
        self, result: dict[str, Any], obs: PolicyObservation
    ) -> DecisionReport:
        """Map an OPA result dict back to a ``DecisionReport``."""
        action_str = result.get("action", "abstain")
        try:
            action = DecisionAction(action_str)
        except ValueError:
            action = DecisionAction.ABSTAIN

        reasons: list[DecisionReason] = []
        for r in result.get("reasons") or []:
            try:
                reasons.append(DecisionReason(r))
            except ValueError:
                pass
        if not reasons:
            reasons = [DecisionReason.DEFAULT_SAFE_ABSTAIN]

        return DecisionReport(
            action=action,
            reasons=tuple(reasons),
            risk_estimate=result.get("risk_estimate"),
            confidence=result.get("confidence"),
            coverage_policy=f"opa:{self.endpoint}",
            evidence_required=action != DecisionAction.ACCEPT,
            # Parity with Python engine: human review required for ESCALATE, VERIFY,
            # or any critical-risk observation — not only ESCALATE.
            human_review_required=(
                action in {DecisionAction.ESCALATE, DecisionAction.VERIFY}
                or _normalize_tier_for_review(obs.risk_tier) == "critical"
            ),
            audit_root=obs.assurance_root,
            explanation=result.get(
                "explanation", "Evaluated by OPA policy daemon."
            ),
            raw_observation=obs,
            source_of_decision="opa",
            policy_version=result.get("policy_version", "opa-remora-v1"),
        )


def _normalize_tier_for_review(tier: str | None) -> str:
    """Engine-identical risk-tier normalisation (strip + validate)."""
    from remora.policy.decision_engine import _normalize_risk_tier
    return _normalize_risk_tier(tier)


# ---------------------------------------------------------------------------
# Convenience function — simple ALLOW/DENY interface
# ---------------------------------------------------------------------------

def query_opa_policy(
    trust_score: float,
    phase: str,
    intent: str,
    opa_url: str = "http://localhost:8181",
    policy_path: str = "/v1/data/remora/policy",
    timeout_seconds: float = 1.0,
) -> str:
    """Query OPA for an ALLOW/DENY decision on a (trust_score, phase, intent) tuple.

    Sends a POST to ``{opa_url}{policy_path}`` with the input document::

        {"input": {"trust_score": ..., "phase": ..., "intent": ...}}

    OPA must have a rule ``allow`` or ``action`` at that path returning a
    boolean or the string ``"allow"``/``"deny"``.

    Returns
    -------
    str
        ``"ALLOW"`` if the policy permits the action, ``"DENY"`` otherwise.
        Falls back to ``"DENY"`` when the OPA server is unreachable
        (fail-closed — callers receive a safe default).
    """
    endpoint = opa_url.rstrip("/") + policy_path
    payload = json.dumps({
        "input": {
            "trust_score": trust_score,
            "phase": phase,
            "intent": intent,
        }
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        result = body.get("result") or {}
        if isinstance(result, dict):
            allow = result.get("allow", result.get("action"))
            if allow is None:
                # Fail-closed: an empty result means the queried rule is
                # undefined at this policy path (OPA returns {} for a missing
                # package/rule). A misconfigured policy_path must deny, not allow.
                return "DENY"
            if allow is False or str(allow).lower() in {"deny", "false"}:
                return "DENY"
            return "ALLOW"
        if result is True:
            return "ALLOW"
        return "DENY"  # fail-closed: non-dict, non-True result is not an explicit allow
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return "DENY"  # fail-closed: OPA server unreachable
