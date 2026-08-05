# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""End-to-end execution API (REM-035): one authoritative state machine.

    PROPOSED --assess--> ACCEPT  -> signed short-lived execution token
                     -> VERIFY/ESCALATE -> ReviewQueue item
    APPROVED --execute--> fresh re-gate -> one-time grant -> PEP consume
    (or: EXPIRED / INVALIDATED / BINDING_REFUSED — all audited)

Every transition appends to the atomic per-tenant audit chain (REM-034).
The exact tool-call payload is bound at the API boundary: assess accepts
``tool_name`` + full ``arguments`` and computes the same canonical hash the
enforcement gate consumes — no summary-hash shortcut.

State durability — read this before deploying
---------------------------------------------
Three pieces of state here are safety-relevant: the tenant audit chain, the
review queue, and the PEP's consumed-jti ledger. They are durable only when
``REMORA_PG_DSN`` (multi-node) or ``REMORA_CHAIN_DB`` (single-node SQLite) is
set. With neither, all three live in process memory, and the consequence is
not just a lost audit trail: a one-time execution grant consumed by one
worker is accepted again by a second worker or after a restart, because the
ledger that would have refused the replay no longer exists.

Production mode therefore refuses to start without one of those variables
(``servers/api.py::_validate_production_prerequisites``). Development mode
allows it, logs a warning, and reports ``execution_state_durable: false`` on
``/v1/metrics`` and ``/v1/policy/version`` so the degradation is recorded
rather than assumed away.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.lease import (
    ExecutionLease,
    GovernedToolDispatcher,
    LeaseRefused,
)
from remora.enforcement.result_envelope import capture_tool_result
from remora.enforcement.token import PolicyDecisionToken
from remora.enforcement.outbox import (
    ExecutionOutbox,
    OutboxState,
    PostgresExecutionOutbox,
    SQLiteExecutionOutbox,
)
from remora.governance.lifecycle import (
    IllegalTransition,
    check_transition,
)
from remora.governance.review_queue import (
    ExecutionDecision,
    ReviewQueue,
)
from remora.governance.tenant_chain import TenantAuditChain
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation, canonical_tool_call_hash
from remora.policy.report import DecisionAction
from remora.toolcall.semantic_bundle import (
    IntentResolver,
    SemanticBundle,
    compute_intent_authority_hash,
    load_intent_resolver,
    load_semantic_bundle,
)

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
import logging as _logging
import os as _os

_LOGGER = _logging.getLogger("remora.execution_api")

# Resolved once, so every reporting surface gives the same answer.
EXECUTION_STATE_BACKEND = (
    "postgres" if _os.environ.get("REMORA_PG_DSN", "").strip()
    else "sqlite" if _os.environ.get("REMORA_CHAIN_DB", "").strip()
    else "in_process"
)
EXECUTION_STATE_DURABLE = EXECUTION_STATE_BACKEND != "in_process"

if not EXECUTION_STATE_DURABLE:
    _LOGGER.warning(
        "execution-layer state is in-process: the tenant audit chain, review "
        "queue and one-time-grant ledger are lost on restart, and a consumed "
        "execution grant becomes replayable by another worker. Set "
        "REMORA_PG_DSN or REMORA_CHAIN_DB. Production mode refuses to start "
        "in this configuration."
    )

_GATE = EnforcementGate(
    strict=True,
    audience=PEP_AUDIENCE,
    dsn=_os.environ.get("REMORA_PG_DSN", "").strip(),
    db_path=_os.environ.get("REMORA_CHAIN_DB", "").strip()
)
_QUEUES: dict[str, ReviewQueue] = {}
# item_id -> (tenant, ToolCallRequest fields) so execute() can rebuild hashes.
_ITEM_TENANT: dict[str, str] = {}


import contextvars as _contextvars
import copy as _copy

# FT-02: the connection of the CURRENTLY OPEN db_transaction_state, exposed
# so the outbox row can be written inside that same transaction. A
# contextvar rather than a changed yield signature: the transaction is
# ambient state for the duration of the block, and threading it through
# six call sites (plus tests) would obscure the one place that needs it.
# None means the in-process branch is active — there is no transaction to
# join, and the outbox falls back to its own write.
# Typed Any deliberately: the connection is a sqlite3.Connection or a
# psycopg.Connection depending on the configured backend, and the outbox
# adapter that receives it is chosen by the same switch.
_ACTIVE_TX_CONNECTION: "_contextvars.ContextVar[Any]" = (
    _contextvars.ContextVar("remora_active_tx_connection", default=None)
)

# Built eagerly, like _CHAIN and _GATE: a durable adapter runs its DDL on
# its own connection, and doing that lazily inside an open transaction
# deadlocks against SQLite's BEGIN EXCLUSIVE write lock.
_OUTBOX: "ExecutionOutbox | None" = None


def _outbox() -> ExecutionOutbox:
    """The dispatch-intent store, chosen by the same durability switches
    that govern the chain, queue and jti ledger (REM-034/REM-025).

    An in-process outbox is a development fallback: it loses the record
    that a dispatch was authorized, which is precisely what FT-02 exists
    to make durable. Production mode already refuses to start without one
    of these variables set.
    """
    global _OUTBOX
    if _OUTBOX is None:
        _OUTBOX = _build_outbox()
    return _OUTBOX


def _build_outbox() -> ExecutionOutbox:
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    db = _os.environ.get("REMORA_CHAIN_DB", "").strip()
    if dsn:
        return PostgresExecutionOutbox(dsn)
    if db:
        return SQLiteExecutionOutbox(db)
    return ExecutionOutbox()


def _reset_outbox() -> None:
    """Test hook: rebuild the outbox eagerly (e.g. after env changes).

    Eager, not lazy: constructing a durable adapter runs its DDL on its own
    connection, and doing that lazily inside an open ``db_transaction_state``
    deadlocks against SQLite's ``BEGIN EXCLUSIVE`` write lock until the
    driver timeout. Building it up front keeps schema work out of every
    request path (found by running the wiring suite against a real
    REMORA_CHAIN_DB, 2026-08-05).
    """
    global _OUTBOX
    _OUTBOX = _build_outbox()


# Eager, at import — same discipline as _CHAIN/_GATE above.
_OUTBOX = _build_outbox()


DEFAULT_OUTBOX_STALE_SECONDS = 900


def reconcile_stale_dispatches(tenant: str, *, now=None) -> list:
    """Settle dispatch intents whose worker never reported back.

    A row stuck in ``DISPATCHING`` past the staleness threshold has an
    undeterminable side effect: the worker may have invoked the tool before
    dying. It is settled as ``UNKNOWN`` — never retried, because re-running
    a call that may already have taken effect is the one move the execution
    layer must never make — and each reconciliation is appended to the
    tenant audit chain so an undeterminable outcome is visible rather than
    silently absorbed.

    Threshold: ``REMORA_OUTBOX_STALE_SECONDS`` (default 900). Called as a
    lazy sweep on every execution-path interaction, exactly like REM-032's
    review-queue TTL sweep; an IDLE tenant is not swept by that, so a
    deployment wanting wall-clock reconciliation must call this on a
    schedule. Resolving an UNKNOWN afterwards is a manual operator
    decision that produces a new record (maintainer decision 2026-08-05) —
    it never rewrites the terminal state.
    """
    raw = _os.environ.get("REMORA_OUTBOX_STALE_SECONDS", "").strip()
    try:
        seconds = int(raw) if raw else DEFAULT_OUTBOX_STALE_SECONDS
    except ValueError:
        seconds = DEFAULT_OUTBOX_STALE_SECONDS
    try:
        window = timedelta(seconds=seconds)
        settled = _outbox().reconcile_stale(tenant, older_than=window, now=now)
        # Crash matrix row 2: an intent committed by the authorize
        # transaction but never claimed. The claim strictly precedes the
        # tool invocation, so nothing was dispatched and FAILED is
        # provable — UNKNOWN would overstate the uncertainty.
        settled = settled + _outbox().reconcile_unclaimed(
            tenant, older_than=window, now=now
        )
    except Exception:
        # Reconciliation is a background courtesy on the request path: it
        # must never turn a healthy assess/execute into a 500. The rows
        # stay DISPATCHING and the next sweep retries them.
        _LOGGER.exception("outbox reconciliation failed for tenant %s", tenant)
        return []
    for row in settled:
        _CHAIN.append(tenant, {
            "event": ("dispatch_never_dispatched"
                      if row.state.value == "FAILED" else "dispatch_unknown"),
            "proposal_id": row.proposal_id,
            "outbox_id": row.outbox_id,
            "item_id": row.item_id,
            "tool_name": row.tool_name,
            "tool_call_hash": row.tool_call_hash,
            "claimed_by": row.worker_id,
            "detail": row.detail,
        })
    return settled


def _record_dispatch_intent(
    *,
    proposal_id: str,
    tenant: str,
    item_id: str,
    tool_name: str,
    tool_call_hash: str,
    grant_jti: str,
):
    """Record the dispatch intent, inside the authorize transaction when one
    is open.

    With a durable backend the row commits with the authorization and rolls
    back with it, so "authorized" and "a dispatch was intended" can never
    disagree. Without one (development), the in-process store records it
    non-atomically — a limitation of that configuration, not of the design.
    """
    outbox = _outbox()
    connection = _ACTIVE_TX_CONNECTION.get()
    # Only the durable adapters can join a transaction; the in-process base
    # class refuses enlistment by design rather than faking the guarantee.
    if connection is not None and type(outbox) is not ExecutionOutbox:
        return outbox.record_intent_enlisted(
            connection,
            proposal_id=proposal_id,
            tenant_id=tenant,
            item_id=item_id,
            tool_name=tool_name,
            tool_call_hash=tool_call_hash,
            grant_jti=grant_jti,
        )
    return outbox.record_intent(
        proposal_id=proposal_id,
        tenant_id=tenant,
        item_id=item_id,
        tool_name=tool_name,
        tool_call_hash=tool_call_hash,
        grant_jti=grant_jti,
    )


def _lifecycle_guard(start: str, *events: str) -> None:
    """FT-01 conformance: the transition this endpoint is about to perform
    must be declared by the lifecycle model. Defense-in-depth — the queue's
    own guards stay primary; an undeclared move here means the runtime and
    the declared machine have drifted, which is an internal inconsistency
    surfaced loudly (HTTP 500), never silently absorbed."""
    state = start
    try:
        for event in events:
            state = check_transition(state, event)
    except IllegalTransition as exc:
        raise HTTPException(
            status_code=500, detail=f"lifecycle conformance violation: {exc}"
        ) from exc


def _auth(request: Request) -> tuple[str, str, str]:
    from servers import api as api_mod

    tenant, role = api_mod._authenticate(request)
    return tenant, role, api_mod._authenticated_principal(request)


import json
import dataclasses
from uuid import uuid4
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
                # Snapshot the in-memory mirrors: the DB transaction rolls
                # back on exception, but q._items / _ITEM_TENANT would keep
                # aborted mutations and leak them into the NEXT successful
                # commit (self-review 2026-07-28).
                items_snapshot = dict(q._items)
                tenant_snapshot = dict(_ITEM_TENANT)
                _tx_token = _ACTIVE_TX_CONNECTION.set(conn)
                try:
                    yield q
                except BaseException:
                    q._items = items_snapshot
                    _ITEM_TENANT.clear()
                    _ITEM_TENANT.update(tenant_snapshot)
                    raise
                else:
                    conn.execute(
                        "INSERT INTO global_state (tenant_id, qs_json, it_json) VALUES (%s, %s, %s) "
                        "ON CONFLICT (tenant_id) DO UPDATE SET qs_json = EXCLUDED.qs_json, it_json = EXCLUDED.it_json",
                        (tenant, json.dumps({k: to_dict(v) for k, v in q._items.items()}), json.dumps(_ITEM_TENANT))
                    )
                finally:
                    _ACTIVE_TX_CONNECTION.reset(_tx_token)
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
            # Snapshot in-memory mirrors (see Postgres branch comment).
            items_snapshot = dict(q._items)
            tenant_snapshot = dict(_ITEM_TENANT)
            _tx_token = _ACTIVE_TX_CONNECTION.set(conn)
            try:
                yield q
            except BaseException:
                # An exception inside the handler must roll the WHOLE
                # transaction back — the DB via rollback(), and the
                # in-memory mirrors via snapshot restore — never persist
                # partially mutated queue state (external review
                # 2026-07-28, N1 + self-review follow-up).
                conn.rollback()
                q._items = items_snapshot
                _ITEM_TENANT.clear()
                _ITEM_TENANT.update(tenant_snapshot)
                raise
            else:
                conn.execute(
                    "INSERT INTO global_state (tenant_id, qs_json, it_json) VALUES (?, ?, ?) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET qs_json = excluded.qs_json, it_json = excluded.it_json",
                    (tenant, json.dumps({k: to_dict(v) for k, v in q._items.items()}), json.dumps(_ITEM_TENANT))
                )
                conn.commit()
            finally:
                _ACTIVE_TX_CONNECTION.reset(_tx_token)
    else:
        # In-process branch: no database to roll back, but the SAME
        # all-or-nothing promise must hold or crash-matrix row 1 is false
        # here — a failed authorization would leave the item AUTHORIZED and
        # not re-executable (found by the fault-injection suite, 2026-08-05).
        with q._lock:
            # DEEP copy: q.execute() mutates the PendingReview in place, so a
            # shallow dict copy restores the mapping while leaving the item
            # itself mutated. The durable branches survive this because their
            # next transaction reloads every item from the store; in-process
            # has no such reload, so the snapshot must own its objects.
            items_snapshot = _copy.deepcopy(q._items)
            tenant_snapshot = dict(_ITEM_TENANT)
            try:
                yield q
            except BaseException:
                q._items = items_snapshot
                _ITEM_TENANT.clear()
                _ITEM_TENANT.update(tenant_snapshot)
                raise


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


# ── Semantic bundle (SHELF-020) ────────────────────────────────────────────
#
# With REMORA_SEMANTIC_BUNDLE_MODULE configured, the assess/execute
# observation is built by build_full_observation — the same authoritative
# context builder the benchmarks lock — over the deployment-declared
# contract bundle. The cache is keyed on the module spec so a test (or a
# redeployment) that unsets the variable falls back to the registry-only
# path instead of consulting a stale bundle.

_SEMANTIC: "tuple[str, SemanticBundle | None, IntentResolver | None] | None" = None


def _semantic_bundle() -> "tuple[SemanticBundle | None, IntentResolver | None]":
    global _SEMANTIC
    spec = _os.environ.get("REMORA_SEMANTIC_BUNDLE_MODULE", "").strip()
    if _SEMANTIC is None or _SEMANTIC[0] != spec:
        if not spec:
            _SEMANTIC = (spec, None, None)
        else:
            _SEMANTIC = (spec, load_semantic_bundle(), load_intent_resolver())
    return _SEMANTIC[1], _SEMANTIC[2]


def _reset_semantic_bundle() -> None:
    """Test hook: drop the cached bundle (e.g. after env changes)."""
    global _SEMANTIC
    _SEMANTIC = None


def _jsonable(value: Any) -> Any:
    """Best-effort JSON projection of a tool result for response/audit.

    Kept for callers that want the raw projection. The governed dispatch path
    uses :func:`capture_tool_result` instead, which bounds what is retained
    while still hashing the full result.
    """
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return repr(value)


# ── OpenAPI contract models (documentation-only) ───────────────────────────
#
# These models type the wire contract for Swagger and generated clients. They
# are attached via `responses={200: {"model": ...}}`, NOT `response_model=`,
# deliberately: the handlers build their dicts incrementally and conditional
# keys are ABSENT, never null (pinned by test_execution_api.py), while the
# semantic booleans are always present even when None. A response_model would
# either inject null keys or, with exclude_none, drop the nullable-but-present
# fields — both are wire-format changes. Timestamps stay `str`: they are
# pre-serialized ISO-8601 and retyping them as datetime would let Pydantic
# re-normalize the string form.

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


#: Semantic context with no bundle configured: absent, never defaulted.
_NO_SEMANTIC_CONTEXT: dict[str, Any] = {
    "tool_contract_bundle_hash": "",
    "state_hash": "",
    "intent_authority_hash": "",
    "tool_matches_goal": None,
    "expected_effect_matches": None,
}


def _observation_with_context(
    req: ToolCallRequest, tenant: str
) -> tuple[PolicyObservation, dict[str, Any]]:
    """The authoritative observation plus the semantic-binding context.

    With a semantic bundle configured, every task-tool safety field comes
    from ``build_full_observation`` — the execution path never assembles
    semantic fields by hand, and no request field can set one. The
    executive metadata the builder does not produce (risk tier, target
    environment, downgrade-only flags, session binding) is then overlaid
    from the server-side registry, exactly as the legacy path derived it.
    """
    registry_entry = TOOL_REGISTRY.get(req.tool_name, {
        "risk_tier": "critical",
        "domain": "unknown",
        "action_type": "unknown"
    })
    full, context = semantic_call_context(
        tool_name=req.tool_name,
        arguments=req.arguments,
        tenant=tenant,
        intent_ref=req.intent_ref,
        untrusted_context=req.untrusted_context,
        domain=str(registry_entry.get("domain", "unknown")),
        derivations=tuple(
            d.model_dump() for d in (req.derivations or ())
        ),
    )
    if full is None:
        return _registry_only_observation(req, tenant, registry_entry), context

    target_environment = str(
        registry_entry.get("target_environment", req.target_environment)
    )
    args_preview = json.dumps(
        req.arguments, sort_keys=True, separators=(",", ":"), default=str
    )[:120]
    obs = dataclasses.replace(
        full,
        question=full.question or f"{req.tool_name}({args_preview})",
        risk_tier=str(registry_entry.get("risk_tier", "critical")),
        action_type=str(registry_entry.get("action_type")) if req.tool_name in TOOL_REGISTRY else full.action_type,
        target_environment=target_environment,
        schema_valid=_downgrade_only_bool(
            registry_entry.get("schema_valid"), req.schema_valid
        ),
        rollback_available=_downgrade_only_bool(
            registry_entry.get("rollback_available"), req.rollback_available
        ),
        session_id=tenant,
        tool_call_hash=canonical_tool_call_hash(
            name=req.tool_name,
            arguments=req.arguments,
            tenant=tenant,
            target=target_environment,
        ),
    )
    return obs, context


def semantic_call_context(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    tenant: str,
    intent_ref: str | None = None,
    untrusted_context: str | None = None,
    domain: str = "unknown",
    user_task: str = "",
    derivations: "tuple[dict[str, Any], ...]" = (),
) -> "tuple[PolicyObservation | None, dict[str, Any]]":
    """Authoritative semantic observation + context for one proposed call.

    Shared by ``/v1/execution/assess`` and ``/v1/assess`` so both endpoints
    run the SAME context builder (``build_full_observation``) over the same
    deployment-declared bundle — no endpoint assembles semantic fields by
    hand, and no request field can set one. Returns ``(None, no-semantic
    context)`` when no bundle is configured: recorded absence, never a
    fabricated verdict. ``user_task`` is the fallback task text when no
    intent resolves; a resolved intent's ``task_text`` always wins.
    """
    bundle, resolver = _semantic_bundle()
    if bundle is None:
        return None, dict(_NO_SEMANTIC_CONTEXT)

    from remora.toolcall.routing.episode import RoutingEpisode
    from remora.toolcall.routing.evaluate import build_full_observation

    resolved = (
        resolver(intent_ref) if (resolver is not None and intent_ref) else None
    )
    episode = RoutingEpisode(
        id=f"exec:{tenant}:{tool_name}",
        source_dataset="execution_api",
        source_commit="",
        cluster_id=f"exec:{tenant}",
        user_task=resolved.task_text if resolved else user_task,
        available_tools=tuple(sorted(bundle.registry.signatures)),
        untrusted_context=untrusted_context or None,
        proposed_tool_name=tool_name,
        proposed_tool_args=dict(arguments),
        domain=domain,
        proposed_derivations=derivations,
    )
    validators = (
        bundle.validators.scoped(tenant) if bundle.validators is not None else None
    )
    full = build_full_observation(
        episode,
        bundle.registry,
        bundle.state,
        validators=validators,
        contracts=bundle.contracts,
        intent=resolved.intent if resolved else None,
    )
    from remora.toolcall.routing.derivation import (
        DERIVATION_TRANSFORMS_DIGEST,
        DERIVATION_TRANSFORMS_VERSION,
    )

    context = {
        "tool_contract_bundle_hash": bundle.bundle_hash,
        "state_hash": bundle.state_hash,
        "intent_authority_hash": (
            compute_intent_authority_hash(resolved) if resolved else ""
        ),
        "tool_matches_goal": full.tool_matches_goal,
        "expected_effect_matches": full.expected_effect_matches,
        # Receipt-vocabulary identity (review 2026-08-05): a receipt
        # verified under one transform semantics must never silently mean
        # something else later. Rides the audit record with the other
        # semantic hashes; lease/ToolSpec binding is FT-03 scope.
        "derivation_transforms_version": DERIVATION_TRANSFORMS_VERSION,
        "derivation_transforms_digest": DERIVATION_TRANSFORMS_DIGEST,
    }
    return full, context


def _observation(req: ToolCallRequest, tenant: str) -> PolicyObservation:
    return _observation_with_context(req, tenant)[0]


def _registry_only_observation(
    req: ToolCallRequest, tenant: str, registry_entry: dict[str, Any]
) -> PolicyObservation:
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



@router.post("/assess", responses={
    200: {"model": ExecutionAssessResponse,
          "description": "Governance decision; conditional keys are absent, never null."},
    **_AUTH_RESPONSES,
})
def assess(req: ToolCallRequest, request: Request) -> dict[str, Any]:
    """Assess a proposed tool call — nothing executes here.

    Authoritative signals (risk tier, action type, domain, semantic context)
    are derived server-side from the tool registry and the deployment's
    semantic bundle; the request is a proposal and can only lower trust,
    never raise it. ACCEPT returns a signed single-use execution token;
    VERIFY/ESCALATE enqueue a review item for a human; ABSTAIN returns
    neither. Every assessment appends to the tenant audit chain.
    """
    tenant, role, principal = _auth(request)
    idemp_key = f"assess:{tenant}:{req.idempotency_key}" if req.idempotency_key else None
    if idemp_key:
        cached = _idempotency_get(idemp_key)
        if cached is not None:
            return cached

    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "assess")
    # FT-02 lazy sweep (same discipline as REM-032's TTL sweep): a dispatch
    # whose worker never reported back is settled as UNKNOWN before new
    # work is considered, so a stranded intent cannot linger unnoticed.
    reconcile_stale_dispatches(tenant)
    obs, semantic = _observation_with_context(req, tenant)
    # FT-01: mint the canonical proposal identity here — every downstream
    # record, response and grant for this action carries it. Attached to the
    # observation so it survives the durable review queue.
    proposal_id = str(uuid4())
    obs = dataclasses.replace(obs, proposal_id=proposal_id)
    report = _ENGINE.decide(obs)
    now = datetime.now(UTC)
    record: dict[str, Any] = {
        "event": "assessed",
        "proposal_id": proposal_id,
        "actor": principal,
        "tool_name": req.tool_name,
        "tool_call_hash": obs.tool_call_hash,
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "policy_version": report.policy_version,
        # SHELF-020: the decision names the declaration set and intent source
        # it was made under. Empty strings mean "no bundle configured" — the
        # registry-only path, recorded rather than assumed away.
        "tool_contract_bundle_hash": semantic["tool_contract_bundle_hash"],
        "state_hash": semantic["state_hash"],
        "intent_authority_hash": semantic["intent_authority_hash"],
    }
    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "tool_call_hash": obs.tool_call_hash,
        "semantic": dict(semantic),
    }
    # FT-01 conformance: the assess flow's shape must match the declared
    # machine (PROPOSED → ASSESSED → branch) before anything is recorded.
    _branch_event = {
        DecisionAction.ACCEPT: "direct_accept_token",
        DecisionAction.VERIFY: "verify_or_escalate",
        DecisionAction.ESCALATE: "verify_or_escalate",
        DecisionAction.ABSTAIN: "abstain_or_hard_refusal",
    }.get(report.action, "abstain_or_hard_refusal")
    _lifecycle_guard("PROPOSED", "engine_decision", _branch_event)

    if report.action is DecisionAction.ACCEPT:
        token = PolicyDecisionToken.issue(
            action="accept",
            observation_hash=obs.tool_call_hash or "",
            request_id=proposal_id,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=EXECUTION_TOKEN_TTL_SECONDS)).isoformat(),
            audience=PEP_AUDIENCE,
        )
        record["grant_jti"] = token.jti
        response["execution_token"] = token.to_dict()
    else:
        with db_transaction_state(tenant) as q:
            # REM-032 lazy sweep: every queue interaction first resolves
            # overdue PENDING items to ABSTAIN (with their events), so an
            # unattended item cannot outlive its TTL past the tenant's next
            # touch. Idle-queue wall-clock expiry needs a scheduled
            # expire_due() — documented in the quickstart.
            q.expire_due()
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
    api_mod.record_execution_assess(report.action.value)

    if idemp_key:
        _idempotency_put(idemp_key, response)
    return response


class ApproveRequest(BaseModel):
    item_id: str
    approval_ttl_seconds: int = Field(900, gt=0, le=86400)
    on_behalf_of: str | None = Field(
        None,
        description="Client-declared annotation only, recorded in the audit "
                    "chain as unverified metadata. The audited approver "
                    "identity is always the authenticated principal from the "
                    "bearer token — this field can never delegate authority.")


@router.post("/approve", responses={
    200: {"model": ExecutionApproveResponse},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "Review item not found for this tenant."},
    409: {"model": ErrorDetail,
          "description": "Item not pending, queue TTL exceeded, or invalid approval TTL."},
})
def approve(req: ApproveRequest, request: Request) -> dict[str, Any]:
    """Record an approval by the authenticated reviewer.

    The approver identity comes from the credential, never from the request
    body; `on_behalf_of` is recorded in the audit chain as client-declared,
    unverified metadata. Role separation is enforced: the operator role that
    proposed the action cannot approve it, and a tenant's risk profile may
    reserve approval for domain_expert/senior_authority. The approval TTL is
    mandatory and bounded.
    """
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
            # REM-032 lazy sweep (see assess); an expired target then fails
            # q.approve with "not pending", surfaced as 409.
            q.expire_due()
            approval = q.approve(
                req.item_id, approver=principal,
                approval_ttl=timedelta(seconds=req.approval_ttl_seconds),
            )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # FT-01 conformance, AFTER the queue accepted: the move the queue just
    # performed (pending → approved) must be one the declared machine
    # allows. Client errors (expired/unknown items) stay the queue's 409s;
    # this catches drift between runtime and model — a loud 500.
    _lifecycle_guard("REVIEW_PENDING", "human_approval")
    proposal_id = getattr(item.observation, "proposal_id", None)
    entry = _CHAIN.append(tenant, {
        "event": "approved",
        "proposal_id": proposal_id,
        "actor": principal,
        "on_behalf_of": req.on_behalf_of,
        "item_id": req.item_id,
        "expires_at": approval.expires_at.isoformat(),
    })
    api_mod.record_execution_approval()
    return {
        "status": "approved",
        "proposal_id": proposal_id,
        "item_id": req.item_id,
        "expires_at": approval.expires_at.isoformat(),
        "audit": {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash},
    }


class ExecuteRequest(BaseModel):
    """Execute an approved item — the FULL payload is re-presented and the
    fresh world state re-gated; the grant is single-use."""

    item_id: str
    tool_call: ToolCallRequest


@router.post("/execute", responses={
    200: {"model": ExecutionExecuteResponse,
          "description": "Outcome of enforcement; refusal outcomes carry no "
                         "grant/pep/tool_execution keys."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "Review item not found for this tenant."},
    409: {"model": ErrorDetail, "description": "Item not in an executable state."},
})
def execute(req: ExecuteRequest, request: Request) -> dict[str, Any]:
    """Execute a previously approved item under full re-gating.

    The complete payload is re-presented and freshly re-decided: an
    equal-or-safer world state executes, a stricter one invalidates the
    approval, and changed arguments are refused by exact payload binding. A
    single-use grant is consumed atomically, and the tool is dispatched
    through the governed dispatcher under a lease bound to the current
    policy bundle hash. Both the pre-dispatch authorization and the result
    are separate records in the tenant audit chain.
    """
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "execute")
    reconcile_stale_dispatches(tenant)  # FT-02 lazy sweep (see assess)
    fresh_obs, fresh_semantic = _observation_with_context(req.tool_call, tenant)
    try:
        # Tenant-binding check inside the transaction: _ITEM_TENANT is
        # rehydrated from the durable store by the load (review finding 2a).
        with db_transaction_state(tenant) as q:
            if _ITEM_TENANT.get(req.item_id) != tenant:
                raise HTTPException(status_code=404, detail="review item not found")
            # REM-032 lazy sweep (see assess): overdue PENDING items resolve
            # to ABSTAIN before any execution is considered.
            q.expire_due()
            # FT-01: the canonical proposal identity rides the QUEUED
            # observation (minted at assess) — the fresh re-presented
            # payload never carries one the caller could assert.
            proposal_id = getattr(q.item(req.item_id).observation,
                                  "proposal_id", None)
            outcome = q.execute(req.item_id, fresh_obs)
            # FT-02: the dispatch intent is recorded in THIS transaction —
            # the one that authorizes the call. If anything below crashes,
            # a durable row says a dispatch was authorized, and a
            # reconciler can settle it as UNKNOWN instead of the effect
            # going unrecorded. A refusal never gets here, so a refused
            # re-gate records no intent (nothing was ever intended).
            intent = None
            if outcome.decision is ExecutionDecision.EXECUTE:
                intent = _record_dispatch_intent(
                    proposal_id=str(proposal_id or req.item_id),
                    tenant=tenant,
                    item_id=req.item_id,
                    tool_name=req.tool_call.tool_name,
                    tool_call_hash=fresh_obs.tool_call_hash or "",
                    grant_jti="",
                )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "outcome": outcome.decision.value,
        "detail": outcome.detail,
    }
    if outcome.decision is not ExecutionDecision.EXECUTE:
        # FT-01 conformance: every re-gate refusal is a declared move from
        # AUTHORIZED (approval and post-re-gate authorization collapse there
        # in the model). Dispatch-stage conformance arrives with FT-02.
        _lifecycle_guard("AUTHORIZED", "regate_binding_or_freshness_refusal")
        entry = _CHAIN.append(tenant, {
            "event": f"execution_{outcome.decision.value}",
            "proposal_id": proposal_id,
            "actor": principal,
            "item_id": req.item_id,
            "tool_call_hash": fresh_obs.tool_call_hash,
            "detail": outcome.detail,
        })
        response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
        api_mod.record_execution_execute(
            executed=False, refusal=outcome.decision.value
        )
        return response

    # The re-gate only AUTHORIZED the call (persisted above); EXECUTED is
    # recorded separately after the dispatcher reports what actually
    # happened (external review 2026-07-27: authorized-for-execution and
    # actually-executed are distinct states).
    now = datetime.now(UTC)
    token = PolicyDecisionToken.issue(
        action="accept",
        observation_hash=fresh_obs.tool_call_hash or "",
        # FT-01: the grant carries the canonical proposal identity; the
        # legacy composite only for pre-lifecycle items with no proposal.
        request_id=proposal_id or f"{tenant}:{req.item_id}",
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
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": req.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
        "tool_contract_bundle_hash": fresh_semantic["tool_contract_bundle_hash"],
        "intent_authority_hash": fresh_semantic["intent_authority_hash"],
    })

    # Issue #13: actually dispatch the tool through the governed dispatcher —
    # the response reports what REALLY happened instead of implying
    # execution. Every refusal path is explicit and audited.
    # FT-02: claim the intent before anything can take effect. The claim is
    # exclusive, so a concurrent worker (or a retried request that got past
    # the grant) can never dispatch the same authorized call twice.
    if intent is not None:
        _outbox().claim(intent.outbox_id, worker_id=f"api:{_os.getpid()}")

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
                    tool_contract_bundle_hash=fresh_semantic[
                        "tool_contract_bundle_hash"
                    ],
                    intent_authority_hash=fresh_semantic["intent_authority_hash"],
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
                        # Bounded retention, unbounded verification: the hash
                        # covers the full result even when the preview is
                        # truncated, so an oversized or hostile tool output
                        # cannot inflate the audit chain or the response while
                        # still being provable in replay.
                        captured = capture_tool_result(dres.result)
                        tool_execution["result"] = captured.preview
                        tool_execution["result_envelope"] = captured.to_dict()
                    else:
                        tool_execution["refusal_reason"] = dres.refusal_reason

    # FT-02: settle the dispatch intent with what actually happened. The
    # terminal state is derived from the observed outcome, never assumed:
    # a confirmed side effect is SUCCEEDED, a burned nonce with no effect
    # is FAILED, and a pre-effect refusal is REFUSED.
    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        if tool_execution["executed"]:
            settled_state = OutboxState.SUCCEEDED
        elif reason == "tool_failed_nonce_burned":
            settled_state = OutboxState.FAILED
        else:
            settled_state = OutboxState.REFUSED
        _outbox().settle(intent.outbox_id, settled_state, detail=reason)

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
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": req.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "intent_sequence_no": intent_entry.sequence_no,
        "tool_executed": tool_execution["executed"],
    }
    # The chain records the result's identity, never the result body: a
    # verbose tool must not be able to grow the audit chain without bound.
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    entry = _CHAIN.append(tenant, result_record)

    response["tool_execution"] = tool_execution
    response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
    api_mod.record_execution_execute(
        executed=bool(tool_execution["executed"]),
        refusal=tool_execution.get("refusal_reason"),
    )
    return response


@router.get("/audit/verify", responses={
    200: {"model": ExecutionAuditVerifyResponse},
    **_AUTH_RESPONSES,
})
def audit_verify(request: Request) -> dict[str, Any]:
    """Verify this tenant's execution audit chain.

    Distinct from `/v1/audit/chain/verify`, which verifies the
    DecisionEnvelope chain in the control-plane store: this chain records
    the execution lifecycle (assessed → approved → execution_authorized →
    execution_result). Reports how many records were checked; an empty
    chain is trivially valid and is flagged as such.
    """
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    ok, problems = _CHAIN.verify(tenant)
    records_checked = len(_CHAIN.entries(tenant))
    return {
        "tenant": tenant,
        "valid": ok,
        "problems": problems,
        # An empty chain is trivially valid; auditors and the evidence bundle
        # must be able to tell "verified history" from "nothing to verify".
        "records_checked": records_checked,
        "empty": records_checked == 0,
    }
