"""Human-on-the-Loop Escalation Contract.

When REMORA's decision engine outputs ESCALATE or ABSTAIN on a high-stakes
query, the result must be handed off to a human reviewer.  In a production
enterprise system that handoff needs a well-defined API contract so that:

- Frontend teams can build approval-inbox dashboards without knowing the
  internals of the cascade pipeline.
- Compliance teams can replay, audit, and trace every escalation back to
  the exact thermodynamic state that triggered it.
- Workflow orchestrators (ServiceNow, Jira, Slack workflows) can receive
  structured webhooks and route to the right domain expert.

``EscalationPayload`` is that contract.  It is a JSON-serialisable dataclass
whose schema is published as a static JSON Schema document
(``EscalationPayload.json_schema()``).

Usage
-----
::

    from remora.policy.escalation_contract import build_escalation_payload

    report = engine.decide(obs)
    if report.action in {DecisionAction.ESCALATE, DecisionAction.ABSTAIN}:
        payload = build_escalation_payload(report)
        # POST payload.to_dict() to your approval-inbox API
        webhook_client.post("/escalations", json=payload.to_dict())

JSON Schema
-----------
The schema is version-locked at ``"escalation-v1"`` so consumer dashboards
can validate payloads against it via ``$schema`` negotiation.
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from remora.policy.report import DecisionAction, DecisionReason, DecisionReport

# ---------------------------------------------------------------------------
# Routing hint table
# ---------------------------------------------------------------------------

_DOMAIN_ROUTING: dict[str, str] = {
    "production": "operations_engineer",
    "maintenance": "maintenance_supervisor",
    "hse": "hse_manager",
    "cyber": "soc_analyst",
    "legal": "legal_counsel",
    "procurement": "category_manager",
    "engineering": "discipline_lead",
}

_REASON_ROUTING: dict[DecisionReason, str] = {
    DecisionReason.COUNTERFACTUAL_FAILED: "hard_failure_review",
    DecisionReason.EVIDENCE_CONTRADICTED: "evidence_reconciliation",
    DecisionReason.DISTRIBUTION_SHIFT: "calibration_review",
    DecisionReason.HIGH_CONTRADICTION: "domain_expert",
    DecisionReason.DISORDERED_NO_EVIDENCE: "evidence_acquisition",
    DecisionReason.LOW_TRUST: "confidence_review",
    DecisionReason.DEFAULT_SAFE_ABSTAIN: "triage",
}


def _routing_hint(report: DecisionReport, domain: str | None) -> str:
    if domain and domain.lower() in _DOMAIN_ROUTING:
        return _DOMAIN_ROUTING[domain.lower()]
    for reason in report.reasons:
        if reason in _REASON_ROUTING:
            return _REASON_ROUTING[reason]
    return "triage"


# ---------------------------------------------------------------------------
# EscalationPayload
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThermodynamicSnapshot:
    """Observed thermodynamic state at the time of escalation."""

    temperature: float | None
    entropy: float | None       # H
    dissensus: float | None     # D
    free_energy: float | None   # F = lambda*D - T*H
    phase: str | None


@dataclass(frozen=True)
class EscalationPayload:
    """Structured handoff document for human-on-the-loop review.

    Every ESCALATE or policy-triggered ABSTAIN produces one of these.
    The payload contains everything a human reviewer or workflow system
    needs to understand *why* the AI could not decide autonomously.

    Fields
    ------
    id : str
        UUID for this escalation event.
    schema_version : str
        Always ``"escalation-v1"`` — bump when the schema changes.
    timestamp : str
        ISO-8601 UTC timestamp of the escalation.
    prompt : str
        The original question that triggered the escalation.
    trigger : str
        Canonical reason code (one of the ``DecisionReason`` enum values).
    action : str
        The final decision action: ``"escalate"`` or ``"abstain"``.
    thermodynamics : ThermodynamicSnapshot
        T, H, D, F values and phase label at escalation time.
    trust_score : float | None
        Oracle trust score if available.
    risk_estimate : float | None
        Estimated probability of error (1.0 for hard failures).
    oracle_responses : list[dict]
        Raw oracle responses if provided by the caller (optional).
    recommended_routing : str
        Suggested human recipient (e.g., ``"domain_expert"``, ``"soc_analyst"``).
    policy_version : str
        Policy engine version that produced this escalation.
    audit_root : str | None
        Assurance-trace root hash if available.
    all_reasons : list[str]
        All ``DecisionReason`` values that contributed to this outcome.
    """

    id: str
    schema_version: str
    timestamp: str
    prompt: str
    trigger: str
    action: str
    thermodynamics: ThermodynamicSnapshot
    trust_score: float | None
    risk_estimate: float | None
    recommended_routing: str
    policy_version: str
    all_reasons: list[str]
    oracle_responses: list[dict] = field(default_factory=list)
    audit_root: str | None = None
    domain_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict (use with ``json.dumps``)."""
        d = asdict(self)
        return d

    @staticmethod
    def json_schema() -> dict[str, Any]:
        """Return the JSON Schema document for this payload format.

        Consumers should validate incoming payloads against this schema
        before processing them in approval-inbox or workflow systems.
        """
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://remora.ai/schemas/escalation-v1.json",
            "title": "REMORA Escalation Payload",
            "description": (
                "Structured handoff document produced when REMORA's decision "
                "engine cannot resolve a query autonomously and routes to a "
                "human reviewer."
            ),
            "type": "object",
            "required": [
                "id", "schema_version", "timestamp", "prompt",
                "trigger", "action", "thermodynamics",
                "recommended_routing", "policy_version", "all_reasons",
            ],
            "additionalProperties": False,
            "properties": {
                "id": {
                    "type": "string",
                    "format": "uuid",
                    "description": "UUID for this escalation event.",
                },
                "schema_version": {
                    "type": "string",
                    "const": "escalation-v1",
                },
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "ISO-8601 UTC timestamp.",
                },
                "prompt": {
                    "type": "string",
                    "description": "The original question that triggered escalation.",
                },
                "trigger": {
                    "type": "string",
                    "enum": [r.value for r in DecisionReason],
                    "description": "Primary reason code for the escalation.",
                },
                "action": {
                    "type": "string",
                    "enum": ["escalate", "abstain"],
                },
                "thermodynamics": {
                    "type": "object",
                    "description": "Thermodynamic state snapshot at escalation time.",
                    "properties": {
                        "temperature": {"type": ["number", "null"]},
                        "entropy": {"type": ["number", "null"], "description": "H"},
                        "dissensus": {"type": ["number", "null"], "description": "D"},
                        "free_energy": {"type": ["number", "null"], "description": "F = λD − TH"},
                        "phase": {
                            "type": ["string", "null"],
                            "enum": ["ordered", "critical", "disordered", None],
                        },
                    },
                    "additionalProperties": False,
                },
                "trust_score": {
                    "type": ["number", "null"],
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "risk_estimate": {
                    "type": ["number", "null"],
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "oracle_responses": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Raw oracle responses if available.",
                },
                "recommended_routing": {
                    "type": "string",
                    "description": (
                        "Suggested human recipient type, e.g. 'domain_expert', "
                        "'soc_analyst', 'legal_counsel'."
                    ),
                },
                "policy_version": {
                    "type": "string",
                },
                "all_reasons": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "All DecisionReason values that contributed.",
                },
                "audit_root": {
                    "type": ["string", "null"],
                    "description": "Assurance-trace root hash if available.",
                },
                "domain_hint": {
                    "type": ["string", "null"],
                    "description": "Business domain hint for routing.",
                },
            },
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_escalation_payload(
    report: DecisionReport,
    oracle_responses: list[dict] | None = None,
    domain_hint: str | None = None,
) -> EscalationPayload:
    """Build an EscalationPayload from a DecisionReport.

    Parameters
    ----------
    report:
        The ``DecisionReport`` produced by ``RemoraDecisionEngine.decide()``.
        Must have ``action`` of ESCALATE or ABSTAIN; raises ``ValueError``
        otherwise.
    oracle_responses:
        Optional list of raw oracle response dicts (e.g. from the cascade
        pipeline).  Included verbatim in the payload.
    domain_hint:
        Business domain string (``"hse"``, ``"legal"``, ``"cyber"``, etc.)
        used to look up the recommended routing target.

    Returns
    -------
    EscalationPayload
    """
    if report.action not in {DecisionAction.ESCALATE, DecisionAction.ABSTAIN}:
        raise ValueError(
            f"build_escalation_payload only applies to ESCALATE/ABSTAIN actions, "
            f"got {report.action.value!r}"
        )

    obs = report.raw_observation

    # Primary trigger = first reason
    trigger = report.reasons[0].value if report.reasons else DecisionReason.DEFAULT_SAFE_ABSTAIN.value

    # Thermodynamic snapshot
    F: float | None = None
    if obs.temperature is not None and obs.final_H is not None and obs.final_D is not None:
        F = 1.0 * obs.final_D - obs.temperature * obs.final_H

    thermo = ThermodynamicSnapshot(
        temperature=obs.temperature,
        entropy=obs.final_H,
        dissensus=obs.final_D,
        free_energy=F,
        phase=obs.phase,
    )

    return EscalationPayload(
        id=str(uuid.uuid4()),
        schema_version="escalation-v1",
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        prompt=obs.question,
        trigger=trigger,
        action=report.action.value,
        thermodynamics=thermo,
        trust_score=obs.trust_score,
        risk_estimate=report.risk_estimate,
        oracle_responses=list(oracle_responses or []),
        recommended_routing=_routing_hint(report, domain_hint),
        policy_version=report.policy_version,
        all_reasons=[r.value for r in report.reasons],
        audit_root=report.audit_root,
        domain_hint=domain_hint,
    )
