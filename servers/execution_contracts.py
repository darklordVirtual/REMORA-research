# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Wire contracts for the /v1/execution API (issue #241, extraction slice 1).

Request/response Pydantic models ONLY — no routing, no orchestration, no
persistence. Moved verbatim from servers/execution_api.py; the OpenAPI schema
is characterization-tested to be byte-identical across the move
(tests/test_execution_contracts_extraction.py).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from remora.governance.effect_verification import EffectStatus

GovernanceAction = Literal["accept", "verify", "abstain", "escalate"]
ExecutionOutcome = Literal["execute", "approval_expired", "binding_refused",
                           "approval_invalidated"]


class ErrorDetail(BaseModel):
    detail: str


class AuditRef(BaseModel):
    sequence_no: int
    entry_hash: str


class SemanticAssessment(BaseModel):
    tool_contract_bundle_hash: str = Field(
        "", description="Empty string means no semantic bundle is configured "
                        "(registry-only path) — recorded, never assumed away.")
    state_hash: str = ""
    intent_authority_hash: str = Field(
        "", description="Empty string when no intent_ref was resolved.")
    tool_matches_goal: bool | None = Field(
        None, description="None means not evaluated; the key is always present.")
    expected_effect_matches: bool | None = Field(
        None, description="None means not evaluated; the key is always present.")


class ExecutionGrant(BaseModel):
    """Signed single-use policy decision token (PolicyDecisionToken)."""

    action: str
    observation_hash: str
    request_id: str
    issued_at: str
    expires_at: str | None
    jti: str
    audience: str
    signature: str
    is_signed: bool


class PepResult(BaseModel):
    allowed: bool
    reason: str = Field(description="e.g. accept, token_already_consumed")


class ToolResultEnvelopeModel(BaseModel):
    sha256: str
    size_bytes: int
    truncated: bool
    preview: Any = None
    media_type: str


class ToolExecutionResult(BaseModel):
    executed: bool
    refusal_reason: str | None = Field(
        None, description="Present only when executed is false: pep_denied, "
                          "policy_bundle_unavailable, lease_unavailable:*, "
                          "tool_failed_nonce_burned, or a dispatcher/lease "
                          "refusal such as unknown_tool, "
                          "nonce_already_consumed, "
                          "nonce_consumed_by_failed_execution (retry after a "
                          "tool that raised — state unknown), "
                          "policy_bundle_mismatch. Canonical reason sets: "
                          "remora/enforcement/lease.py (lease/dispatcher) and "
                          "remora/enforcement/token.py (PEP token reasons, "
                          "surfaced under pep.reason, e.g. token_expired, "
                          "token_not_yet_valid, observation_hash_mismatch, "
                          "token_already_consumed).")
    error: str | None = None
    result: Any = Field(
        None, description="Tool return value (deployment-defined shape); "
                          "present only when executed is true.")
    result_envelope: ToolResultEnvelopeModel | None = None


class ExecutionAssessResponse(BaseModel):
    proposal_id: str = Field(
        description="FT-01: the canonical proposal identity minted here — "
                    "the join key across every chain record, grant and "
                    "response for this action.")
    decision: GovernanceAction
    reasons: list[str]
    tool_call_hash: str
    semantic: SemanticAssessment
    execution_token: ExecutionGrant | None = Field(
        None, description="Present only on accept; key absent otherwise.")
    review_item_id: str | None = Field(
        None, description="Present only on verify/escalate; key absent "
                          "otherwise (abstain has neither).")
    audit: AuditRef


class ExecutionApproveResponse(BaseModel):
    status: Literal["approved"]
    proposal_id: str | None = Field(
        None, description="Canonical proposal identity; null only for items "
                          "enqueued before the lifecycle existed.")
    item_id: str
    expires_at: str
    audit: AuditRef


class ExecutionExecuteResponse(BaseModel):
    proposal_id: str | None = Field(
        None, description="Canonical proposal identity from the queued item; "
                          "null only for pre-lifecycle items.")
    outcome: ExecutionOutcome
    detail: str
    execution_grant: ExecutionGrant | None = Field(
        None, description="Present only when outcome is execute.")
    pep: PepResult | None = Field(
        None, description="Present only when outcome is execute.")
    tool_execution: ToolExecutionResult | None = Field(
        None, description="Present only when outcome is execute.")
    audit: AuditRef


class ExecutionAuditVerifyResponse(BaseModel):
    tenant: str
    valid: bool
    problems: list[str]
    records_checked: int
    empty: bool = Field(
        description="True when no records exist: an empty chain is trivially "
                    "valid and must not pose as verified history.")


_AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail,
          "description": "Missing or invalid bearer token."},
    403: {"model": ErrorDetail,
          "description": "Role lacks the required capability for this tenant."},
}


class DerivationProposal(BaseModel):
    """One proposed derivation receipt (theme 3): value = transform(span).

    A PROPOSAL only — acceptance happens exclusively in
    ``remora.toolcall.routing.derivation.verify_receipt``'s deterministic
    re-execution. ``extra="forbid"``: semantic verdicts or any other
    unknown key cannot ride along inside a receipt.
    """

    argument: str = Field(..., min_length=1, max_length=200)
    value: Any = None
    transform: str = Field(..., min_length=1, max_length=64)
    source_span: str = Field(..., min_length=1, max_length=2000)
    params: dict[str, Any] = Field(default_factory=dict)
    # Optional exact offset binding into the resolved task text (review
    # 2026-08-05 hardening): when both are set, verification requires
    # task_text[source_start:source_end] == source_span.
    source_start: int | None = Field(None, ge=0)
    source_end: int | None = Field(None, ge=0)

    model_config = {"extra": "forbid"}


class ToolCallRequest(BaseModel):
    """The PROPOSAL only (issue #34 trust boundary; full-args binding kept).

    The request carries what the agent proposes: tool, exact arguments,
    requested target. Every authoritative safety signal — risk tier,
    domain, action type, trust, phase, evidence status, schema validity,
    rollback capability — is derived SERVER-SIDE from the tool registry;
    the caller can never assert its way to an ACCEPT. The only inbound
    safety influence permitted is a DOWNGRADE: schema_valid=false or
    rollback_available=false lowers trust; true/None never raises it.
    Legacy pre-#34 fields (trust_score, phase, evidence_action,
    evidence_confidence, risk_tier, domain, action_type) are ignored as
    unknown extras for wire compatibility.
    """

    tool_name: str = Field(..., min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    target_environment: str = "prod"
    schema_valid: bool | None = None       # only false is honored (downgrade)
    rollback_available: bool | None = None  # only false is honored (downgrade)
    idempotency_key: str | None = None
    # SHELF-020: an OPAQUE reference into the deployment's intent source
    # (signed work order, approved workflow template). The intent itself can
    # never ride in this request (task_intent_authority_v1.md §2.3) — the
    # server resolves the reference against a source the caller does not
    # control, so a fabricated intent cannot be delivered alongside the call
    # it would justify.
    intent_ref: str | None = Field(None, max_length=200)
    # Downgrade-only, like schema_valid: declaring untrusted context marks
    # every argument as potentially tainted. Omitting it never raises trust —
    # absence is the same default the legacy path had.
    untrusted_context: str | None = Field(None, max_length=20_000)
    # Theme 3: proposed derivation receipts for derived argument values.
    # Proposals only — verified by deterministic re-execution server-side;
    # an invalid receipt just leaves its value ungrounded.
    derivations: list[DerivationProposal] | None = Field(None, max_length=32)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tool_name": "set_valve_position",
                    "arguments": {"valve": "V-12", "position_pct": 35},
                    "target_environment": "prod",
                    "intent_ref": "WO-1204",
                },
                {
                    "tool_name": "read_sensor",
                    "arguments": {"sensor_id": "PT-101"},
                    "target_environment": "prod",
                    "intent_ref": "MON-ROUND",
                },
            ]
        }
    }


class ApproveRequest(BaseModel):
    item_id: str
    approval_ttl_seconds: int = Field(900, gt=0, le=86400)
    on_behalf_of: str | None = Field(
        None,
        description="Client-declared annotation only, recorded in the audit "
                    "chain as unverified metadata. The audited approver "
                    "identity is always the authenticated principal from the "
                    "bearer token — this field can never delegate authority.")


class ExecuteRequest(BaseModel):
    """Execute an approved item — the FULL payload is re-presented and the
    fresh world state re-gated; the grant is single-use."""

    item_id: str
    tool_call: ToolCallRequest


class DispatchLeasedRequest(BaseModel):
    """Dispatch a call under a lease minted by the AUTHORITY domain (ADR-A).

    The execution domain's only inbound execution surface. It receives a lease
    it did not request and did not sign, together with the call that lease is
    supposed to authorise, and re-verifies the whole binding before anything
    runs.

    Nothing here is trusted because it arrived. The lease signature is checked
    against the PUBLIC verification key -- this domain holds no private key and
    so cannot have produced the lease -- and every bound field is compared to
    the concrete call. A lease for a different tool, tenant, target or argument
    set is refused here exactly as a forged one is.

    ``now`` is carried so the authority's clock decides freshness rather than
    the executor's, which keeps a skewed executor from widening or narrowing a
    lease's usable window.
    """

    lease: dict[str, Any]
    tool_call: ToolCallRequest
    tenant_id: str = ""
    actor_identity: str = ""
    now: str = ""


class ExecuteAcceptedRequest(BaseModel):
    """Redeem an ACCEPT execution token (issue #36).

    The token IS the authorization: it was bound to the exact tool call at
    assess time, so no review item exists or is needed. The full payload is
    re-presented so the server can verify that binding rather than trust
    the caller's word about what was approved.
    """

    execution_token: dict[str, Any]
    tool_call: ToolCallRequest


class RejectRequest(BaseModel):
    """Record a reviewer's refusal of a pending item."""

    item_id: str
    # Mandatory: an unexplained refusal cannot be reviewed after the fact.
    reason: str = Field(..., min_length=1, max_length=2000)


class EffectVerificationRequest(BaseModel):
    """A verification observed by the deployment, submitted for recording.

    Verification runs where the credentials are, which is the product's
    process — REMORA never reaches into a customer's system of record to
    check on it. What crosses back is this record, and the chain stores it
    as an **attestation by a named verifier**, not as an independent proof
    by REMORA. ``verifier_identity`` is therefore mandatory: an
    attestation nobody signed is not evidence, because an auditor could
    not tell who claimed to have looked.

    What changed, and why the extra fields exist: the recorder used to accept
    any status for any existing proposal, so a proposal that was assessed and
    never executed could be recorded EFFECT_VERIFIED. The receipt is now bound
    to a dispatch in the audit chain, and VERIFIED is DERIVED from the digests
    rather than taken from this request. See
    ``remora.governance.effect_receipt``.
    """

    execution_id: str = Field(..., min_length=1, max_length=200)
    tool_id: str = Field(..., min_length=1, max_length=200)
    toolspec_hash: str = Field("", max_length=128)
    tool_call_hash: str = Field(
        "", max_length=64, pattern=r"^([0-9a-f]{64})?$",
        description="The exact call this observation is about. Compared "
                    "against the dispatch recorded in the audit chain; a "
                    "receipt for a different call is refused.")
    grant_jti: str = Field(
        "", max_length=200,
        description="The grant consumed by the dispatch being attested to. "
                    "One receipt per dispatch; a second is refused as a "
                    "replay.")
    observed_state_hash: str = Field(
        "", max_length=128,
        description="The system-of-record state the verifier observed, for "
                    "the operator to correlate. Recorded, not adjudicated.")
    verifier_version: str = Field(
        "", max_length=100,
        description="Which build of the verifier looked. A verdict whose "
                    "producer cannot be identified is not reproducible.")
    status: EffectStatus
    reason_code: str = Field(..., min_length=1, max_length=100)
    verifier_identity: str = Field(..., min_length=1, max_length=200)
    expected_sha256: str = Field(
        "", max_length=64, pattern=r"^([0-9a-f]{64})?$",
        description="Lowercase hex SHA-256, or empty. Validated on the wire: "
                    "a digest field that accepts arbitrary text is not a "
                    "digest field.")
    observed_sha256: str = Field(
        "", max_length=64, pattern=r"^([0-9a-f]{64})?$",
        description="Lowercase hex SHA-256, or empty.")
    verified_at: str = Field("", max_length=64)
    detail: str = Field("", max_length=2000)
