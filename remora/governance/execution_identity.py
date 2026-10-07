# SPDX-License-Identifier: BUSL-1.1
"""Deployment-owned execution provenance, independent of export formats."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol
from uuid import UUID

from remora.errors import RemoraError
from remora.policy.observation import PolicyObservation, _canonical_json


class ExecutionContextRefused(RemoraError):
    code = "execution_context_refused"
    category = "execution"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _text(value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ExecutionContextRefused("execution_context_invalid")


def _digest(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ExecutionContextRefused("execution_context_invalid_digest")


@dataclass(frozen=True)
class ContextAuthority:
    kind: str
    issuer: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for value in (self.kind, self.issuer, self.evidence_ref):
            _text(value)


@dataclass(frozen=True)
class ContextSubject:
    principal_id: str
    authority: ContextAuthority

    def __post_init__(self) -> None:
        _text(self.principal_id)
        if type(self.authority) is not ContextAuthority:
            raise ExecutionContextRefused("execution_context_invalid")
        if self.authority.kind not in {"oidc", "spiffe", "orchestrator", "deployment"}:
            raise ExecutionContextRefused("execution_context_subject_authority_invalid")


@dataclass(frozen=True)
class ModelInitiator:
    provider: str
    model_id: str
    authority: ContextAuthority

    def __post_init__(self) -> None:
        _text(self.provider)
        _text(self.model_id)
        if type(self.authority) is not ContextAuthority:
            raise ExecutionContextRefused("execution_context_invalid")
        if self.authority.kind not in {"inference_gateway", "trusted_orchestrator"}:
            raise ExecutionContextRefused("execution_context_model_authority_invalid")


@dataclass(frozen=True)
class ContextRuntime:
    runtime_identity_hash: str
    build_provenance_digest: str
    authority: ContextAuthority

    def __post_init__(self) -> None:
        _digest(self.runtime_identity_hash)
        _digest(self.build_provenance_digest)
        if type(self.authority) is not ContextAuthority:
            raise ExecutionContextRefused("execution_context_invalid")
        if self.authority.kind != "deployment":
            raise ExecutionContextRefused("execution_context_runtime_authority_invalid")


@dataclass(frozen=True)
class ContextDataScope:
    classification: str
    scope: tuple[str, ...]
    authority: ContextAuthority
    ceiling: str = "does_not_classify_unknown_downstream_data"

    def __post_init__(self) -> None:
        _text(self.classification)
        if type(self.authority) is not ContextAuthority:
            raise ExecutionContextRefused("execution_context_invalid")
        if (type(self.scope) is not tuple or not self.scope
                or any(type(s) is not str or s not in {"proposal_input", "declared_tool_access"}
                       for s in self.scope)
                or len(set(self.scope)) != len(self.scope)):
            raise ExecutionContextRefused("execution_context_data_scope_invalid")
        if (self.authority.kind != "deployment_policy"
                or self.ceiling != "does_not_classify_unknown_downstream_data"):
            raise ExecutionContextRefused("execution_context_data_ceiling_invalid")


@dataclass(frozen=True)
class ExecutionContextV1:
    context_id: str
    proposal_id: str
    tenant_id: str
    tool_call_hash: str
    captured_at: str
    subject: ContextSubject
    model_initiator: ModelInitiator
    runtime: ContextRuntime
    data_scope: ContextDataScope
    schema_version: str = "remora-execution-context-v1"

    def __post_init__(self) -> None:
        if self.schema_version != "remora-execution-context-v1":
            raise ExecutionContextRefused("execution_context_schema_invalid")
        _text(self.context_id)
        _text(self.proposal_id)
        _text(self.tenant_id)
        _digest(self.tool_call_hash)
        try:
            UUID(self.context_id)
            UUID(self.proposal_id)
            captured = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ExecutionContextRefused("execution_context_identity_invalid") from exc
        if captured.utcoffset() != timedelta(0):
            raise ExecutionContextRefused("execution_context_timestamp_invalid")
        # Reject untyped constructor inputs too, not only malformed wire records.
        for value, expected in (
            (self.subject, ContextSubject), (self.model_initiator, ModelInitiator),
            (self.runtime, ContextRuntime), (self.data_scope, ContextDataScope),
        ):
            if type(value) is not expected:
                raise ExecutionContextRefused("execution_context_invalid")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["data_scope"]["scope"] = list(self.data_scope.scope)
        return data

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ExecutionContextV1:
        def fields(value: Any, names: set[str]) -> dict[str, Any]:
            if type(value) is not dict or set(value) != names:
                raise ExecutionContextRefused("execution_context_schema_invalid")
            return dict(value)

        def authority(value: Any) -> ContextAuthority:
            return ContextAuthority(**fields(value, {"kind", "issuer", "evidence_ref"}))

        data = fields(raw, {
            "context_id", "proposal_id", "tenant_id", "tool_call_hash", "captured_at",
            "subject", "model_initiator", "runtime", "data_scope", "schema_version",
        })
        subject = fields(data["subject"], {"principal_id", "authority"})
        model = fields(data["model_initiator"], {"provider", "model_id", "authority"})
        runtime = fields(data["runtime"], {
            "runtime_identity_hash", "build_provenance_digest", "authority"})
        scope = fields(data["data_scope"], {"classification", "scope", "authority", "ceiling"})
        for block in (subject, model, runtime, scope):
            block["authority"] = authority(block["authority"])
        if type(scope["scope"]) is not list or any(type(s) is not str for s in scope["scope"]):
            raise ExecutionContextRefused("execution_context_data_scope_invalid")
        scope["scope"] = tuple(scope["scope"])
        return cls(**{
            **data, "subject": ContextSubject(**subject),
            "model_initiator": ModelInitiator(**model), "runtime": ContextRuntime(**runtime),
            "data_scope": ContextDataScope(**scope),
        })

    @classmethod
    def from_canonical(cls, value: str) -> ExecutionContextV1:
        try:
            result = cls.from_dict(json.loads(value))
        except (ValueError, TypeError) as exc:
            raise ExecutionContextRefused("execution_context_history_invalid") from exc
        if result.canonical_bytes().decode("utf-8") != value:
            raise ExecutionContextRefused("execution_context_history_noncanonical")
        return result

    def check_binding(self, *, proposal_id: str, tenant: str,
                      principal: str, tool_call_hash: str) -> None:
        if (self.proposal_id != proposal_id or self.tenant_id != tenant
                or self.subject.principal_id != principal
                or self.tool_call_hash != tool_call_hash):
            raise ExecutionContextRefused("execution_context_binding_mismatch")


class ExecutionContextProvider(Protocol):
    def capture(self, *, proposal_id: str, tenant: str, principal: str,
                tool_call_hash: str) -> ExecutionContextV1: ...

    def data_scope_valid(self, context: ExecutionContextV1) -> bool: ...

    def current_build_provenance_digest(self) -> str: ...


def observation_binding(observation: PolicyObservation) -> str:
    """Preserve legacy call hashes; context-bound grants cover both digests."""
    if not observation.execution_context_hash:
        return observation.tool_call_hash or ""
    return hashlib.sha256(_canonical_json({
        "tool_call_hash": observation.tool_call_hash,
        "execution_context_hash": observation.execution_context_hash,
        "proposal_id": observation.proposal_id,
    }).encode("utf-8")).hexdigest()


def historical_context(chain: Any, tenant: str, proposal_id: str,
                       *, required: bool = False) -> ExecutionContextV1 | None:
    events = [e.payload for e in chain.entries(tenant)
              if e.payload.get("proposal_id") == proposal_id]
    records = [e for e in events if e.get("event") == "assessed"]
    if len(records) > 1:
        raise ExecutionContextRefused("execution_context_history_ambiguous")
    record = records[0] if records else {}
    digest = record.get("execution_context_hash")
    canonical = record.get("execution_context_canonical")
    if not digest and canonical is None:
        if required or any(e.get("execution_context_hash") for e in events):
            raise ExecutionContextRefused("execution_context_missing")
        return None
    if type(canonical) is not str:
        raise ExecutionContextRefused("execution_context_history_missing")
    context = ExecutionContextV1.from_canonical(canonical)
    if context.digest() != digest:
        raise ExecutionContextRefused("execution_context_history_hash_mismatch")
    context.check_binding(
        proposal_id=proposal_id, tenant=tenant, principal=record.get("actor", ""),
        tool_call_hash=record.get("tool_call_hash", ""))
    if any(e.get("execution_context_hash") not in (None, "", digest) for e in events):
        raise ExecutionContextRefused("execution_context_history_join_mismatch")
    return context
