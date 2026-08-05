# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Stable data models for the REMORA SDK.

These frozen dataclasses mirror the ``/v1/execution/*`` REST contract
1:1 (see ``schemas/openapi.json``, the drift-gated contract artifact).
Conditional response keys are absent on the wire and ``None`` on the
models. ``DecisionAction`` is re-exported from the canonical policy enum
— the SDK introduces no parallel decision vocabulary.

Result-model mappings (``execution_token``, ``raw``, ``execution_grant``,
``pep``, ``tool_execution``) are wrapped in ``MappingProxyType`` at parse
time, so top-level mutation (``result.raw["decision"] = ...``) raises
``TypeError`` instead of silently lying to downstream consumers (review
2026-08-05). Nested values are not deep-frozen; request-side ``ToolCall``
fields stay caller-owned plain mappings and are copied at serialization.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


from remora.policy.report import DecisionAction


def _frozen(payload: Any) -> Mapping[str, Any] | None:
    """Top-level immutable view of a response mapping (None passes through)."""
    if payload is None:
        return None
    return MappingProxyType(dict(payload))

__all__ = [
    "ApprovalResult",
    "AssessmentResult",
    "AuditRef",
    "AuditVerification",
    "DecisionAction",
    "DerivationProposal",
    "ExecutionResult",
    "SemanticAssessment",
    "ToolCall",
]


@dataclass(frozen=True)
class DerivationProposal:
    """A proposed derivation receipt for one derived argument value.

    Declares WHERE the value came from (``source_span``, which must occur
    verbatim in the resolved task text) and HOW (``transform``, a name
    from the server's versioned whitelist). A proposal only: the server
    accepts it exclusively by deterministic re-execution — an explanation
    is never a proof, and an invalid receipt simply leaves the value
    ungrounded.
    """

    argument: str
    value: Any
    transform: str
    source_span: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "argument": self.argument,
            "value": self.value,
            "transform": self.transform,
            "source_span": self.source_span,
        }
        if self.params:
            payload["params"] = dict(self.params)
        return payload


@dataclass(frozen=True)
class ToolCall:
    """A proposed tool invocation submitted for governance assessment.

    The request is a proposal: authoritative risk signals are derived
    server-side, and client-declared fields can only lower trust, never
    raise it. ``schema_valid`` and ``rollback_available`` are
    downgrade-only declarations; ``intent_ref`` links the call to a work
    order or task authority; ``untrusted_context`` carries text of
    unverified provenance for injection screening.
    """

    tool_name: str
    arguments: Mapping[str, Any]
    target_environment: str = "prod"
    intent_ref: str | None = None
    untrusted_context: str | None = None
    idempotency_key: str | None = None
    schema_valid: bool | None = None
    rollback_available: bool | None = None
    derivations: "tuple[DerivationProposal, ...] | None" = None

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the wire shape, omitting unset optional fields."""
        payload: dict[str, Any] = {
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "target_environment": self.target_environment,
        }
        for key in ("intent_ref", "untrusted_context", "idempotency_key",
                    "schema_valid", "rollback_available"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.derivations:
            payload["derivations"] = [d.to_payload() for d in self.derivations]
        return payload


@dataclass(frozen=True)
class AuditRef:
    """Position of an operation's record in the tenant audit chain."""

    sequence_no: int
    entry_hash: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> AuditRef:
        return cls(sequence_no=int(payload["sequence_no"]),
                   entry_hash=str(payload["entry_hash"]))


@dataclass(frozen=True)
class SemanticAssessment:
    """Semantic context the decision was made under (SHELF-020).

    Empty hashes mean "no bundle configured" — the registry-only path,
    recorded rather than assumed away.
    """

    tool_contract_bundle_hash: str
    state_hash: str
    intent_authority_hash: str
    tool_matches_goal: bool | None
    expected_effect_matches: bool | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SemanticAssessment:
        return cls(
            tool_contract_bundle_hash=str(payload.get("tool_contract_bundle_hash", "")),
            state_hash=str(payload.get("state_hash", "")),
            intent_authority_hash=str(payload.get("intent_authority_hash", "")),
            tool_matches_goal=payload.get("tool_matches_goal"),
            expected_effect_matches=payload.get("expected_effect_matches"),
        )


@dataclass(frozen=True)
class AssessmentResult:
    """The governance decision for one proposed tool call.

    ``execution_token`` is present only on ACCEPT (a signed single-use
    grant); ``review_item_id`` only on VERIFY/ESCALATE (a human review
    item); ABSTAIN carries neither. ``raw`` retains the full response
    body for forward compatibility with additive server fields.

    CONTRACT BOUNDARY (review 2026-08-05): the REST API currently has NO
    token-redemption endpoint — the ACCEPT token is consumed by a
    deployment-side PEP (``remora.enforcement``), not by this client, and
    the SDK's ``execute()`` covers only the review path
    (VERIFY → approve → execute). A governed REST dispatch path for
    direct-ACCEPT proposals is tracked as issue #36 / FT-01; until it
    ships, this SDK is NOT a complete client for the ACCEPT lifecycle.
    """

    proposal_id: str
    action: DecisionAction
    reasons: tuple[str, ...]
    tool_call_hash: str
    semantic: SemanticAssessment
    audit: AuditRef
    execution_token: Mapping[str, Any] | None = None
    review_item_id: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> AssessmentResult:
        return cls(
            proposal_id=str(payload["proposal_id"]),
            action=DecisionAction(payload["decision"]),
            reasons=tuple(str(r) for r in payload.get("reasons", [])),
            tool_call_hash=str(payload.get("tool_call_hash", "")),
            semantic=SemanticAssessment.from_payload(payload.get("semantic", {})),
            audit=AuditRef.from_payload(payload["audit"]),
            execution_token=_frozen(payload.get("execution_token")),
            review_item_id=payload.get("review_item_id"),
            raw=_frozen(payload) or MappingProxyType({}),
        )


@dataclass(frozen=True)
class ApprovalResult:
    """Outcome of approving a review item; approval expires at ``expires_at``."""

    status: str
    proposal_id: str
    item_id: str
    expires_at: str
    audit: AuditRef
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ApprovalResult:
        return cls(
            status=str(payload["status"]),
            proposal_id=str(payload["proposal_id"]),
            item_id=str(payload["item_id"]),
            expires_at=str(payload["expires_at"]),
            audit=AuditRef.from_payload(payload["audit"]),
            raw=_frozen(payload) or MappingProxyType({}),
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of a governed execution attempt.

    ``outcome`` is ``"execute"`` when the exact approved payload was
    re-bound and dispatched; otherwise a refusal
    (``approval_expired`` / ``binding_refused`` / ``approval_invalidated``)
    with ``execution_grant``, ``pep`` and ``tool_execution`` set to
    ``None``. The nested mappings are passed through verbatim in this
    SDK version; typed models for them are planned, additively.
    """

    proposal_id: str
    outcome: str
    detail: str
    audit: AuditRef
    execution_grant: Mapping[str, Any] | None = None
    pep: Mapping[str, Any] | None = None
    tool_execution: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExecutionResult:
        return cls(
            proposal_id=str(payload["proposal_id"]),
            outcome=str(payload["outcome"]),
            detail=str(payload.get("detail", "")),
            audit=AuditRef.from_payload(payload["audit"]),
            execution_grant=_frozen(payload.get("execution_grant")),
            pep=_frozen(payload.get("pep")),
            tool_execution=_frozen(payload.get("tool_execution")),
            raw=_frozen(payload) or MappingProxyType({}),
        )


@dataclass(frozen=True)
class AuditVerification:
    """Result of verifying the tenant's audit chain end to end."""

    tenant: str
    valid: bool
    problems: tuple[str, ...]
    records_checked: int
    empty: bool
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> AuditVerification:
        return cls(
            tenant=str(payload["tenant"]),
            valid=bool(payload["valid"]),
            problems=tuple(str(p) for p in payload.get("problems", [])),
            records_checked=int(payload.get("records_checked", 0)),
            empty=bool(payload.get("empty", False)),
            raw=_frozen(payload) or MappingProxyType({}),
        )
