# Author: Stian Skogbrott
# License: Apache-2.0
"""End-to-end execution API (REM-035): one authoritative state machine.

    PROPOSED --assess--> ACCEPT  -> signed short-lived execution token
                     -> VERIFY/ESCALATE -> durable ReviewQueue item
    APPROVED --execute--> fresh re-gate -> one-time grant -> PEP consume
    (or: EXPIRED / INVALIDATED / BINDING_REFUSED — all audited)

Every transition appends to the atomic per-tenant audit chain (REM-034).
The exact tool-call payload is bound at the API boundary: assess accepts
``tool_name`` + full ``arguments`` and computes the same canonical hash the
enforcement gate consumes — no summary-hash shortcut.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken
from remora.governance.review_queue import (
    ExecutionDecision,
    ReviewQueue,
)
from remora.governance.tenant_chain import TenantAuditChain
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

router = APIRouter(prefix="/v1/execution", tags=["execution"])

PEP_AUDIENCE = "pep://remora-execution"
EXECUTION_TOKEN_TTL_SECONDS = 300

_ENGINE = RemoraDecisionEngine()
_CHAIN = TenantAuditChain()
_GATE = EnforcementGate(strict=True, audience=PEP_AUDIENCE)
_QUEUES: dict[str, ReviewQueue] = {}
# item_id -> (tenant, ToolCallRequest fields) so execute() can rebuild hashes.
_ITEM_TENANT: dict[str, str] = {}


def _auth(request: Request) -> tuple[str, str, str]:
    from servers import api as api_mod

    tenant, role = api_mod._authenticate(request)
    return tenant, role, api_mod._authenticated_principal(request)


def _queue(tenant: str) -> ReviewQueue:
    if tenant not in _QUEUES:
        _QUEUES[tenant] = ReviewQueue(engine=_ENGINE)
    return _QUEUES[tenant]


class ToolCallRequest(BaseModel):
    """Exact-payload assessment request (review finding: full-args binding)."""

    tool_name: str = Field(..., min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_tier: str | None = None
    domain: str | None = None
    action_type: str | None = None
    target_environment: str = "prod"
    trust_score: float | None = None
    phase: str | None = None
    evidence_action: str | None = None
    evidence_confidence: float | None = None
    schema_valid: bool | None = None
    rollback_available: bool | None = None
    idempotency_key: str | None = None


def _observation(req: ToolCallRequest, tenant: str) -> PolicyObservation:
    return PolicyObservation.from_tool_call(
        name=req.tool_name,
        arguments=req.arguments,
        risk_tier=req.risk_tier,
        domain=req.domain,
        action_type=req.action_type,
        target_environment=req.target_environment,
        trust_score=req.trust_score,
        phase=req.phase,
        evidence_action=req.evidence_action,
        evidence_confidence=req.evidence_confidence,
        schema_valid=req.schema_valid,
        rollback_available=req.rollback_available,
        session_id=tenant,
    )


@router.post("/assess")
def assess(req: ToolCallRequest, request: Request) -> dict[str, Any]:
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "assess")
    obs = _observation(req, tenant)
    report = _ENGINE.decide(obs)
    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "event": "assessed",
        "actor": principal,
        "tool_name": req.tool_name,
        "tool_call_hash": obs.tool_call_hash,
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "policy_version": report.policy_version,
    }
    response: dict[str, Any] = {
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "tool_call_hash": obs.tool_call_hash,
    }
    if report.action is DecisionAction.ACCEPT:
        token = PolicyDecisionToken.issue(
            action="accept",
            observation_hash=obs.tool_call_hash or "",
            request_id=f"{tenant}:{obs.tool_call_hash}",
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=EXECUTION_TOKEN_TTL_SECONDS)).isoformat(),
            audience=PEP_AUDIENCE,
        )
        record["grant_jti"] = token.jti
        response["execution_token"] = token.to_dict()
    else:
        item = _queue(tenant).enqueue(obs, report.action) if report.action in (
            DecisionAction.VERIFY, DecisionAction.ESCALATE
        ) else None
        if item is not None:
            _ITEM_TENANT[item.item_id] = tenant
            record["review_item_id"] = item.item_id
            response["review_item_id"] = item.item_id
    entry = _CHAIN.append(tenant, record)
    response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
    return response


class ApproveRequest(BaseModel):
    item_id: str
    approval_ttl_seconds: int = Field(900, gt=0, le=86400)
    on_behalf_of: str | None = None


@router.post("/approve")
def approve(req: ApproveRequest, request: Request) -> dict[str, Any]:
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    if _ITEM_TENANT.get(req.item_id) != tenant:
        raise HTTPException(status_code=404, detail="review item not found")
    try:
        approval = _queue(tenant).approve(
            req.item_id, approver=principal,
            approval_ttl=timedelta(seconds=req.approval_ttl_seconds),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    entry = _CHAIN.append(tenant, {
        "event": "approved",
        "actor": principal,
        "on_behalf_of": req.on_behalf_of,
        "item_id": req.item_id,
        "expires_at": approval.expires_at.isoformat(),
    })
    return {
        "status": "approved",
        "item_id": req.item_id,
        "expires_at": approval.expires_at.isoformat(),
        "audit": {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash},
    }


class ExecuteRequest(BaseModel):
    """Execute an approved item — the FULL payload is re-presented and the
    fresh world state re-gated; the grant is single-use."""

    item_id: str
    tool_call: ToolCallRequest


@router.post("/execute")
def execute(req: ExecuteRequest, request: Request) -> dict[str, Any]:
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "execute")
    if _ITEM_TENANT.get(req.item_id) != tenant:
        raise HTTPException(status_code=404, detail="review item not found")
    fresh_obs = _observation(req.tool_call, tenant)
    try:
        outcome = _queue(tenant).execute(req.item_id, fresh_obs)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record: dict[str, Any] = {
        "event": f"execution_{outcome.decision.value}",
        "actor": principal,
        "item_id": req.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "detail": outcome.detail,
    }
    response: dict[str, Any] = {
        "outcome": outcome.decision.value,
        "detail": outcome.detail,
    }
    if outcome.decision is ExecutionDecision.EXECUTE:
        now = datetime.now(timezone.utc)
        token = PolicyDecisionToken.issue(
            action="accept",
            observation_hash=fresh_obs.tool_call_hash or "",
            request_id=f"{tenant}:{req.item_id}",
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=EXECUTION_TOKEN_TTL_SECONDS)).isoformat(),
            audience=PEP_AUDIENCE,
        )
        # PEP consumption happens HERE: the grant is consumed atomically the
        # moment it is honoured — a re-presented token can never execute twice.
        gate_result = _GATE.check(token, fresh_obs.tool_call_hash, consume=True)
        record["grant_jti"] = token.jti
        record["pep_allowed"] = gate_result.allowed
        response["execution_grant"] = token.to_dict()
        response["pep"] = {"allowed": gate_result.allowed, "reason": gate_result.reason}
    entry = _CHAIN.append(tenant, record)
    response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
    return response


@router.get("/audit/verify")
def audit_verify(request: Request) -> dict[str, Any]:
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    ok, problems = _CHAIN.verify(tenant)
    return {"tenant": tenant, "valid": ok, "problems": problems}
