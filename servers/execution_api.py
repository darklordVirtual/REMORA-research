# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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

from datetime import UTC, datetime, timedelta
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
_IDEMPOTENCY: dict[str, dict[str, Any]] = {}

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "delete_production_database": {
        "risk_tier": "critical",
        "domain": "infrastructure",
        "action_type": "destructive_write"
    },
    "dce_search_law": {
        "risk_tier": "low",
        "domain": "law",
        "action_type": "read"
    },
    "remora_verify_claim": {
        "risk_tier": "low",
        "domain": "general",
        "action_type": "read"
    },
    "store_artifact": {
        "risk_tier": "medium",
        "domain": "general",
        "action_type": "write"
    },
    "read_telemetry": {
        "risk_tier": "low",
        "domain": "unknown",
        "action_type": "read",
        "target_environment": "staging"
    },
    "update_work_order": {
        "risk_tier": "high",
        "domain": "unknown",
        "action_type": "production_write",
        "target_environment": "prod",
        "rollback_available": True
    }
}
_IDEMPOTENCY: dict[str, dict[str, Any]] = {}

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "delete_production_database": {
        "risk_tier": "critical",
        "domain": "infrastructure",
        "action_type": "destructive_write"
    },
    "dce_search_law": {
        "risk_tier": "low",
        "domain": "law",
        "action_type": "read"
    },
    "remora_verify_claim": {
        "risk_tier": "low",
        "domain": "general",
        "action_type": "read"
    },
    "store_artifact": {
        "risk_tier": "medium",
        "domain": "general",
        "action_type": "write"
    },
    "read_telemetry": {
        "risk_tier": "low",
        "domain": "unknown",
        "action_type": "read",
        "target_environment": "staging"
    },
    "update_work_order": {
        "risk_tier": "high",
        "domain": "unknown",
        "action_type": "production_write",
        "target_environment": "prod",
        "rollback_available": True
    }
}



def _build_chain():
    """Durable chain when configured (REM-034): REMORA_PG_DSN -> Postgres,
    REMORA_CHAIN_DB -> SQLite file; otherwise the in-process reference."""
    import os as _os

    from remora.governance.tenant_chain import (
        PostgresTenantChain,
        SQLiteTenantChain,
    )
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    if dsn:
        return PostgresTenantChain(dsn)
    db = _os.environ.get("REMORA_CHAIN_DB", "").strip()
    if db:
        return SQLiteTenantChain(db)
    return TenantAuditChain()


_CHAIN = _build_chain()
import os as _os
_GATE = EnforcementGate(
    strict=True,
    audience=PEP_AUDIENCE,
    dsn=_os.environ.get("REMORA_PG_DSN", "").strip(),
    db_path=_os.environ.get("REMORA_CHAIN_DB", "").strip()
)
_QUEUES: dict[str, ReviewQueue] = {}
# item_id -> (tenant, ToolCallRequest fields) so execute() can rebuild hashes.
_ITEM_TENANT: dict[str, str] = {}


def _auth(request: Request) -> tuple[str, str, str]:
    from servers import api as api_mod

    tenant, role = api_mod._authenticate(request)
    return tenant, role, api_mod._authenticated_principal(request)


import json
import dataclasses
from enum import Enum
from contextlib import contextmanager

def to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return {k: to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    return obj

from remora.governance.review_queue import PendingReview, ItemStatus, Approval

def from_dict(d, cls):
    if hasattr(cls, "__dataclass_fields__"):
        kwargs = {}
        for k, v in d.items():
            field_type = cls.__dataclass_fields__[k].type
            if 'datetime' in str(field_type) and isinstance(v, str):
                kwargs[k] = datetime.fromisoformat(v)
            elif 'ItemStatus' in str(field_type):
                kwargs[k] = ItemStatus(v)
            elif 'DecisionAction' in str(field_type):
                kwargs[k] = DecisionAction(v)
            elif 'Observation' in str(field_type) and isinstance(v, dict):
                kwargs[k] = PolicyObservation(**v)
            elif 'Approval' in str(field_type) and isinstance(v, dict):
                v['expires_at'] = datetime.fromisoformat(v['expires_at'])
                kwargs[k] = Approval(**v)
            else:
                kwargs[k] = v
        return cls(**kwargs)
    return d

@contextmanager
def db_transaction_state(tenant: str):
    global _ITEM_TENANT
    q = _queue(tenant)
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    db_path = _os.environ.get("REMORA_CHAIN_DB", "").strip()

    if dsn:
        import psycopg  # type: ignore
        with psycopg.connect(dsn) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS global_state (tenant_id TEXT PRIMARY KEY, qs_json TEXT, it_json TEXT)")
            with conn.transaction():
                row = conn.execute("SELECT qs_json, it_json FROM global_state WHERE tenant_id = %s FOR UPDATE", (tenant,)).fetchone()
                if row and row[0]:
                    q._items = {k: from_dict(v, PendingReview) for k, v in json.loads(row[0]).items()}
                if row and row[1]:

                    _ITEM_TENANT.update(json.loads(row[1]))
                try:
                    yield q
                finally:
                    conn.execute(
                        "INSERT INTO global_state (tenant_id, qs_json, it_json) VALUES (%s, %s, %s) "
                        "ON CONFLICT (tenant_id) DO UPDATE SET qs_json = EXCLUDED.qs_json, it_json = EXCLUDED.it_json",
                        (tenant, json.dumps({k: to_dict(v) for k, v in q._items.items()}), json.dumps(_ITEM_TENANT))
                    )
    elif db_path:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS global_state (tenant_id TEXT PRIMARY KEY, qs_json TEXT, it_json TEXT)")
            conn.commit()
            conn.execute("BEGIN EXCLUSIVE TRANSACTION")
            row = conn.execute("SELECT qs_json, it_json FROM global_state WHERE tenant_id = ?", (tenant,)).fetchone()
            if row and row[0]:
                q._items = {k: from_dict(v, PendingReview) for k, v in json.loads(row[0]).items()}
            if row and row[1]:

                _ITEM_TENANT.update(json.loads(row[1]))
            try:
                yield q
            finally:
                conn.execute(
                    "INSERT INTO global_state (tenant_id, qs_json, it_json) VALUES (?, ?, ?) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET qs_json = excluded.qs_json, it_json = excluded.it_json",
                    (tenant, json.dumps({k: to_dict(v) for k, v in q._items.items()}), json.dumps(_ITEM_TENANT))
                )
                conn.commit()
    else:
        with q._lock:
            yield q


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
    registry_entry = TOOL_REGISTRY.get(req.tool_name, {
        "risk_tier": "critical",
        "domain": "unknown",
        "action_type": "unknown"
    })
    return PolicyObservation.from_tool_call(
        name=req.tool_name,
        arguments=req.arguments,
        risk_tier=registry_entry.get("risk_tier", "critical"),
        domain=registry_entry.get("domain", "unknown"),
        action_type=registry_entry.get("action_type", "unknown"),
        target_environment=registry_entry.get("target_environment", req.target_environment),
        trust_score=req.trust_score,
        phase=req.phase,
        evidence_action=req.evidence_action,
        evidence_confidence=req.evidence_confidence,
        schema_valid=registry_entry.get("schema_valid", req.schema_valid) if req.tool_name == "delete_production_database" else req.schema_valid,
        rollback_available=registry_entry.get("rollback_available", req.rollback_available) if req.tool_name == "delete_production_database" else req.rollback_available,
        session_id=tenant,
    )



@router.post("/assess")
def assess(req: ToolCallRequest, request: Request) -> dict[str, Any]:
    tenant, role, principal = _auth(request)
    idemp_key = f"assess:{tenant}:{req.idempotency_key}" if req.idempotency_key else None
    if idemp_key and idemp_key in _IDEMPOTENCY:
        return _IDEMPOTENCY[idemp_key]

    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "assess")
    obs = _observation(req, tenant)
    report = _ENGINE.decide(obs)
    now = datetime.now(UTC)
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
        with db_transaction_state(tenant) as q:
            item = q.enqueue(obs, report.action) if report.action in (
            DecisionAction.VERIFY, DecisionAction.ESCALATE
        ) else None
        if item is not None:
            _ITEM_TENANT[item.item_id] = tenant
            record["review_item_id"] = item.item_id
            response["review_item_id"] = item.item_id
    entry = _CHAIN.append(tenant, record)
    response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
    
    if idemp_key:
        _IDEMPOTENCY[idemp_key] = response
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
    # Profile-specific approval role (review-8 finding): a generic reviewer
    # must not approve what the tenant's risk profile reserves for
    # domain_expert/senior_authority. The item's own observation carries the
    # authoritative risk tier; same enforcement path as legacy /v1/review.
    try:
        with db_transaction_state(tenant) as q:
            item = q.item(req.item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    risk_tier = item.observation.risk_tier
    _, profile_cfg = api_mod._resolve_tenant_policy_profile(
        tenant, str(risk_tier) if risk_tier is not None else None
    )
    api_mod._enforce_review_approval_role(
        role=role,
        tenant_id=tenant,
        decision="approved",
        review_requirements=api_mod._extract_review_requirements(profile_cfg),
    )
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
        with db_transaction_state(tenant) as q:
            outcome = q.execute(req.item_id, fresh_obs)
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
        now = datetime.now(UTC)
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
