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
See ``enterprise/policy-model.md`` for the complete Rego package that mirrors
the Python decision engine logic.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport


@dataclass(frozen=True)
class OPAContext:
    """JSON-serialisable input document for OPA policy evaluation.

    This is the canonical "input" object that the Rego package receives.
    All fields map 1-to-1 to ``PolicyObservation`` fields that the decision
    engine uses as guards.  Optional fields use ``None`` so the Rego policy
    can distinguish "not provided" from "zero".
    """

    trust_score: float | None
    phase: str | None
    temperature: float | None
    distribution_shift_detected: bool
    counterfactual_passed: bool | None
    evidence_action: str | None
    evidence_confidence: float | None
    evidence_contradictions: int | None
    contradiction_cycles: int | None
    require_rag: bool
    refuse_parametric_verdict: bool
    claim_graph_betti_1: int | None
    conformal_score: float | None
    # Enterprise risk fields — required for Rego policies that gate on risk tier,
    # domain, or action type (previously absent, causing silent policy no-ops).
    risk_tier: str | None
    domain: str | None
    action_type: str | None
    order_parameter: float | None
    susceptibility: float | None

    def to_opa_input(self) -> dict[str, Any]:
        """Return the ``{"input": {...}}`` envelope expected by the OPA REST API."""
        return {"input": asdict(self)}


def export_opa_context(obs: PolicyObservation) -> OPAContext:
    """Extract a JSON-serialisable OPAContext from a PolicyObservation."""
    return OPAContext(
        trust_score=obs.trust_score,
        phase=obs.phase,
        temperature=obs.temperature,
        distribution_shift_detected=obs.distribution_shift_detected,
        counterfactual_passed=obs.counterfactual_passed,
        evidence_action=obs.evidence_action,
        evidence_confidence=obs.evidence_confidence,
        evidence_contradictions=obs.evidence_contradictions,
        contradiction_cycles=obs.contradiction_cycles,
        require_rag=obs.require_rag,
        refuse_parametric_verdict=obs.refuse_parametric_verdict,
        claim_graph_betti_1=obs.claim_graph_betti_1,
        conformal_score=obs.conformal_score,
        risk_tier=obs.risk_tier,
        domain=obs.domain,
        action_type=obs.action_type,
        order_parameter=obs.order_parameter,
        susceptibility=obs.susceptibility,
    )


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
            result = body.get("result") or {}
            report = self._opa_result_to_report(result, obs)
            return report, False
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            pass

        risk_tier = (obs.risk_tier or "").lower()
        if risk_tier in self._fail_closed_risk_tiers:
            return self._fail_closed_on_opa_outage(obs), True

        report = self._python_fallback(obs)
        # Stamp fallback_used on the report so audit consumers can see it.
        from dataclasses import replace as _replace
        return _replace(report, fallback_used=True), True

    def _fail_closed_on_opa_outage(self, obs: PolicyObservation) -> DecisionReport:
        """Conservative fail-closed path for high-stakes OPA outages."""
        critical = (obs.risk_tier or "").lower() == "critical"
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
                or obs.risk_tier == "critical"
            ),
            audit_root=obs.assurance_root,
            explanation=result.get(
                "explanation", "Evaluated by OPA policy daemon."
            ),
            raw_observation=obs,
            source_of_decision="opa",
            policy_version=result.get("policy_version", "opa-remora-v1"),
        )


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
            allow = result.get("allow", result.get("action", True))
            if allow is False or str(allow).lower() in {"deny", "false"}:
                return "DENY"
        elif result is False:
            return "DENY"
        return "ALLOW"
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return "DENY"  # fail-closed: OPA server unreachable
