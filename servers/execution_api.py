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

from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.lease import (
    ExecutionLease,
    GovernedToolDispatcher,
    LeaseRefused,
)
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
# Bounded LRU (external review 2026-07-28, N2): previously an unbounded dict
# that grew for the process lifetime. On overflow the oldest entry is
# evicted; a replayed key after eviction simply re-runs assess, which is
# idempotent-safe (assess has no side effects beyond the audit record).
_IDEMPOTENCY: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_IDEMPOTENCY_MAX_ENTRIES = 10_000


def _idempotency_get(key: str) -> dict[str, Any] | None:
    hit = _IDEMPOTENCY.get(key)
    if hit is not None:
        _IDEMPOTENCY.move_to_end(key)
    return hit


def _idempotency_put(key: str, response: dict[str, Any]) -> None:
    _IDEMPOTENCY[key] = response
    _IDEMPOTENCY.move_to_end(key)
    while len(_IDEMPOTENCY) > _IDEMPOTENCY_MAX_ENTRIES:
        _IDEMPOTENCY.popitem(last=False)

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
    # Recurse into containers: dataclasses.asdict() leaves datetimes and
    # Enums untouched inside NESTED dataclasses (e.g. PendingReview.approval),
    # and the previous version never descended into plain dicts — approvals
    # were unserializable, which went unnoticed exactly because they were
    # never persisted (external review 2026-07-27, finding 2).
    if dataclasses.is_dataclass(obj):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
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
                v['issued_at'] = datetime.fromisoformat(v['issued_at'])
                v['approved_action'] = DecisionAction(v['approved_action'])
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
            except BaseException:
                # Mirror the Postgres branch's transaction semantics: an
                # exception inside the handler must roll the whole
                # transaction back, never persist partially mutated queue
                # state (external review 2026-07-28, N1).
                conn.rollback()
                raise
            else:
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


# ── Governed tool dispatch (issue #13) ─────────────────────────────────────
#
# The dispatcher — not the agent — holds the tool callables and any
# downstream credentials they close over. Tools are registered exclusively
# through trusted deployment configuration: the module named by
# REMORA_TOOL_REGISTRY_MODULE must expose
#
#     def register_tools(register: Callable[[str, Callable], None]) -> None
#
# and is imported once per process at first dispatch. Request payloads can
# never add or replace callables. With no module configured the registry is
# empty and every dispatch reports executed=false/unknown_tool — the
# research-profile default stays side-effect free but is now EXPLICIT about
# it instead of implying execution.

_DISPATCHER: GovernedToolDispatcher | None = None


def _current_policy_bundle_hash() -> str:
    from servers import api as api_mod

    return api_mod._policy_component_hashes().get("policy_hash") or ""


def _tool_dispatcher() -> GovernedToolDispatcher | None:
    """App-lifecycle dispatcher; None when no policy bundle hash exists."""
    global _DISPATCHER
    if _DISPATCHER is None:
        bundle = _current_policy_bundle_hash()
        if not bundle:
            return None
        dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=bundle)
        spec = _os.environ.get("REMORA_TOOL_REGISTRY_MODULE", "").strip()
        if spec:
            import importlib

            importlib.import_module(spec).register_tools(dispatcher.register)
        _DISPATCHER = dispatcher
    return _DISPATCHER


def _reset_tool_dispatcher() -> None:
    """Test hook: drop the cached dispatcher (e.g. after env changes)."""
    global _DISPATCHER
    _DISPATCHER = None


def _jsonable(value: Any) -> Any:
    """Best-effort JSON projection of a tool result for response/audit."""
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return repr(value)


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
        # Trust boundary (issue #34): the policy-only execution kernel has
        # no oracle/evidence pipeline, and the CLIENT is never a trust
        # source — trust, phase and evidence status are unknown here, so
        # the engine fails toward VERIFY/ABSTAIN. No probabilistic ACCEPT
        # can fire without these signals; an authoritative server-side
        # signal source is #35/#39 scope.
        trust_score=None,
        phase=None,
        evidence_action=None,
        evidence_confidence=None,
        # Downgrade-only rule (issue #34): the request may LOWER trust
        # (schema_valid/rollback_available false — "world got riskier"
        # signals must keep feeding the freshness re-gate) but can never
        # raise it: request true is IGNORED, including when the registry
        # pins nothing (previously true passed through on unpinned tools).
        schema_valid=_downgrade_only_bool(registry_entry.get("schema_valid"), req.schema_valid),
        rollback_available=_downgrade_only_bool(
            registry_entry.get("rollback_available"), req.rollback_available
        ),
        session_id=tenant,
    )


def _downgrade_only_bool(registry_value: bool | None, request_value: bool | None) -> bool | None:
    """Issue #34: the request may lower trust, never raise it.

    request False -> False (downgrade honored); anything else -> the
    registry value unchanged (request True is ignored, unknown stays
    unknown).
    """
    if request_value is False:
        return False
    return registry_value



@router.post("/assess")
def assess(req: ToolCallRequest, request: Request) -> dict[str, Any]:
    tenant, role, principal = _auth(request)
    idemp_key = f"assess:{tenant}:{req.idempotency_key}" if req.idempotency_key else None
    if idemp_key:
        cached = _idempotency_get(idemp_key)
        if cached is not None:
            return cached

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
                # Inside the transaction (external review 2026-07-27): the
                # item->tenant binding must be part of the same durable write
                # as the item itself, or a restart leaves an item the API
                # refuses as unknown.
                _ITEM_TENANT[item.item_id] = tenant
        if item is not None:
            record["review_item_id"] = item.item_id
            response["review_item_id"] = item.item_id
    entry = _CHAIN.append(tenant, record)
    response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}

    if idemp_key:
        _idempotency_put(idemp_key, response)
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
    # Profile-specific approval role (review-8 finding): a generic reviewer
    # must not approve what the tenant's risk profile reserves for
    # domain_expert/senior_authority. The item's own observation carries the
    # authoritative risk tier; same enforcement path as legacy /v1/review.
    # The tenant-binding check runs INSIDE the transaction: after a process
    # restart _ITEM_TENANT is rehydrated from the durable store by the
    # transaction load, so checking before the load 404s real items
    # (review finding 2a).
    try:
        with db_transaction_state(tenant) as q:
            if _ITEM_TENANT.get(req.item_id) != tenant:
                raise KeyError(req.item_id)
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
        # Inside the durable transaction (external review 2026-07-27): the
        # approval previously mutated only in-process state and was silently
        # discarded when the next transaction reloaded the queue from the
        # database — approve->execute was broken in Postgres/SQLite mode.
        with db_transaction_state(tenant) as q:
            approval = q.approve(
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
    fresh_obs = _observation(req.tool_call, tenant)
    try:
        # Tenant-binding check inside the transaction: _ITEM_TENANT is
        # rehydrated from the durable store by the load (review finding 2a).
        with db_transaction_state(tenant) as q:
            if _ITEM_TENANT.get(req.item_id) != tenant:
                raise HTTPException(status_code=404, detail="review item not found")
            outcome = q.execute(req.item_id, fresh_obs)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    response: dict[str, Any] = {
        "outcome": outcome.decision.value,
        "detail": outcome.detail,
    }
    if outcome.decision is not ExecutionDecision.EXECUTE:
        entry = _CHAIN.append(tenant, {
            "event": f"execution_{outcome.decision.value}",
            "actor": principal,
            "item_id": req.item_id,
            "tool_call_hash": fresh_obs.tool_call_hash,
            "detail": outcome.detail,
        })
        response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
        return response

    # The re-gate only AUTHORIZED the call (persisted above); EXECUTED is
    # recorded separately after the dispatcher reports what actually
    # happened (external review 2026-07-27: authorized-for-execution and
    # actually-executed are distinct states).
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
    response["execution_grant"] = token.to_dict()
    response["pep"] = {"allowed": gate_result.allowed, "reason": gate_result.reason}

    # Durable INTENT record BEFORE the external side effect: if the process
    # dies mid-dispatch, the chain shows an authorization with no matching
    # execution_result — never a real side effect without any record.
    intent_entry = _CHAIN.append(tenant, {
        "event": "execution_authorized",
        "actor": principal,
        "item_id": req.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
    })

    # Issue #13: actually dispatch the tool through the governed dispatcher —
    # the response reports what REALLY happened instead of implying
    # execution. Every refusal path is explicit and audited.
    tool_execution: dict[str, Any] = {"executed": False}
    if not gate_result.allowed:
        tool_execution["refusal_reason"] = "pep_denied"
    else:
        dispatcher = _tool_dispatcher()
        if dispatcher is None:
            tool_execution["refusal_reason"] = "policy_bundle_unavailable"
        else:
            try:
                lease = ExecutionLease.issue(
                    decision="accept",
                    tenant_id=tenant,
                    actor_identity=principal,
                    tool_name=req.tool_call.tool_name,
                    arguments=req.tool_call.arguments,
                    target_environment=req.tool_call.target_environment,
                    policy_bundle_hash=_current_policy_bundle_hash(),
                    issued_at=now.isoformat(),
                )
            except (LeaseRefused, ValueError) as exc:
                tool_execution["refusal_reason"] = f"lease_unavailable: {exc}"
            else:
                try:
                    dres = dispatcher.dispatch(
                        lease,
                        req.tool_call.tool_name,
                        req.tool_call.arguments,
                        tenant_id=tenant,
                        target_environment=req.tool_call.target_environment,
                        actor_identity=principal,
                    )
                except RuntimeError as exc:
                    # Tool raised: the nonce is burned, state is unknown.
                    tool_execution["refusal_reason"] = "tool_failed_nonce_burned"
                    tool_execution["error"] = str(exc)
                else:
                    tool_execution["executed"] = dres.executed
                    if dres.executed:
                        tool_execution["result"] = _jsonable(dres.result)
                    else:
                        tool_execution["refusal_reason"] = dres.refusal_reason

    # Persist the REAL outcome as the item's terminal state (EXECUTED only
    # after a confirmed side effect; refusals/failures get their own states).
    with db_transaction_state(tenant) as q:
        q.record_execution_outcome(
            req.item_id,
            executed=tool_execution["executed"],
            failed=tool_execution.get("refusal_reason") == "tool_failed_nonce_burned",
            reason=tool_execution.get("refusal_reason"),
        )

    result_record: dict[str, Any] = {
        "event": "execution_result",
        "actor": principal,
        "item_id": req.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "intent_sequence_no": intent_entry.sequence_no,
        "tool_executed": tool_execution["executed"],
    }
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    entry = _CHAIN.append(tenant, result_record)

    response["tool_execution"] = tool_execution
    response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
    return response


@router.get("/audit/verify")
def audit_verify(request: Request) -> dict[str, Any]:
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    ok, problems = _CHAIN.verify(tenant)
    return {"tenant": tenant, "valid": ok, "problems": problems}
