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
from remora.sdk.effects import EffectVerificationView


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
    "LifecycleTrail",
    "ProposalLineageView",
    "ProposalView",
    "RejectionResult",
    "ResolutionPlan",
    "SemanticAssessment",
    "ToolCall",
    "ToolSpecIdentity",
]


@dataclass(frozen=True)
class ProposalLineageView:
    """What the chain says about this proposal's ancestry.

    Present so a product can SEE resubmit-until-accept probing: without
    lineage, an agent refused once can adjust an argument and propose
    again, and every attempt looks like a first one.

    ``escalation_eligible`` is advisory. ``shadow_only`` is true while
    REMORA records the signal without routing on it — a product that
    treated eligibility as an escalation would be acting on a
    false-positive rate nobody has measured yet. ``lineage_key_basis``
    says how precise the grouping could be: ``semantic_target`` names the
    object a signed ToolSpec declared, ``tool_only`` cannot tell repeated
    legitimate use from probing and deserves less weight.
    """

    superseded_proposal_id: str
    prior_abstain_count: int
    probe_sequence_no: int
    escalation_eligible: bool
    lineage_key_basis: str
    window_seconds: int
    shadow_only: bool

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any] | None
    ) -> "ProposalLineageView | None":
        if not payload:
            return None
        return cls(
            superseded_proposal_id=str(
                payload.get("superseded_proposal_id", "")),
            prior_abstain_count=int(payload.get("prior_abstain_count", 0)),
            probe_sequence_no=int(payload.get("probe_sequence_no", 1)),
            escalation_eligible=bool(payload.get("escalation_eligible", False)),
            lineage_key_basis=str(payload.get("lineage_key_basis", "")),
            window_seconds=int(payload.get("window_seconds", 0)),
            # Absent means an older server that does not route on lineage
            # either. Defaulting to True keeps a consumer from reading an
            # omission as "this WAS escalated".
            shadow_only=bool(payload.get("shadow_only", True)),
        )


@dataclass(frozen=True)
class ToolSpecIdentity:
    """Which signed ToolSpec authorized an action.

    ``enforced`` is not decoration. A deployment running without signed
    specs is not silently equivalent to one running with them, and a
    consumer must be able to SEE which mode produced a decision rather
    than infer it from an empty hash.
    """

    tool_id: str
    version: int
    hash: str
    enforced: bool

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any] | None
    ) -> "ToolSpecIdentity | None":
        if not payload:
            return None
        return cls(
            tool_id=str(payload.get("tool_id", "")),
            version=int(payload.get("version", 0)),
            hash=str(payload.get("hash", "")),
            enforced=bool(payload.get("enforced", False)),
        )


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
    #: Optional exact offset binding into the resolved task text; when both
    #: are set the server requires task_text[start:end] == source_span.
    source_start: int | None = None
    source_end: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "argument": self.argument,
            "value": self.value,
            "transform": self.transform,
            "source_span": self.source_span,
        }
        if self.params:
            payload["params"] = dict(self.params)
        if self.source_start is not None and self.source_end is not None:
            payload["source_start"] = self.source_start
            payload["source_end"] = self.source_end
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
class ResolutionPlan:
    """What would resolve a VERIFY or ESCALATE, in machine-readable form.

    ``type`` discriminates two genuinely different resolutions rather than
    merging them: ``human_approval`` (a person holding ``required_role``
    must act, before ``expires_at``) and ``machine_resolution`` (a bounded
    lookup the engine named — ``resolver`` plus the arguments it may
    establish). ABSTAIN carries no plan at all, because no bounded step is
    known and promising one would be a lie.

    An ESCALATE's ``required_role`` is always higher than a VERIFY's: an
    escalation a normal reviewer may approve is not an escalation.
    """

    type: str
    required_role: str | None = None
    requirements: tuple[str, ...] = ()
    decision_reasons: tuple[str, ...] = ()
    expires_at: str | None = None
    resubmit_required: bool = False
    resolver: str | None = None
    target_arguments: tuple[str, ...] = ()
    source_tools: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ResolutionPlan":
        return cls(
            type=str(payload["type"]),
            required_role=payload.get("required_role"),
            requirements=tuple(str(r) for r in payload.get("requirements", ())),
            decision_reasons=tuple(
                str(r) for r in payload.get("decision_reasons", ())
            ),
            expires_at=payload.get("expires_at"),
            resubmit_required=bool(payload.get("resubmit_required", False)),
            resolver=payload.get("resolver"),
            target_arguments=tuple(
                str(a) for a in payload.get("target_arguments", ())
            ),
            source_tools=tuple(str(s) for s in payload.get("source_tools", ())),
            raw=_frozen(payload) or MappingProxyType({}),
        )


@dataclass(frozen=True)
class RejectionResult:
    """Outcome of refusing a review item; terminal."""

    status: str
    proposal_id: str | None
    item_id: str
    reason: str
    audit: AuditRef
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RejectionResult":
        return cls(
            status=str(payload["status"]),
            proposal_id=payload.get("proposal_id"),
            item_id=str(payload["item_id"]),
            reason=str(payload.get("reason", "")),
            audit=AuditRef.from_payload(payload["audit"]),
            raw=_frozen(payload) or MappingProxyType({}),
        )


@dataclass(frozen=True)
class AssessmentResult:
    """The governance decision for one proposed tool call.

    ``execution_token`` is present only on ACCEPT (a signed single-use
    grant); ``review_item_id`` only on VERIFY/ESCALATE (a human review
    item); ABSTAIN carries neither. ``raw`` retains the full response
    body for forward compatibility with additive server fields.

    Both lifecycle branches are now redeemable from this client
    (issue #36, closed 2026-08-05): pass ``execution_token`` to
    :meth:`RemoraClient.execute_accepted` for a direct ACCEPT, or take
    ``review_item_id`` through approve → :meth:`RemoraClient.execute`.
    A deployment-side PEP consuming the token out-of-band remains
    supported; the REST path is an addition, not a replacement.
    """

    proposal_id: str
    action: DecisionAction
    reasons: tuple[str, ...]
    tool_call_hash: str
    semantic: SemanticAssessment
    audit: AuditRef
    execution_token: Mapping[str, Any] | None = None
    review_item_id: str | None = None
    resolution_plan: "ResolutionPlan | None" = None
    toolspec: ToolSpecIdentity | None = None
    #: Ancestry of this proposal, when the server reports it. None on an
    #: older server — never read as "no probing", only as "not reported".
    lineage: "ProposalLineageView | None" = None
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
            resolution_plan=(
                ResolutionPlan.from_payload(payload["resolution_plan"])
                if payload.get("resolution_plan") else None
            ),
            toolspec=ToolSpecIdentity.from_payload(payload.get("toolspec")),
            lineage=ProposalLineageView.from_payload(payload.get("lineage")),
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
    toolspec: ToolSpecIdentity | None = None
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
            toolspec=ToolSpecIdentity.from_payload(payload.get("toolspec")),
            raw=_frozen(payload) or MappingProxyType({}),
        )


@dataclass(frozen=True)
class ProposalView:
    """One proposal's decision and where it currently stands.

    ``current_state`` is DERIVED from the audit chain and the dispatch
    verdict, never stored — a stored copy could drift from the records it
    claims to describe.
    """

    proposal_id: str
    decision: str | None
    current_state: str
    event_count: int
    tool_name: str | None = None
    tool_call_hash: str | None = None
    reasons: tuple[str, ...] = ()
    review_item_id: str | None = None
    dispatch: Mapping[str, Any] | None = None
    #: The latest effect verification, or None when nothing has been
    #: verified. Absence must never read as a passing verdict.
    effect: EffectVerificationView | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProposalView":
        return cls(
            proposal_id=str(payload["proposal_id"]),
            decision=payload.get("decision"),
            current_state=str(payload["current_state"]),
            event_count=int(payload.get("event_count", 0)),
            tool_name=payload.get("tool_name"),
            tool_call_hash=payload.get("tool_call_hash"),
            reasons=tuple(str(r) for r in payload.get("reasons", ())),
            review_item_id=payload.get("review_item_id"),
            dispatch=_frozen(payload.get("dispatch")),
            effect=(
                EffectVerificationView.from_payload(payload["effect"])
                if (payload.get("effect") or {}).get("status") else None
            ),
            raw=_frozen(payload) or MappingProxyType({}),
        )


@dataclass(frozen=True)
class LifecycleTrail:
    """The ordered event trail for one proposal, plus its dispatch verdict."""

    proposal_id: str
    events: tuple[Mapping[str, Any], ...]
    current_state: str
    dispatch: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "LifecycleTrail":
        return cls(
            proposal_id=str(payload["proposal_id"]),
            events=tuple(_frozen(e) or MappingProxyType({})
                         for e in payload.get("events", ())),
            current_state=str(payload.get("current_state", "")),
            dispatch=_frozen(payload.get("dispatch")),
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
