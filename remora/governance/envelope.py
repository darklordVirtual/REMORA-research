"""DecisionEnvelope v2 — canonical decision contract for REMORA.

This module defines the shared envelope schema used by both the backend
consensus engine and the frontend Control Room.  Using a single
source-of-truth contract prevents frontend/backend drift and makes the
decision pipeline auditable end-to-end.

Schema design
-------------
The envelope is intentionally flat at the top level (request, assessment,
gate, reviewer_context, follow_up, history, policy_learning, audit) so
that serialisation to JSON, RDF, or JSONL is a simple ``dataclasses.asdict``
call with no nested Pydantic magic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.causal.explanation import CausalExplanation


@dataclass(frozen=True)
class RequestBlock:
    """Operational context for the decision."""

    request_id: str
    domain: str
    risk_tier: str
    proposed_action: str
    action_type: str
    target_environment: str


@dataclass(frozen=True)
class AssessmentBlock:
    """Quantitative assessment produced by the REMORA engine."""

    oracle_votes: list[dict[str, Any]]
    thermodynamic: dict[str, Any]
    evidence_quality: dict[str, Any]
    policy_triggers: list[str]


@dataclass(frozen=True)
class GateBlock:
    """Authoritative gate decision — the single source of truth."""

    outcome: str
    blocked_action: str | None = None
    allowed_next_steps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewerContextBlock:
    """Human-readable context for the reviewer."""

    asset: dict[str, Any] = field(default_factory=dict)
    missing_critical_data: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FollowUpBlock:
    """Follow-up workflow state."""

    required: bool = False
    type: str | None = None
    requested_evidence: list[str] = field(default_factory=list)
    sla_hours: int | None = None


@dataclass(frozen=True)
class HistoryBlock:
    """Case-memory and pattern detection."""

    similar_cases_found: int = 0
    decision_pattern: dict[str, Any] = field(default_factory=dict)
    known_blockers: list[str] = field(default_factory=list)
    # PR-12: flag whether similar_cases data is from live case history
    # or generated synthetically for demonstration / testing.  Consumers
    # and audit records must surface this to avoid treating synthetic
    # data as real precedent.
    synthetic: bool = True


@dataclass(frozen=True)
class PolicyLearningBlock:
    """Safe policy update proposals."""

    candidate_rule_update: bool = False
    requires_policy_owner_approval: bool = True


@dataclass(frozen=True)
class AuditBlock:
    """Tamper-evident audit metadata (frozen dataclass; integrity via SHA-256 hash-chain).

    Fields
    ------
    policy_version:      Version string from RemoraDecisionEngine.
    hash:                SHA-256 of canonical safety-relevant request fields.
    previous_hash:       Prior envelope hash for this tenant (hash-chain linkage).
    signature:           HMAC-SHA256 of hash when REMORA_ENVELOPE_SIGNING_KEY is set.
    schema_version:      Envelope schema version (always "2" for v2 envelopes).
    timestamp_utc:       UTC ISO-8601 decision timestamp (server clock; not RFC 3161).
    tenant_id:           Tenant the decision belongs to.
    actor_identity:      Caller/service-principal from X-Remora-Actor header.
    policy_bundle_hash:  SHA-256 composite of active policy files.
    tool_args_hash:      SHA-256 of (proposed_action, action_type) — proves what was
                         assessed without storing the full action text in the hash-chain.
    data_classification: e.g. "confidential", "restricted" (set by integration layer).
    retention_policy:    e.g. "7y", "legal_hold" (set by integration layer).

    Roadmap gaps (require external infrastructure):
    - approver_identity: OIDC/JWT-bound approver identity (needs IdP integration).
    - kms_key_id:        KMS/HSM signing key reference (needs AWS KMS / Azure Key Vault).
    - tsa_timestamp:     RFC 3161 trusted-timestamp token (needs external TSA).
    """

    policy_version: str = ""
    hash: str | None = None
    previous_hash: str | None = None
    signature: str | None = None
    schema_version: str = "2"
    timestamp_utc: str | None = None
    tenant_id: str | None = None
    actor_identity: str | None = None
    policy_bundle_hash: str | None = None
    tool_args_hash: str | None = None
    data_classification: str | None = None
    retention_policy: str | None = None


@dataclass(frozen=True)
class DecisionEnvelope:
    """Top-level v2 envelope — the canonical decision contract.

    All sub-blocks are immutable and JSON-serialisable.
    """

    request: RequestBlock
    assessment: AssessmentBlock
    gate: GateBlock
    reviewer_context: ReviewerContextBlock = field(
        default_factory=ReviewerContextBlock
    )
    follow_up: FollowUpBlock = field(default_factory=FollowUpBlock)
    history: HistoryBlock = field(default_factory=HistoryBlock)
    policy_learning: PolicyLearningBlock = field(
        default_factory=PolicyLearningBlock
    )
    audit: AuditBlock = field(default_factory=AuditBlock)
    # Optional causal explanation — populated by generate_explanation() when
    # the caller requests a policy-only counterfactual analysis.
    # decision_scope is always "policy_only"; see remora.causal.explanation.
    causal_explanation: "CausalExplanation | None" = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain JSON-compatible dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DecisionEnvelope":
        """Deserialise from a plain dict (minimal — no deep validation)."""
        return cls(
            request=RequestBlock(**d["request"]),
            assessment=AssessmentBlock(**d["assessment"]),
            gate=GateBlock(**d["gate"]),
            reviewer_context=ReviewerContextBlock(
                **d.get("reviewer_context", {})
            ),
            follow_up=FollowUpBlock(**d.get("follow_up", {})),
            history=HistoryBlock(**d.get("history", {})),
            policy_learning=PolicyLearningBlock(
                **d.get("policy_learning", {})
            ),
            audit=AuditBlock(**d.get("audit", {})),
        )

    def envelope_hash(self) -> str:
        """Compute a deterministic SHA-256 hash over canonical safety-relevant fields.

        The hash covers request_id, domain, action_type, risk_tier, proposed_action,
        verdict, and policy_triggers. Same inputs always produce the same hash.
        The canonical payload uses sorted keys and no extra whitespace.
        """
        canonical = json.dumps({
            "request_id":      self.request.request_id,
            "domain":          self.request.domain,
            "action_type":     self.request.action_type,
            "risk_tier":       self.request.risk_tier,
            "proposed_action": self.request.proposed_action,
            "verdict":         self.gate.outcome,
            "policy_triggers": sorted(self.assessment.policy_triggers),
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_flat_dict(self) -> dict[str, Any]:
        """Return a flat dict with canonical fields for external audit consumers.

        All safety-relevant fields are at the top level. This is the format
        external reviewers, audit systems, and SIEM tools should consume.
        """
        thermo = self.assessment.thermodynamic
        return {
            "request_id":         self.request.request_id,
            "domain":             self.request.domain,
            "action_type":        self.request.action_type,
            "risk_tier":          self.request.risk_tier,
            "proposed_action":    self.request.proposed_action,
            "target_environment": self.request.target_environment,
            "verdict":            self.gate.outcome,
            "blocked_action":     self.gate.blocked_action,
            "policy_triggers":    list(self.assessment.policy_triggers),
            "oracle_votes":       list(self.assessment.oracle_votes),
            "trust_score":        thermo.get("trust_score"),
            "entropy_h":          thermo.get("entropy_H"),
            "dissensus_d":        thermo.get("dissensus_D"),
            "policy_version":      self.audit.policy_version,
            "previous_hash":       self.audit.previous_hash,
            "envelope_hash":       self.envelope_hash(),
            "schema_version":      self.audit.schema_version,
            "timestamp_utc":       self.audit.timestamp_utc,
            "tenant_id":           self.audit.tenant_id,
            "actor_identity":      self.audit.actor_identity,
            "policy_bundle_hash":  self.audit.policy_bundle_hash,
            "tool_args_hash":      self.audit.tool_args_hash,
            "data_classification": self.audit.data_classification,
            "retention_policy":    self.audit.retention_policy,
        }


_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "decision_envelope_schema.yaml"


def load_decision_envelope_schema() -> dict[str, Any]:
    """Load the versioned DecisionEnvelope schema contract from repository."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _is_instance_for_schema_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _matches_schema_type(value: Any, schema_type: Any) -> bool:
    if isinstance(schema_type, str):
        return _is_instance_for_schema_type(value, schema_type)
    if isinstance(schema_type, list):
        return any(_is_instance_for_schema_type(value, t) for t in schema_type)
    return True


def _validate_schema_subset(
    value: Any,
    schema: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    schema_type = schema.get("type")
    if schema_type is not None and not _matches_schema_type(value, schema_type):
        errors.append(f"{path}: expected {schema_type}, got {type(value).__name__}")
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']!r}")

    if schema_type == "object":
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        additional_properties = schema.get("additionalProperties", True)

        for req_key in required:
            if req_key not in value:
                errors.append(f"{path}: missing required property {req_key!r}")

        for key, prop_value in value.items():
            if key in properties:
                _validate_schema_subset(
                    prop_value,
                    properties[key],
                    f"{path}.{key}",
                    errors,
                )
            elif additional_properties is False:
                errors.append(f"{path}: unexpected property {key!r}")
            elif isinstance(additional_properties, dict):
                _validate_schema_subset(
                    prop_value,
                    additional_properties,
                    f"{path}.{key}",
                    errors,
                )

    if schema_type == "array":
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for idx, item in enumerate(value):
                _validate_schema_subset(item, items_schema, f"{path}[{idx}]", errors)


def validate_decision_envelope_dict(payload: dict[str, Any]) -> list[str]:
    """Validate payload against the repository schema contract.

    This validator supports the schema subset used by REMORA's envelope contract
    (type, required, properties, items, enum, additionalProperties).
    """
    schema = load_decision_envelope_schema()
    errors: list[str] = []
    _validate_schema_subset(payload, schema, "$", errors)
    return errors
