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

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.lease import (
    ExecutionLease,
    GovernedToolDispatcher,
)
from remora.enforcement.nonce_store import DurableNonceStore, NonceStore
from remora.enforcement.outbox import (
    ExecutionOutbox,
    PostgresExecutionOutbox,
    SQLiteExecutionOutbox,
    UnbackedExecutionOutbox,
)
from remora.enforcement.token import PolicyDecisionToken
from remora.governance import audit_outbox as _audit_outbox
from remora.governance.delegation import delegated_executor_of, delegation_refusal
from remora.governance.effect_receipt import (
    ReceiptRefused,
)
from remora.governance.effect_receipt import (
    verify_receipt as verify_effect_receipt,
)
from remora.governance.effect_verification import (
    EffectVerification,
)
from remora.governance.execution_identity import (
    ExecutionContextRefused,
    ExecutionContextV1,
    historical_context,
)
from remora.governance.lifecycle import (
    IllegalTransition,
    check_transition,
)
from remora.governance.loop_safety import (
    DurableLoopSafetyStore,
    InMemoryLoopSafetyStore,
    LoopSafetyMonitor,
    LoopSafetyStoreUnavailable,
)
from remora.governance.review_queue import (
    ReviewQueue,
)
from remora.governance.revocation_store import (
    DurableRevocationStore,
    RevocationStore,
    RevocationStoreUnavailable,
)
from remora.governance.task_identity import TaskIdentity
from remora.governance.tenant_chain import TenantAuditChain
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation, canonical_tool_call_hash
from remora.policy.report import DecisionAction
from remora.toolcall.deployment_registry import resolve_tool_metadata
from remora.toolcall.semantic_bundle import (
    IntentResolver,
    SemanticBundle,
    compute_intent_authority_hash,
    load_argument_scope_validator,
    load_intent_resolution_provider,
    load_intent_resolver,
    load_semantic_bundle,
)
from remora.toolcall.toolspec import ToolSpecBundle, ToolSpecRefused

# Wire contracts (issue #241 extraction slice 1): request/response Pydantic
# models live in servers/execution_contracts.py; re-imported here so existing
# `from servers.execution_api import ToolCallRequest` style access keeps
# working (test suites patch through this module's namespace).
from servers.execution_contracts import (  # noqa: F401
    _AUTH_RESPONSES,
    ApproveRequest,
    AuditRef,
    ContextMintRequest,
    ContextMintResponse,
    DerivationProposal,
    DispatchLeasedRequest,
    EffectVerificationRequest,
    ErrorDetail,
    ExecuteAcceptedRequest,
    ExecuteRequest,
    ExecutionApproveResponse,
    ExecutionAssessResponse,
    ExecutionAuditVerifyResponse,
    ExecutionExecuteResponse,
    ExecutionGrant,
    ExecutionOutcome,
    ExecutionPendingResponse,
    ExecutionStopRequest,
    GovernanceAction,
    LimitResolveRequest,
    LoopSafetyResetRequest,
    PepResult,
    RejectRequest,
    RevokeAuthorityRequest,
    RevokePrincipalRequest,
    SemanticAssessment,
    SignedEffectReceiptRequest,
    ToolCallRequest,
    ToolExecutionResult,
    ToolResultEnvelopeModel,
)
from servers.execution_identity import context_provider, context_required

#: The only path the execution domain serves.
#:
#: Exact equality, not a prefix or a substring. An allowlist that matches
#: loosely is the defect this repository already recorded once: a WITH ...
#: INSERT passed a read-only SQL check because the match was unanchored
#: (NEGATIVE_RESULTS section 51). A prefix test here would admit
#: /dispatch-leased-anything.
_EXECUTOR_PATHS = frozenset({"/v1/execution/dispatch-leased"})
#: The only routes the effect domain serves (NTA-2 phase 3), and the only
#: domain that serves them. Exact equality, for the reason above.
_EFFECT_PATHS = frozenset({"/v1/execution/effects", "/v1/execution/effects/close"})

#: IFC-11 (derived information-flow control SDD §4), the execution API's
#: mediation surface, classified. A tool runs, and a tool result returns, only
#: through the three TOOL_DISPATCH routes and the worker entry, all of which
#: hand the call to _dispatch_under_lease (the flow check, the lease, the
#: nonce and the result commit live there). Every other route reaches no tool
#: and returns no tool result. scripts/check_flow_mediation_surface.py holds
#: both routers to this classification, statically, and
#: tests/flow/test_mediation_surface.py fails when a route joins neither set:
#: a new route is unclassified until someone says which kind it is.
MEDIATION_TOOL_DISPATCH = frozenset({
    ("POST", "/v1/execution/execute"),
    ("POST", "/v1/execution/execute-accepted"),
    ("POST", "/v1/execution/dispatch-leased"),
})
MEDIATION_NO_TOOL_RESULT = frozenset({
    # decide, review, settle: no tool runs, nothing a tool returned is served
    ("POST", "/v1/execution/assess"),
    ("POST", "/v1/execution/approve"),
    ("POST", "/v1/execution/reject"),
    ("POST", "/v1/contexts"),
    # authority state changes: revocations, limits, the stop switch, loops
    ("POST", "/v1/execution/revoke-principal"),
    ("POST", "/v1/execution/revoke-authority"),
    ("POST", "/v1/execution/stop"),
    ("POST", "/v1/execution/resume"),
    ("GET", "/v1/execution/stop"),
    ("GET", "/v1/execution/limits/unresolved"),
    ("POST", "/v1/execution/limits/resolve"),
    ("GET", "/v1/execution/loop-safety/{context_id}"),
    ("POST", "/v1/execution/loop-safety/reset"),
    # the effect domain's own routes: the effect credential, not the tool callable
    ("POST", "/v1/execution/effects"),
    ("POST", "/v1/execution/effects/close"),
    # readers and evidence: records of what happened, never a live result
    ("GET", "/v1/execution/capabilities"),
    ("GET", "/v1/execution/proposals/{proposal_id}"),
    ("GET", "/v1/execution/proposals/{proposal_id}/semantic-assessment"),
    ("POST", "/v1/execution/proposals/{proposal_id}/effect"),
    ("POST", "/v1/execution/proposals/{proposal_id}/effect-receipt"),
    ("GET", "/v1/execution/proposals/{proposal_id}/lifecycle"),
    ("GET", "/v1/execution/proposals/{proposal_id}/envelope"),
    ("GET", "/v1/execution/proposals/{proposal_id}/evidence"),
    ("GET", "/v1/execution/proposals/{proposal_id}/invocation-evidence"),
    ("GET", "/v1/execution/audit/verify"),
})
#: Non-route entry points that dispatch: the async worker.
MEDIATION_WORKER_ENTRIES = frozenset({"dispatch_pending_intents"})

#: Which half of the custody split this process is.
#:
#: The split gave the execution container its own credentials and only the
#: public verification key, but it kept serving the whole router: assess,
#: approve, execute, reject, the audit reader. A compromise there could
#: therefore authorize work as well as perform it, which is exactly the
#: property the split claims to remove (RMR-013). The default is "authority",
#: so an unconfigured deployment behaves as it always did.
_DOMAIN_AUTHORITY = "authority"
_DOMAIN_EXECUTOR = "executor"
_DOMAIN_EFFECT = "effect"


def _execution_domain() -> str:
    value = (_os.getenv("REMORA_EXECUTION_DOMAIN_ROLE") or "").strip().lower()
    if value in (_DOMAIN_AUTHORITY, _DOMAIN_EXECUTOR, _DOMAIN_EFFECT):
        return value
    if value:
        # An unrecognised role is a configuration error, and guessing which
        # domain was meant is the wrong way to resolve it.
        raise RuntimeError(
            f"REMORA_EXECUTION_DOMAIN_ROLE={value!r} is not one of "
            f"{_DOMAIN_AUTHORITY!r}, {_DOMAIN_EXECUTOR!r}, {_DOMAIN_EFFECT!r}")
    return _DOMAIN_AUTHORITY


def _enforce_execution_domain(request: Request) -> None:
    """Refuse authority routes when this process is the executor.

    Attached to the router rather than to each route: a per-route decorator is
    a list that a new endpoint silently fails to join, and that failure mode is
    an authority route quietly reachable from the execution domain.
    """
    role = _execution_domain()
    path = request.url.path
    if role == _DOMAIN_EFFECT:
        if path in _EFFECT_PATHS:
            return
        raise HTTPException(status_code=404, detail="not served by the effect domain")
    if path in _EFFECT_PATHS:
        # Effects run only where the effect credentials are.
        raise HTTPException(status_code=404, detail="served only by the effect domain")
    if role != _DOMAIN_EXECUTOR:
        return
    if path in _EXECUTOR_PATHS:
        return
    raise HTTPException(
        status_code=404,
        detail="not served by the execution domain")


router = APIRouter(
    prefix="/v1/execution",
    tags=["execution"],
    dependencies=[Depends(_enforce_execution_domain)],
)

PEP_AUDIENCE = "pep://remora-execution"
EXECUTION_TOKEN_TTL_SECONDS = 300

def _engine_from_env() -> RemoraDecisionEngine:
    """The decision engine, with its opt-in ACCEPT paths read from the env.

    Both default OFF, so an unconfigured deployment keeps the fail-closed
    behaviour it had. ``REMORA_GROUNDED_READ_ACCEPT`` is the deterministic
    path: it is only meaningful once the deployment declares tool contracts,
    a state index and an intent source, and it accepts nothing without them.
    """
    import os as _env

    def _on(value: str) -> bool:
        # Takes the value, not the name: each variable is read below by its
        # literal name, so the credential topology scanner sees every read
        # without a line-pinned exception that moves with every edit.
        return value.strip().lower() in {"1", "true", "yes", "on"}

    return RemoraDecisionEngine(
        low_consequence_accept=_on(_env.environ.get("REMORA_LOW_CONSEQUENCE_ACCEPT", "")),
        grounded_read_accept=_on(_env.environ.get("REMORA_GROUNDED_READ_ACCEPT", "")),
        # ON by default on the enforcing surface, stricter only: no risk
        # signal and no higher production-write tier makes a call more
        # approvable (RMR-AUD-001/003; NEGATIVE_RESULTS §90). The library
        # default stays off so sealed replays reproduce. REMORA_STRICT_MONOTONE=0
        # restores the published decision table here.
        strict_monotone=_env.environ.get("REMORA_STRICT_MONOTONE", "1").strip().lower()
        not in {"0", "false", "no", "off"},
        # Issue #35: the enforcing surface runs the execution profile — a
        # probabilistic signal (conformal/temperature/evidence/ordered-trust)
        # can STRUCTURALLY never produce ACCEPT here, independent of what a
        # future adapter feeds the observation. Previously this depended on
        # the execution observation builder leaving those fields None.
        execution_profile=True,
    )


_ENGINE = _engine_from_env()
# Durable when REMORA_PG_DSN/REMORA_CHAIN_DB is configured (review finding:
# the previous process-local LRU forgot every key on restart, so a retried
# idempotency key re-ran assess and FORKED the proposal identity with a new
# chain record). In-process fallback keeps the bounded-LRU behavior.
import threading as _threading

from remora.persistence.idempotency import (
    IdempotencyClaim,
    IdempotencyConflict,
    IdempotencyStore,
    build_idempotency_store,
    idempotency_scope,
)

#: Guards every lazy singleton below. FastAPI runs sync endpoints in a
#: threadpool, so "if X is None: X = build()" is a real check-then-set race:
#: two concurrent first-requests each built an object and one of them was
#: discarded — taking any state written into it with it. A review item
#: enqueued into the losing ReviewQueue simply vanished.
_LAZY_INIT_LOCK = _threading.RLock()

_IDEMPOTENCY_STORE: IdempotencyStore | None = None


def _idempotency_store() -> IdempotencyStore:
    global _IDEMPOTENCY_STORE
    if _IDEMPOTENCY_STORE is None:
        with _LAZY_INIT_LOCK:
            if _IDEMPOTENCY_STORE is None:
                import os as _env
                _IDEMPOTENCY_STORE = build_idempotency_store(_env.environ)
    return _IDEMPOTENCY_STORE


def _reset_idempotency_store() -> None:
    """Test hook: drop the cached store (e.g. after env changes)."""
    global _IDEMPOTENCY_STORE
    _IDEMPOTENCY_STORE = None


def _idempotency_claim(tenant: str, principal: str, key: str,
                       req: Any) -> IdempotencyClaim:
    """Reserve ``key`` for this principal and request, or return its answer.

    Code review of 898758f, findings 3 and 4: the key is scoped to the
    authenticated principal and bound to the request's fingerprint, and it is
    reserved before anything is assessed, so one key yields one grant. A key
    that belongs to another request, or is still being answered after the
    wait, is a 409 and nothing is assessed.
    """
    scoped, fingerprint = idempotency_scope(
        principal, key, req.model_dump(mode="json", exclude={"idempotency_key"}))
    try:
        return _idempotency_store().claim(tenant, scoped, fingerprint)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=f"idempotency_key {exc.reason}") from exc

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


def _build_chain() -> Any:
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
    else "state_endpoint_partial"
    if _os.environ.get("REMORA_STATE_ENDPOINT", "").strip()
    else "in_process"
)
EXECUTION_STATE_DURABLE = EXECUTION_STATE_BACKEND in ("postgres", "sqlite")

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
    db_path=_os.environ.get("REMORA_CHAIN_DB", "").strip(),
    # The gate must know every backend the durability guard accepts. It knew
    # the first two and not this one, so the Cloudflare deployment passed the
    # guard while the jti ledger silently fell to the in-memory set — a
    # replay-after-restart window on ACCEPT execution tokens.
    state_endpoint=_os.environ.get("REMORA_STATE_ENDPOINT", "").strip(),
)
_QUEUES: dict[str, ReviewQueue] = {}
# item_id -> (tenant, ToolCallRequest fields) so execute() can rebuild hashes.
_ITEM_TENANT: dict[str, str] = {}


import contextvars as _contextvars
import dataclasses
import datetime as _dt

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
_ACTIVE_TX_CONNECTION: _contextvars.ContextVar[Any] = (
    _contextvars.ContextVar("remora_active_tx_connection", default=None)
)

# Phase 13 observability: the proposal identity this request is about, noted
# by the execution handlers and surfaced by the gateway middleware as the
# X-Remora-Proposal-Id response header — one stable id correlates ingress,
# policy, review, grant, dispatch, effect and evidence (FT-01 join key) on
# the transport layer too, without parsing bodies.
#
# The contextvar holds a MUTABLE holder dict, installed per request by the
# middleware, because sync endpoints run in a threadpool with a COPY of the
# context: a set() inside the handler never propagates back, but mutating
# the shared holder object does.
CURRENT_PROPOSAL_ID: _contextvars.ContextVar[dict[str, str | None] | None] = (
    _contextvars.ContextVar("remora_current_proposal_id", default=None)
)


def _note_proposal_id(proposal_id: Any) -> None:
    holder = CURRENT_PROPOSAL_ID.get()
    if holder is not None and proposal_id:
        holder["id"] = str(proposal_id)

# Built eagerly, like _CHAIN and _GATE: a durable adapter runs its DDL on
# its own connection, and doing that lazily inside an open transaction
# deadlocks against SQLite's BEGIN EXCLUSIVE write lock.
_OUTBOX: ExecutionOutbox | None = None


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
    if _os.environ.get("REMORA_STATE_ENDPOINT", "").strip():
        # The endpoint keeps the ledgers durable, not this. Production is
        # refused here as well as at startup, so an import-time build cannot
        # hand a production worker a process-local outbox.
        from remora.profiles import deployment_environment

        if deployment_environment() == "production":
            raise RuntimeError(
                "REMORA_STATE_ENDPOINT has no dispatch-outbox adapter; "
                "production requires REMORA_PG_DSN or REMORA_CHAIN_DB")
        _LOGGER.warning(UnbackedExecutionOutbox.reason)
        return UnbackedExecutionOutbox()
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



def chain_append_transactional(
    tenant: str, payload: dict[str, Any], *, key: str
) -> Any | None:
    """Append an audit event, joining the caller's state transaction when there is one.

    Inside ``db_transaction_state`` the event is enqueued on the SAME
    connection, so it commits or rolls back with the state transition it
    describes. Outside one there is nothing to be atomic with, and the event
    goes straight to the chain as before.

    This is REM-047: the two writes were each atomic and the pair was not, so a
    crash between them left a transition with no audit event and a verifier
    unable to tell that from a chain nobody wrote to. Returns the chain entry
    when appended directly, or None when enqueued for projection.
    """
    connection = _ACTIVE_TX_CONNECTION.get()
    if connection is None:
        return _CHAIN.append(tenant, payload)
    _audit_outbox.enqueue(connection, tenant=tenant, key=key, payload=payload)
    return None


def drain_audit_outbox(tenant: str | None = None) -> int:
    """Project any audit event whose transaction committed before it was written.

    Runs on the same lazy sweep as the stale-dispatch reconciler, for the same
    reason: a background daemon is not deployed, so recovery has to happen on
    the next interaction rather than on a timer. An idle tenant is never swept,
    which is a limitation and not a claim to the contrary.
    """
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    db_path = _os.environ.get("REMORA_CHAIN_DB", "").strip()
    if not (dsn or db_path):
        return 0
    try:
        if dsn:
            import psycopg  # type: ignore

            with psycopg.connect(dsn) as conn:
                return _audit_outbox.drain(conn, _CHAIN, tenant=tenant)
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            return _audit_outbox.drain(conn, _CHAIN, tenant=tenant)
    except Exception:
        # Recovery that raises would turn a durable, recoverable gap into a
        # failed request. The row stays pending and the next sweep retries.
        return 0


def reconcile_stale_dispatches(
    tenant: str, *, now: datetime | None = None
) -> list[Any]:
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
    # REM-047 recovery on the same sweep: an audit event whose transaction
    # committed before it reached the chain is projected here.
    drain_audit_outbox(tenant)
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
    # Crash-matrix row 5 (issue #416): finish the downstream projection of
    # terminal rows the settling process never completed. Idempotent, and a
    # background courtesy exactly like the sweep above.
    try:
        project_terminal_intents(tenant)
    except Exception:
        _LOGGER.exception("terminal projection failed for tenant %s", tenant)
    return settled


def project_terminal_intents(tenant: str) -> list[dict[str, Any]]:
    """Idempotently finish downstream projections for one tenant.

    Binds the module ambients around
    :func:`remora.execution.service.project_terminal_intent` (issue #416):
    every terminal outbox row without a confirmed projection gets its
    review-queue outcome and execution_result chain record replayed from
    the persisted projection payload, then is marked projected.
    """
    from remora.execution.service import project_terminal_intent

    results: list[dict[str, Any]] = []
    for row in _outbox().unprojected_terminal(tenant):
        result = project_terminal_intent(
            row, tenant=tenant, transaction=db_transaction_state,
            chain=_CHAIN, outbox=_outbox,
        )
        if result is not None:
            results.append(result)
    return results


# ── Signed ToolSpec (FT-03) ────────────────────────────────────────────────
#
# Opt-in by configuration, exactly as PR 1 decided: with
# REMORA_TOOLSPEC_BUNDLE set, the signed spec is the authority for
# arguments, target and callable identity, and its hash binds the whole
# chain. Without it the legacy registry path runs unchanged and the
# response RECORDS that enforcement is off — never silently equivalent,
# and never a trust-on-first-use upgrade that breaks a running deployment.

# ToolSpec authorization context (issue #241, extraction slice 3): bundle
# loading/verification and the assessed-record read-back live in
# remora/execution/authorization.py. These wrappers bind this module's
# ambient state (env, chain) and keep the HTTP conversion at the route layer.
from remora.execution.authorization import (
    assessed_record as _authz_assessed_record,
)
from remora.execution.authorization import (
    assessed_toolspec_for_proposal as _authz_assessed_toolspec_for_proposal,
)
from remora.execution.authorization import (
    load_toolspec_bundle as _authz_load_bundle,
)
from remora.execution.authorization import (
    reset_toolspec_bundle_cache,
)
from remora.execution.authorization import (
    resolve_toolspec as _authz_resolve_toolspec,
)
from remora.execution.authorization import (
    verified_registration as _authz_verified_registration,
)
from remora.execution.dispatch import (
    dispatch_under_lease as _dispatch_under_lease_impl,
)
from remora.execution.dispatch import (
    record_dispatch_intent as _record_dispatch_intent_impl,
)
from remora.execution.review_service import (
    ApprovalAuthority,
    ReviewConflict,
    ReviewNotFound,
    SeparationOfDutiesRefused,
)
from remora.execution.review_service import (
    approve_item as _approve_item,
)
from remora.execution.review_service import (
    reject_item as _reject_item,
)
from remora.execution.service import (
    ApprovalContextRefused,
    TokenRefused,
    ToolSpecChanged,
)
from remora.execution.service import (
    assess_proposal as _assess_proposal,
)
from remora.execution.service import (
    execute_approved_item as _execute_approved_item,
)
from remora.execution.service import (
    redeem_accept_token as _redeem_accept_token,
)

#: Re-exported under the name the tests reload this module for. An assignment
#: rather than an import alias, so the binding is a use of the imported name and
#: the re-export is visible to anything reading this module.
_reset_toolspec_bundle = reset_toolspec_bundle_cache


def _rebuild_tool_call(payload: dict[str, Any]) -> Any:
    """Rebuild the typed wire model from a persisted intent payload."""
    from servers.execution_contracts import ToolCallRequest

    return ToolCallRequest(**payload)


def dispatch_pending_intents(tenant: str, *, worker_id: str) -> list[dict[str, Any]]:
    """Worker entry point (issue #82): dispatch this tenant's pending intents.

    Binds the module's ambient state around
    :func:`remora.execution.service.dispatch_pending_intent`, exactly as
    the routes bind :func:`execute_approved_item`. Rows without a persisted
    payload (pre-#82 or synchronous-path rows) are skipped — the
    reconciler, not the worker, owns their fate.
    """
    from functools import partial

    from remora.execution.service import dispatch_pending_intent

    results: list[dict[str, Any]] = []
    for row in _outbox().pending(tenant):
        result = _with_flow_principal(_proposer_of_item(tenant, row.item_id), partial(
            dispatch_pending_intent,
            row,
            tenant=tenant,
            principal=f"worker:{worker_id}",
            transaction=db_transaction_state,
            chain=_CHAIN,
            gate=_GATE,
            outbox=_outbox,
            worker_id=worker_id,
            build_observation=_observation_with_context,
            dispatch_under_lease=_dispatch_under_lease,
            token_audience=PEP_AUDIENCE,
            token_ttl_seconds=EXECUTION_TOKEN_TTL_SECONDS,
            # The domain resolver, not the route wrapper: a spec refused at
            # dispatch settles the row under its reason code instead of
            # escaping the worker loop as an HTTP 409.
            resolve_toolspec=_resolve_toolspec_unwrapped,
            policy_coverage=_policy_coverage,
            policy_bundle_hash=_current_policy_bundle_hash,
            limits_policy_hash=_limits_policy_hash,
            rebuild_call=_rebuild_tool_call,
            assessed_record=_assessed_record,
            require_execution_context=context_required(),
            approval_policy=_approval_policy_for(tenant),
            ws1_gate=_ws1_gate(),
            ws1_capability=_ws1_capability(tenant),
            admission=_admission(),
        ))
        if result is not None:
            results.append(result)
    return results


def _toolspec_bundle() -> ToolSpecBundle | None:
    return _authz_load_bundle(_os.environ)


def _resolve_toolspec(
    tool_name: str, arguments: dict[str, Any], target_environment: str
) -> dict[str, Any]:
    """Enforce the signed spec for one call and return its identity.

    Every refusal is an HTTP 409 whose detail STARTS with the published
    reason code, so a consumer branches on the code rather than parsing
    prose (the domain refusal is raised by remora.execution.authorization).
    """
    try:
        return _authz_resolve_toolspec(
            _toolspec_bundle(), tool_name, arguments, target_environment
        )
    except ToolSpecRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason_code) from exc


def _resolve_toolspec_unwrapped(
    tool_name: str, arguments: dict[str, Any], target_environment: str
) -> dict[str, Any]:
    """:func:`_resolve_toolspec` for the worker: raises ``ToolSpecRefused``."""
    return _authz_resolve_toolspec(
        _toolspec_bundle(), tool_name, arguments, target_environment
    )


def _assessed_record(tenant: str, item_id: str) -> tuple[str, str]:
    return _authz_assessed_record(_CHAIN, tenant, item_id)


def _assessed_toolspec_for_proposal(tenant: str, proposal_id: str) -> str:
    """The ToolSpec hash recorded at assessment for a direct ACCEPT.

    The review path keys the same lookup on the review item; a direct ACCEPT
    never produces one, so the grant's canonical proposal identity is the key.
    Read back from the chain, never from the request, or the comparison would
    be against a value the caller chose.
    """
    return _authz_assessed_toolspec_for_proposal(_CHAIN, tenant, proposal_id)


def _record_dispatch_intent(
    *,
    proposal_id: str,
    tenant: str,
    item_id: str,
    tool_name: str,
    tool_call_hash: str,
    grant_jti: str,
    tool_call_json: str | None = None,
    authorization_expires_at: Any = None,
    requested_by: str | None = None,
) -> Any:
    """Record the dispatch intent (see remora.execution.dispatch); binds this
    module's outbox and the ambient transaction contextvar."""
    return _record_dispatch_intent_impl(
        _outbox(),
        _ACTIVE_TX_CONNECTION.get(),
        proposal_id=proposal_id,
        tenant=tenant,
        item_id=item_id,
        tool_name=tool_name,
        tool_call_hash=tool_call_hash,
        grant_jti=grant_jti,
        tool_call_json=tool_call_json,
        authorization_expires_at=authorization_expires_at,
        requested_by=requested_by,
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
    if request.method == "POST":
        # Issue #296: the per-tenant limiter guards BOTH surfaces' mutating
        # routes. Applied at the shared auth choke point rather than
        # per-route, so a new POST route cannot forget it; reads stay
        # unlimited.
        api_mod._enforce_execution_rate_limit(tenant)
    principal = api_mod._authenticated_principal(request)
    _FLOW_PRINCIPAL.set(principal)
    return tenant, role, principal


import hashlib
import json

# Review-state persistence (issue #241 extraction slice 2): the transaction
# adapter lives in remora/persistence/execution_state.py. to_dict/from_dict
# are re-imported so existing imports through this module keep working.
from remora.persistence.execution_state import (  # noqa: F401
    from_dict,
    to_dict,
)
from remora.persistence.execution_state import (
    transaction_state as _transaction_state,
)


def db_transaction_state(tenant: str) -> AbstractContextManager[Any]:
    """One all-or-nothing review-state transaction (see remora.persistence).

    Thin binding of this module's ambient state — queue, item→tenant mirror,
    the outbox's transaction contextvar and the durability env switches —
    onto the extracted adapter. Semantics unchanged and pinned by the
    fault-injection suite.
    """
    return _transaction_state(
        tenant,
        queue=_queue(tenant),
        item_tenant=_ITEM_TENANT,
        active_tx_connection=_ACTIVE_TX_CONNECTION,
        dsn=_os.environ.get("REMORA_PG_DSN", "").strip(),
        db_path=_os.environ.get("REMORA_CHAIN_DB", "").strip(),
    )


def _delegation_or_refuse(req: Any, tenant: str, principal: str) -> None:
    """Refuse a proposal naming a delegate this deployment has not declared.

    409 with the reason and nothing assessed. The declaration is read from
    the tenant's own ``tenant_access`` block of the risk-profile config; see
    remora/governance/delegation.py for why defaults never apply.
    """
    delegate = delegated_executor_of(req)
    if not delegate:
        return
    from servers import api as api_mod

    tenant_access = api_mod._RISK_PROFILE_CONFIG.get("tenant_access", {})
    reason = delegation_refusal(
        tenant_access if isinstance(tenant_access, dict) else {},
        tenant=tenant, proposer=principal, delegate=delegate)
    if reason is not None:
        raise HTTPException(status_code=409, detail=reason)


def _approval_requirement(tenant: str, risk_tier: Any) -> dict[str, Any]:
    """Who may approve an item at ``risk_tier`` in ``tenant``, as resolved now.

    The two inputs ``_enforce_review_approval_role`` decides with: the
    profile's ``approval_role`` and the tenant's ``reviewer_roles``. Read from
    the risk-profile config loaded at startup, so an edited file takes effect
    at the next restart, and an approval granted before it is compared with
    the requirement after it.
    """
    from servers import api as api_mod

    _, profile_cfg = api_mod._resolve_tenant_policy_profile(
        tenant, str(risk_tier) if risk_tier is not None else None)
    required = api_mod._extract_review_requirements(profile_cfg).get("approval_role")
    access = api_mod._tenant_access_policy(tenant)
    reviewer_roles = access.get("reviewer_roles", []) if isinstance(access, dict) else []
    return {
        "approval_role": str(required).strip().lower() if required else None,
        "reviewer_roles": sorted({str(r).strip().lower() for r in reviewer_roles
                                  if isinstance(r, str)}),
    }


def _approval_requirement_hash(requirement: dict[str, Any]) -> str:
    canonical = json.dumps(requirement, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _approval_policy_for(tenant: str) -> Any:
    """The hook the execution re-gate uses: observation -> requirement hash."""
    return lambda observation: _approval_requirement_hash(
        _approval_requirement(tenant, getattr(observation, "risk_tier", None)))


def _queue(tenant: str) -> ReviewQueue:
    queue = _QUEUES.get(tenant)
    if queue is None:
        with _LAZY_INIT_LOCK:
            queue = _QUEUES.get(tenant)
            if queue is None:
                queue = ReviewQueue(
                    engine=_ENGINE,
                    tenant_id=tenant,
                    revocation_store=_revocation_store(),
                )
                _QUEUES[tenant] = queue
    return queue


def _revocation_store() -> RevocationStore | None:
    """The durable revocation store when this deployment has one.

    Reads the same three switches as the durability guard in servers/api.py,
    and the strict runtime profile already requires one of them
    (``validate_runtime_profile_prerequisites``). It read only two of them
    until the D1 deployment was audited: that deployment is admitted on
    REMORA_STATE_ENDPOINT alone, so it passed the guard, kept the jti and
    lease-nonce ledgers durable, and silently held revoked principals in a
    per-process dict while the chain still recorded ``principal_revoked``.

    Returning None hands the queue its in-process default, which is correct
    for the research profile and is the configuration whose limitation is
    recorded in the store's module docstring: a revocation that reaches one
    worker and does not survive a restart.
    """
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    db_path = _os.environ.get("REMORA_CHAIN_DB", "").strip()
    endpoint = _os.environ.get("REMORA_STATE_ENDPOINT", "").strip()
    if not (dsn or db_path or endpoint):
        return None
    return DurableRevocationStore(
        dsn=dsn,
        db_path=db_path,
        state_endpoint=endpoint,
        # The re-gate reads this store from inside the review-state
        # transaction. A second connection to the same SQLite file would
        # block on the writer already holding it, so the store joins that
        # transaction when there is one and opens its own otherwise.
        connection_provider=_ACTIVE_TX_CONNECTION.get,
    )


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
_LOOP_SAFETY: LoopSafetyMonitor | None = None


def _loop_safety_monitor() -> LoopSafetyMonitor:
    """The loop safety monitor, over durable state when the deployment has it.

    The same three switches as ``_revocation_store`` and the durability guard,
    for the reason recorded there: a switch the guard admits and this store
    did not read would leave that deployment's loop history per-process.
    Without any of them the in-process store is used, which keeps a context's
    history for the life of this worker only (AST-012).
    """
    global _LOOP_SAFETY
    if _LOOP_SAFETY is None:
        with _LAZY_INIT_LOCK:
            if _LOOP_SAFETY is None:
                dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
                db_path = _os.environ.get("REMORA_CHAIN_DB", "").strip()
                endpoint = _os.environ.get("REMORA_STATE_ENDPOINT", "").strip()
                store = (
                    DurableLoopSafetyStore(dsn=dsn, db_path=db_path,
                                           state_endpoint=endpoint)
                    if (dsn or db_path or endpoint) else InMemoryLoopSafetyStore()
                )
                _LOOP_SAFETY = LoopSafetyMonitor(store)
    return _LOOP_SAFETY


_FLOW_CONTEXTS: Any = None


def _flow_control_enabled() -> bool:
    """``REMORA_FLOW_CONTROL=1`` turns on derived flow control (SDD v1.3)."""
    return _os.environ.get("REMORA_FLOW_CONTROL", "").strip() == "1"


_WS1_GATE: Any = None


def _ws1_gate() -> Any:
    """The WS1 gate (issue #953), or None when ``REMORA_WS1_MODE`` is unset or off.

    ``REMORA_WS1_MODE`` is ``off`` (default), ``shadow`` or ``enforce``; any
    other value, ``research`` included, is refused: research runs in the
    isolated runner, never behind this API. A mode other than off needs
    ``REMORA_WS1_DEPLOYMENT_MODULE``, a module exposing
    ``build_ws1_deployment()``. Enforce is refused unless flow control is on
    and the deployment names evidence for every prerequisite work package
    (``remora.verification.execution_gate.ENFORCE_DEPENDENCIES``).
    """
    global _WS1_GATE
    mode = _os.environ.get("REMORA_WS1_MODE", "").strip().lower() or "off"
    if mode == "off":
        return None
    if mode not in ("shadow", "enforce"):
        raise ValueError(f"REMORA_WS1_MODE={mode!r} is not one of off, shadow, enforce")
    if _WS1_GATE is None or _WS1_GATE.mode != mode:
        module = _deployment_module(_os.environ.get("REMORA_WS1_DEPLOYMENT_MODULE", ""))
        if module is None:
            raise ValueError(f"REMORA_WS1_MODE={mode} needs REMORA_WS1_DEPLOYMENT_MODULE")
        from remora.verification.execution_gate import Ws1Gate

        _WS1_GATE = Ws1Gate(mode, module.build_ws1_deployment(),
                            flow_control=_flow_control_enabled())
    return _WS1_GATE


#: The guard and the limit settings it was built from (_limit_settings).
_LIMIT_GUARD: tuple[tuple[str, str, str, bool, bool, str], Any] | None = None


def _tool_is_write(tool_name: str) -> bool | None:
    """Whether the deployment declares that ``tool_name`` writes; None when unknown.

    Read for the cumulative-limit coverage check. The signed ToolSpec answers
    when a bundle is configured; otherwise the deployment's semantic bundle
    (its contract's ``mutation``, else its signature's ``effect``). A tool
    neither declares is unknown, and coverage ``all_writes`` refuses it
    rather than assume it reads.
    """
    bundle = _toolspec_bundle()
    if bundle is not None:
        try:
            spec = bundle.get(tool_name)
        except ToolSpecRefused:
            return None
        return spec.action_type != "read" or bool(spec.semantic_contract.get("mutation"))
    semantic, _ = _semantic_bundle()
    if semantic is None:
        return None
    contract = semantic.contracts.get(tool_name)
    if contract is not None:
        return bool(contract.mutation) or contract.effect != "read"
    signature = semantic.registry.signatures.get(tool_name)
    if signature is None or signature.effect is None:
        return None
    return signature.effect != "read"


def _limit_guard() -> Any:
    """Cumulative limits, or None when ``REMORA_LIMITS_FILE`` is unset.

    The file is a JSON or YAML ``remora-cumulative-limits/v1`` policy
    (``remora/enforcement/cumulative_limits.py``); ``REMORA_LIMITS_LEDGER``
    names the SQLite file the reservations are kept in. One without the
    other, or a malformed policy, refuses at startup: a limit that silently
    does not apply would read as one that holds.
    """
    global _LIMIT_GUARD
    settings = _limit_settings()
    path, ledger, _keys, required, require_keys, _evidence = settings
    if not path and not ledger:
        if required:
            raise ValueError("REMORA_REQUIRE_LIMITS is set and no cumulative limits are "
                             "configured (REMORA_LIMITS_FILE, REMORA_LIMITS_LEDGER)")
        return None
    if not path or not ledger:
        raise ValueError("REMORA_LIMITS_FILE and REMORA_LIMITS_LEDGER are set together")
    if _LIMIT_GUARD is None or _LIMIT_GUARD[0] != settings:
        import yaml

        from remora.enforcement.cumulative_limits import (
            LimitGuard,
            LimitLedger,
            LimitPolicy,
        )

        # One read: the bytes digested are the bytes verified and enforced.
        with open(path, "rb") as handle:
            raw = handle.read()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        policy = LimitPolicy.from_dict(_verified_limit_policy(yaml.safe_load(raw), required))
        if required and policy.coverage != "all_writes":
            raise ValueError("REMORA_REQUIRE_LIMITS needs coverage all_writes: a write tool "
                             "the policy does not meter must not run")
        if require_keys:
            # Fail at startup for the tools the deployment can already name;
            # the guard refuses the rest call by call (limit_key_undeclared,
            # limit_coverage_unknown for a tool whose kind it cannot read).
            unkeyed = sorted(tool for tool in policy.meters
                             if tool not in policy.idempotency and _tool_is_write(tool))
            if unkeyed:
                raise ValueError("REMORA_REQUIRE_IDEMPOTENCY is set and these metered "
                                 "write tools declare no idempotency.key_arguments: "
                                 + ", ".join(unkeyed))
        _LIMIT_GUARD = (settings,
                        LimitGuard(policy, LimitLedger(ledger), is_write=_tool_is_write,
                                   observer=_limit_observer(),
                                   in_force=lambda: _limit_policy_in_force(settings, digest),
                                   evidence=_limit_evidence_checker(),
                                   require_keys=require_keys))
    return _LIMIT_GUARD[1]


_ON = frozenset({"1", "true", "yes", "on"})


def _limit_settings() -> tuple[str, str, str, bool, bool, str]:
    """What a limit guard is built from.

    (policy file, ledger, trusted keys, limits required, operation keys
    required, evidence module). A change to any of them after startup makes
    the guard refuse as ``limit_policy_changed``. Each key is read literally
    so the credential-topology scanner can resolve every environment read.
    """
    return (_os.environ.get("REMORA_LIMITS_FILE", "").strip(),
            _os.environ.get("REMORA_LIMITS_LEDGER", "").strip(),
            _os.environ.get("REMORA_LIMITS_TRUSTED_KEYS", "").strip(),
            _os.environ.get("REMORA_REQUIRE_LIMITS", "").strip().lower() in _ON,
            _os.environ.get("REMORA_REQUIRE_IDEMPOTENCY", "").strip().lower() in _ON,
            _os.environ.get("REMORA_LIMITS_EVIDENCE_MODULE", "").strip())


def _limit_policy_in_force(settings: tuple[str, str, str, bool, bool, str],
                           digest: str) -> bool:
    """Whether the guard built from ``settings`` and ``digest`` is still the deployed one.

    The policy identity a grant binds (``limits_policy_hash``) is the digest
    of the file at ``REMORA_LIMITS_FILE`` read now, so this reads it the same
    way. The dispatcher keeps the guard it was given; when the file or the
    settings have moved, that guard refuses every call instead of enforcing
    a policy no grant names.
    """
    from pathlib import Path

    from servers import api as api_mod

    return (_limit_settings() == settings
            and api_mod._sha256_file(Path(settings[0])) == digest)


def _verified_limit_policy(document: Any, required: bool) -> Any:
    """The limit policy to enforce, verified when a signer is trusted.

    ``REMORA_LIMITS_TRUSTED_KEYS`` lists the Ed25519 public keys (hex or
    base64, comma-separated) of the authority that sets the budgets. With
    them, the file must be a signed envelope by one of those keys. Without
    them, a signed envelope refuses (it cannot be checked) and a plain policy
    is accepted only when ``REMORA_REQUIRE_LIMITS`` is off.
    """
    from remora.crypto import SignatureDomain, VerificationKey
    from remora.enforcement.cumulative_limits import SIGNED_SCHEMA, verify_signed_policy

    raw_keys = [k for k in _os.environ.get("REMORA_LIMITS_TRUSTED_KEYS", "").split(",")
                if k.strip()]
    signed = isinstance(document, dict) and document.get("schema") == SIGNED_SCHEMA
    if not raw_keys:
        if required:
            raise ValueError("REMORA_REQUIRE_LIMITS needs REMORA_LIMITS_TRUSTED_KEYS: the "
                             "limits must be signed by the authority that sets them")
        if signed:
            raise ValueError("the limit policy is signed and REMORA_LIMITS_TRUSTED_KEYS is "
                             "unset, so its signature cannot be checked")
        return document
    keys = [VerificationKey.from_text(k, {SignatureDomain.LIMIT_POLICY}) for k in raw_keys]
    policy, _kid = verify_signed_policy(document, keys)
    return policy


def _cam_digest() -> str | None:
    """The digest of the Capability Activation Manifest this process loaded at
    startup (``servers.api.CAPABILITY_ACTIVATION``), or None without one."""
    from servers import api as api_mod

    report = getattr(api_mod, "CAPABILITY_ACTIVATION", None)
    return str(report.manifest_digest) if report is not None else None


def _limits_policy_hash() -> str | None:
    """The digest of the cumulative-limit policy in force, or None without one."""
    from servers import api as api_mod

    return api_mod._policy_component_hashes().get("limits_policy_hash")


def _limit_observer() -> Any:
    """The deployment's reader of actual equipment values, or None.

    ``REMORA_LIMITS_OBSERVER_MODULE`` names a module exposing
    ``observe_limit_value(tenant, quantity, resource)``, which returns the
    value the equipment reports now (a number) or raises. A policy with
    ``observed`` change meters and no observer refuses at startup.
    """
    spec = _os.environ.get("REMORA_LIMITS_OBSERVER_MODULE", "").strip()
    if not spec:
        return None
    import importlib

    observe = getattr(importlib.import_module(spec), "observe_limit_value", None)
    if not callable(observe):
        raise ValueError(f"{spec} does not expose observe_limit_value(tenant, quantity, "
                         "resource)")
    return observe


def _limit_evidence_checker() -> Any:
    """The deployment's reader of what the rail or plant says an operation did, or None.

    ``REMORA_LIMITS_EVIDENCE_MODULE`` names a module exposing
    ``check_limit_evidence(tenant, operation, evidence_ref)``, which asks the
    authoritative source named by ``evidence_ref`` and returns a mapping
    whose ``executed`` is True or False, or raises. Without one no unknown
    outcome can be resolved: ``POST /limits/resolve`` refuses as
    ``limit_evidence_unchecked`` and the budget stays held.
    """
    spec = _os.environ.get("REMORA_LIMITS_EVIDENCE_MODULE", "").strip()
    if not spec:
        return None
    import importlib

    check = getattr(importlib.import_module(spec), "check_limit_evidence", None)
    if not callable(check):
        raise ValueError(f"{spec} does not expose check_limit_evidence(tenant, operation, "
                         "evidence_ref)")
    return check


def _limits_or_refuse(req: Any, tenant: str, principal: str) -> None:
    """Refuse a call its cumulative limits cannot take.

    409 before anything is decided or queued, so no reviewer is asked to
    approve a call that could not run. Advisory only: the reservation at
    dispatch (``GovernedToolDispatcher.bind_limit_guard``) is what holds.
    """
    guard = _limit_guard()
    if guard is None or not guard.governs(req.tool_name):
        return
    refusal = guard.preview(tenant=tenant, principal=principal, tool_name=req.tool_name,
                            arguments=req.arguments)
    if refusal is None:
        return
    _CHAIN.append(tenant, {"event": "limit_refused", "actor": principal,
                           "tool_name": req.tool_name, "detail": refusal,
                           "stage": "assess"})
    raise HTTPException(status_code=409, detail=refusal)


_ADMISSION: Any = None
_ADMISSION_KEY: tuple[str, str, int] | None = None


def _admission() -> Any:
    """WS1-M4 atomic admission, or None when ``REMORA_WS1_ADMISSION`` is unset.

    ``REMORA_WS1_ADMISSION=atomic`` makes every dispatch path check the WS1
    receipts at the database instant and spend the grant in one tenant
    transaction with the intent: ``/execute-accepted`` records it there, and
    the synchronous review path and the async worker claim it there
    (``remora/execution/admission.py``). It needs Postgres (the reference
    backend) or SQLite (single host), and ``REMORA_MAX_CLOCK_SKEW_MS`` from 0
    to 5000, which has no default. D1 and in-process state are refused: neither
    has a transaction the steps could share
    (docs/architecture/ADR-ws1-m4-admission-topology.md, decision 5).
    """
    global _ADMISSION, _ADMISSION_KEY
    mode = _os.environ.get("REMORA_WS1_ADMISSION", "").strip().lower() or "legacy"
    if mode == "legacy":
        return None
    if mode != "atomic":
        raise ValueError(f"REMORA_WS1_ADMISSION={mode!r} is not one of legacy, atomic")
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    db_path = "" if dsn else _os.environ.get("REMORA_CHAIN_DB", "").strip()
    if _os.environ.get("REMORA_STATE_ENDPOINT", "").strip() or not (dsn or db_path):
        raise ValueError(
            "REMORA_WS1_ADMISSION=atomic needs REMORA_PG_DSN or REMORA_CHAIN_DB and no "
            "REMORA_STATE_ENDPOINT: D1 and in-process state have no shared transaction")
    raw = _os.environ.get("REMORA_MAX_CLOCK_SKEW_MS", "").strip()
    if not raw:
        raise ValueError("REMORA_WS1_ADMISSION=atomic needs REMORA_MAX_CLOCK_SKEW_MS; "
                         "it has no default")
    try:
        skew = int(raw)
    except ValueError as exc:
        raise ValueError(f"REMORA_MAX_CLOCK_SKEW_MS={raw!r} is not an integer") from exc
    key = (dsn, db_path, skew)
    if _ADMISSION is None or _ADMISSION_KEY != key:
        from remora.execution.admission import AtomicAdmission
        from remora.governance.authority_epochs import AuthorityEpochs

        _ADMISSION = AtomicAdmission(
            transaction=db_transaction_state, connection=_ACTIVE_TX_CONNECTION.get,
            epochs=AuthorityEpochs(dsn=dsn, db_path=db_path,
                                   connection_provider=_ACTIVE_TX_CONNECTION.get),
            dialect="postgres" if dsn else "sqlite", max_clock_skew_ms=skew,
            revocations=_revocation_store(), drain=drain_audit_outbox)
        _ADMISSION_KEY = key
    return _ADMISSION


def _ws1_capability(tenant: str) -> Any:
    """The capability block a WS1 binding covers, for a call and its proposer."""
    if _capability_resolver() is None:
        return None
    return lambda call, who: _capability_block(call, who, tenant)


def _flow_contexts() -> Any:
    """The flow context store, over the loop-safety store's durable backends.

    Same three switches as ``_loop_safety_monitor``, for the same reason: a
    switch the durability guard admits and this store ignored would keep a
    deployment's labels per-process (AST-016). The processing policy comes
    from ``REMORA_FLOW_PROCESSING_POLICY``, a JSON file
    ``{tenant: {data_class: [principal patterns]}}``. Without it nothing is
    authorized, so no context can be minted.
    """
    global _FLOW_CONTEXTS
    if _FLOW_CONTEXTS is None:
        with _LAZY_INIT_LOCK:
            if _FLOW_CONTEXTS is None:
                from remora.flow.context import (
                    DurableFlowEventStore,
                    FlowContextStore,
                    InMemoryFlowEventStore,
                    ProcessingPolicy,
                )

                dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
                db_path = _os.environ.get("REMORA_CHAIN_DB", "").strip()
                endpoint = _os.environ.get("REMORA_STATE_ENDPOINT", "").strip()
                store = (
                    DurableFlowEventStore(dsn=dsn, db_path=db_path, state_endpoint=endpoint)
                    if (dsn or db_path or endpoint) else InMemoryFlowEventStore()
                )
                policy_path = _os.environ.get("REMORA_FLOW_PROCESSING_POLICY", "").strip()
                policy = ProcessingPolicy()
                if policy_path:
                    with open(policy_path, encoding="utf-8") as fh:
                        policy = ProcessingPolicy.from_mapping(json.load(fh))
                _FLOW_CONTEXTS = FlowContextStore(store, policy)
    return _FLOW_CONTEXTS


_FLOW_HANDLES: Any = None

# The authenticated principal of the request being served, set by ``_auth``.
# Flow contexts belong to a principal, and the observation builders take only
# the tenant. Unset (a worker re-gate, a direct call) reads as no principal,
# which F2 refuses.
_FLOW_PRINCIPAL: _contextvars.ContextVar[str | None] = (
    _contextvars.ContextVar("remora_flow_principal", default=None)
)


def _proposer_of_item(tenant: str, item_id: str) -> str | None:
    """The actor of the proposal a review item belongs to, or None."""
    from remora.execution.service import _assessed_payload

    try:
        _toolspec_hash, proposal_id = _assessed_record(tenant, item_id)
        actor = (_assessed_payload(_CHAIN, tenant, proposal_id) or {}).get("actor")
    except Exception:
        return None
    return str(actor) if actor else None


def _with_flow_principal(principal: str | None, run: Callable[[], Any]) -> Any:
    """Run *run* with the flow principal set to *principal*.

    Flow contexts belong to the agent that proposed the call. On the review
    path the reviewer executes, and in the async worker nobody is
    authenticated, so the observation and the dispatch-time flow check read
    the proposer's context, not the executor's. Before this the context was
    unknown there and no flow check ran at dispatch.
    """
    token = _FLOW_PRINCIPAL.set(principal)
    try:
        return run()
    finally:
        _FLOW_PRINCIPAL.reset(token)


def _flow_handles() -> Any:
    """The handle store. Handles are minted when an executed call's result is
    labelled and committed (_flow_at_dispatch). The store is per-process: a
    restart or another worker does not know a handle, and a call that names
    one is refused as flow_handle_invalid (F2)."""
    global _FLOW_HANDLES
    if _FLOW_HANDLES is None:
        with _LAZY_INIT_LOCK:
            if _FLOW_HANDLES is None:
                from remora.flow.handles import HandleStore, InMemoryHandleBackend

                _FLOW_HANDLES = HandleStore(InMemoryHandleBackend())
    return _FLOW_HANDLES


def _with_flow(obs: PolicyObservation, req: ToolCallRequest, tenant: str) -> PolicyObservation:
    """Add the server-derived flow fields (IFC-05b) when flow control is on.

    The only writer of ``flow_*`` on the execution path; no request field can
    set one. Off, the observation is returned unchanged and the v5 decision
    stands.
    """
    if not _flow_control_enabled():
        return obs
    from remora.enforcement.custody import custody_is_enforced
    from remora.flow.observe import flow_observation

    fields = flow_observation(
        contexts=_flow_contexts(), handles=_flow_handles(), tenant=tenant,
        principal=_FLOW_PRINCIPAL.get(), context_id=req.context_id,
        flow=_flow_spec(req.tool_name), arguments=req.arguments,
        strict=custody_is_enforced())
    return dataclasses.replace(obs, **fields)


def _flow_spec(tool_name: str) -> Any:
    """The signed ToolSpec's ``flow`` block, or None (no bundle, no spec, no block).

    An unknown tool is refused by ``_resolve_toolspec`` on its own; here it
    only means no block, which the strict profile refuses (F3).
    """
    bundle = _toolspec_bundle()
    if bundle is None:
        return None
    try:
        return bundle.get(tool_name).flow
    except ToolSpecRefused:
        return None


_EFFECT_RESOLVER: Any = None


def _deployment_module(spec: str) -> Any:
    """The module a deployment names, or None when the setting is unset.

    Callers read the variable by its literal name, so the credential
    topology scanner can see every setting this process reads.
    """
    spec = spec.strip()
    if not spec:
        return None
    import importlib

    return importlib.import_module(spec)


def _effect_resolver() -> Any:
    """The deployment's closed effect registry (Q7.4), or None.

    ``REMORA_EFFECT_REGISTRY_MODULE`` names a module exposing
    ``build_resolver()``. Unset means no resolved-effect binding, which is
    the behaviour before Q7.4.
    """
    global _EFFECT_RESOLVER
    if _EFFECT_RESOLVER is None:
        module = _deployment_module(
            _os.environ.get("REMORA_EFFECT_REGISTRY_MODULE", ""))
        if module is None:
            return None
        _EFFECT_RESOLVER = module.build_resolver()
    return _EFFECT_RESOLVER


def _bind_premise_checks(dispatcher: GovernedToolDispatcher) -> None:
    """Bind the WS7 pre-dispatch checks a deployment configured. Each is
    opt-in; an unset variable leaves the dispatcher as it was.

    ``REMORA_EFFECT_REGISTRY_MODULE``   resolved-effect binding (Q7.4)
    ``REMORA_STATE_REVISION_MODULE``    ``read_revision(resource)`` for plans (Q7.5)
    ``REMORA_RECORDER_ADDRESS``         independent recorder host:port (Q7.6), with
    ``REMORA_RECORDER_MANDATORY_TOOLS`` comma-separated tools, or ``*`` for all
    ``REMORA_PROCEDURE_MODULE``         ``contract()`` and ``trace_for(lease)`` (Q7.7)
    """
    resolver = _effect_resolver()
    if resolver is not None:
        dispatcher.bind_effect_resolver(resolver)
    state_reader = _capability_state_reader()
    if state_reader is not None:
        dispatcher.bind_capability_state(state_reader)
    epoch_source = _capability_epoch_source()
    if epoch_source is not None:
        dispatcher.bind_capability_epochs(epoch_source)
    revisions = _deployment_module(
        _os.environ.get("REMORA_STATE_REVISION_MODULE", ""))
    if revisions is not None:
        dispatcher.bind_state_revisions(revisions.read_revision)
    address = _os.environ.get("REMORA_RECORDER_ADDRESS", "").strip()
    if address:
        from remora.audit.recorder import RecorderClient

        named = {t.strip() for t in _os.environ.get(
            "REMORA_RECORDER_MANDATORY_TOOLS", "").split(",") if t.strip()}
        dispatcher.bind_recorder(
            RecorderClient(address),
            mandatory_for=lambda tool: "*" in named or tool in named)
    procedure = _deployment_module(
        _os.environ.get("REMORA_PROCEDURE_MODULE", ""))
    if procedure is not None:
        dispatcher.bind_procedure(procedure.contract(), procedure.trace_for)


_CAPABILITY_RESOLVER: Any = None


def _capability_resolver() -> Any:
    """The deployment's capability resolver (Q8.2), or None when unset.

    ``REMORA_CAPABILITY_POLICY_FILE`` names a YAML or JSON capability policy
    (``CapabilityPolicy.from_dict``). Unset means no capability minimization,
    which is the behaviour before WS8.
    """
    global _CAPABILITY_RESOLVER
    path = _os.environ.get("REMORA_CAPABILITY_POLICY_FILE", "").strip()
    if not path:
        return None
    if _CAPABILITY_RESOLVER is None:
        import yaml

        from remora.capabilities import CapabilityPolicy, CapabilityResolver

        with open(path, encoding="utf-8") as handle:
            _CAPABILITY_RESOLVER = CapabilityResolver(
                CapabilityPolicy.from_dict(yaml.safe_load(handle)))
    return _CAPABILITY_RESOLVER


def _resolve_capability(tool_call: Any, principal: str, tenant: str,
                        now: _dt.datetime | None = None) -> Any:
    """A fresh capability set for this call, or None without a policy.

    Resolved from the deployment's policy for the AUTHENTICATED principal,
    never from anything in the request but the task type, which can only
    narrow (see ToolCallRequest.task_type).
    """
    resolver = _capability_resolver()
    if resolver is None:
        return None
    source = _capability_epoch_source()
    # Issued under the epochs in force now; a source that cannot answer is
    # raised to the caller, which refuses (capability_epoch_unverifiable).
    epochs = source.current(tenant, principal) if source is not None else None
    return resolver.resolve(
        epochs=epochs,
        principal_id=principal, tenant_id=tenant,
        environment=tool_call.target_environment or "",
        # A call that names no task type gets one the policy never names, so
        # it resolves to no tools: default deny, not an error.
        task_type=getattr(tool_call, "task_type", None) or "unspecified",
        now=now or _dt.datetime.now(_dt.UTC))


def _capability_epoch_source() -> Any:
    """The deployment's revocation epochs (Q8.6), or None.

    ``REMORA_CAPABILITY_EPOCH_MODULE`` names a module exposing
    ``current(tenant_id, principal_id) -> CapabilityEpochs`` and
    ``revoked(capability_set_id) -> bool``; the module itself is the source.
    """
    return _deployment_module(_os.environ.get("REMORA_CAPABILITY_EPOCH_MODULE", ""))


def _capability_state_reader() -> Any:
    """``read(source, arguments)`` from ``REMORA_CAPABILITY_STATE_MODULE`` (Q8.4),
    or None. Capability constraints read trusted state only through it."""
    module = _deployment_module(_os.environ.get("REMORA_CAPABILITY_STATE_MODULE", ""))
    return module.read if module is not None else None


def _capability_block(tool_call: Any, principal: str, tenant: str) -> dict[str, Any] | None:
    """What /assess records about the capability check (Q8.2)."""
    try:
        capability_set = _resolve_capability(tool_call, principal, tenant)
    except Exception:
        return {"allowed": False, "refusal": "capability_epoch_unverifiable",
                "requested_tool": tool_call.tool_name}
    if capability_set is None:
        return None
    refusal = capability_set.check(
        tool_call.tool_name, principal_id=principal, tenant_id=tenant,
        environment=tool_call.target_environment or "",
        now=_dt.datetime.now(_dt.UTC)) or capability_set.check_arguments(
        tool_call.tool_name, tool_call.arguments, _capability_state_reader())
    return {
        "capability_set_id": capability_set.capability_set_id,
        "capability_digest": capability_set.digest,
        "task_type": capability_set.task_type,
        "requested_tool": tool_call.tool_name,
        "allowed": refusal is None,
        "refusal": refusal.value if refusal is not None else None,
        "allowed_tools": list(capability_set.allowed_tools),
        "policy_version": capability_set.policy_version,
    }


def _capability_or_refuse(tool_call: Any, principal: str, tenant: str) -> None:
    """Refuse an execution whose tool is outside a fresh capability set,
    before anything is decided or consumed (409, reason in the detail)."""
    block = _capability_block(tool_call, principal, tenant)
    if block is not None and not block["allowed"]:
        raise HTTPException(status_code=409, detail=str(block["refusal"]))


def _stop_or_refuse(tenant: str) -> None:
    """Refuse while the operator has stopped execution for ``tenant``, before
    an approval or a token is spent (P0 item 7).

    The dispatcher refuses a stopped dispatch too, but by then ``/execute``
    has consumed the approval and ``/execute-accepted`` the token, so the
    work could not run after ``/resume``. Read here first: 409
    ``execution_stopped``, or 503 ``execution_stop_unverifiable`` when the
    store cannot answer. A stop set after this read is still refused by the
    dispatcher, with the approval spent; the window is one request.
    """
    try:
        stopped = _execution_stopped(tenant)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="execution_stop_unverifiable") from exc
    if stopped:
        raise HTTPException(status_code=409, detail="execution_stopped")


def _require_capability_set() -> bool:
    """Refuse any lease without a capability digest: when the BindingPolicy
    marks capability_set REQUIRED, or ``REMORA_REQUIRE_CAPABILITY_SET`` is set."""
    policy = _binding_policy()
    if policy is not None and policy.required("capability_set"):
        return True
    return _os.environ.get("REMORA_REQUIRE_CAPABILITY_SET", "").strip().lower() in {
        "1", "true", "yes", "on"}


#: Opt-in outside the strict profiles, where separation of duties is always on.
_ENV_REQUIRE_DISTINCT_APPROVER = "REMORA_REQUIRE_DISTINCT_APPROVER"


def _distinct_approver_required() -> bool:
    """Whether an approver must differ from the proposer (RMR-CR-004).

    Always under a strict profile; opt-in elsewhere, because a development
    deployment often has one principal doing everything on purpose.
    """
    from remora.profiles import STRICT_PROFILES, current_runtime_profile

    if current_runtime_profile() in STRICT_PROFILES:
        return True
    return _os.environ.get(_ENV_REQUIRE_DISTINCT_APPROVER, "").strip().lower() in {
        "1", "true", "yes", "on"}


_BINDING_POLICY_CACHE: tuple[str, Any] | None = None


def _binding_policy() -> Any:
    """The BindingPolicy named by REMORA_BINDING_POLICY, or None (CR-006, A2).

    Cached on the path. A policy that does not load raises: a deployment that
    named a policy has said what must be bound, and running without it would
    silently drop every requirement it states.
    """
    global _BINDING_POLICY_CACHE
    path = _os.environ.get("REMORA_BINDING_POLICY", "").strip()
    if not path:
        return None
    if _BINDING_POLICY_CACHE is None or _BINDING_POLICY_CACHE[0] != path:
        from remora.enforcement.binding_policy import load_binding_policy

        _BINDING_POLICY_CACHE = (path, load_binding_policy(path))
    return _BINDING_POLICY_CACHE[1]


def _require_task_identity() -> bool:
    """Whether this deployment refuses calls that name no task (Q7.2).

    On when the BindingPolicy marks task_identity REQUIRED, or when
    ``REMORA_REQUIRE_TASK_IDENTITY`` is set. Otherwise off, because a caller
    that does not yet send ``context_id`` and ``task_id`` would be refused on
    every call.
    """
    policy = _binding_policy()
    if policy is not None and policy.required("task_identity"):
        return True
    return _os.environ.get("REMORA_REQUIRE_TASK_IDENTITY", "").strip().lower() in {
        "1", "true", "yes", "on"}


def _presented_capability_set(raw: Any) -> Any:
    """The capability set sent with a leased dispatch; a set whose content no
    longer matches its own digest is a 409."""
    if raw is None:
        return None
    from remora.capabilities import EffectiveCapabilitySet

    try:
        return EffectiveCapabilitySet.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"capability set refused: {exc}") from exc


def _plan_or_refuse(tool_call: Any) -> Any:
    """The plan a call carries (Q7.5); a malformed one is a 422."""
    from remora.execution.service import plan_binding_of

    try:
        return plan_binding_of(tool_call)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"malformed plan: {exc}") from exc


def _task_or_refuse(tool_call: Any) -> TaskIdentity | None:
    """The task a call names; a 409 when the deployment requires one and it
    names none. Checked before anything is decided or consumed, so a refused
    call spends no grant and records no loop state."""
    task = TaskIdentity.from_fields({
        "context_id": getattr(tool_call, "context_id", None),
        "task_id": getattr(tool_call, "task_id", None),
    })
    if task is None and _require_task_identity():
        raise HTTPException(
            status_code=409,
            detail="task_identity_required: this deployment requires "
                   "context_id and task_id on every call")
    return task


def _policy_coverage() -> dict[str, Any]:
    """Per-component trust-base view for the execution surface.

    Read separately at admission and at closure so the two records can
    disagree; see remora.execution.service.execute_approved_item.
    """
    from servers import api as api_mod

    return api_mod.policy_coverage_block(surface=api_mod.SURFACE_EXECUTION)


def _current_policy_bundle_hash() -> str:
    from servers import api as api_mod

    return api_mod._policy_component_hashes().get("policy_hash") or ""


def _lease_nonce_store() -> NonceStore | None:
    """Durable lease-nonce consumption over whichever backend is configured.

    Deliberately reads the same three variables as the durability guard in
    servers/api.py, so the two cannot drift apart the way the jti ledger did.
    """
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    db_path = _os.environ.get("REMORA_CHAIN_DB", "").strip()
    endpoint = _os.environ.get("REMORA_STATE_ENDPOINT", "").strip()
    if not (dsn or db_path or endpoint):
        return None
    return DurableNonceStore(dsn=dsn, db_path=db_path, state_endpoint=endpoint)


_STOP_EPOCHS: Any = None
_STOP_EPOCHS_KEY: tuple[str, str] | None = None


def _stop_epochs() -> Any:
    """The authority-epoch store the stop switch lives in, or None without one.

    SDD unified capability execution v1.1, P0 item 7 (gate G10). Built from
    REMORA_PG_DSN or REMORA_CHAIN_DB, the two backends the store has, and
    bound to the open state transaction so the flag and its audit event
    commit together. The executing domain reads the same row from the same
    store its nonce ledger uses. D1 (REMORA_STATE_ENDPOINT) has no
    interactive transaction and no epoch store: a D1-only deployment has
    no stop, the routes answer 409, and the dispatcher binds nothing.
    """
    global _STOP_EPOCHS, _STOP_EPOCHS_KEY
    dsn = _os.environ.get("REMORA_PG_DSN", "").strip()
    db_path = "" if dsn else _os.environ.get("REMORA_CHAIN_DB", "").strip()
    if not (dsn or db_path):
        return None
    key = (dsn, db_path)
    if _STOP_EPOCHS is None or _STOP_EPOCHS_KEY != key:
        from remora.governance.authority_epochs import AuthorityEpochs

        _STOP_EPOCHS = AuthorityEpochs(dsn=dsn, db_path=db_path,
                                       connection_provider=_ACTIVE_TX_CONNECTION.get)
        _STOP_EPOCHS_KEY = key
    return _STOP_EPOCHS


def _execution_stopped(tenant: str) -> bool:
    """Whether the operator stopped execution for ``tenant``.

    Raises when the store cannot answer; the callers refuse on that, they
    do not guess. Without a durable store nothing can be stopped, and this
    says so by returning False only after _stop_epochs() said there is none.
    """
    from remora.governance.authority_epochs import EXECUTION_STOP_SUBJECT

    store = _stop_epochs()
    if store is None:
        return False
    return bool(store.read((EXECUTION_STOP_SUBJECT,),
                           tenant_id=tenant)[EXECUTION_STOP_SUBJECT][1])


def _tool_dispatcher() -> GovernedToolDispatcher | None:
    """App-lifecycle dispatcher; None when no policy bundle hash exists."""
    global _DISPATCHER
    if _DISPATCHER is None:
        with _LAZY_INIT_LOCK:
            if _DISPATCHER is None:
                bundle = _current_policy_bundle_hash()
                if not bundle:
                    return None
                # The lease nonce ledger must reach the same durable state
                # the jti ledger reaches. Built from the identical three
                # environment variables as _GATE above, for the identical
                # reason: a store the durability guard accepts and the
                # consumer never learns to use is how the jti ledger silently
                # fell back to memory (#350). Here the consequence is a lease
                # that is single-use only for the lifetime of a container --
                # and on Cloudflare containers are replaced on idle.
                #
                # None when nothing durable is configured, which leaves the
                # in-process NonceLedger and its honest docstring in place for
                # library and research use.
                dispatcher = GovernedToolDispatcher(
                    expected_policy_bundle_hash=bundle,
                    nonce_store=_lease_nonce_store(),
                    require_task_identity=_require_task_identity(),
                    require_capability_set=_require_capability_set(),
                    require_execution_context=context_required(),
                    execution_context_provider=context_provider(),
                )
                # RMR-004: the lease has always carried the signed spec
                # identity and verify() has always been able to check it.
                # Nothing supplied it, so the identity sat inside the
                # signature and was inert at the final PEP. This resolves the
                # spec THIS process would run, at the moment of dispatch, so a
                # bundle that moved between approval and execution refuses.
                dispatcher.bind_toolspec_identity(_toolspec_identity)
                # NTA-2: a mediated tool's downstream ceiling is the one its
                # signed ToolSpec declares, resolved in this process.
                dispatcher.bind_downstream_ceilings(_downstream_ceiling)
                # CR-006: the surface binding was inert on this path. The
                # observer reports the surface this dispatcher actually
                # offers; strict profiles enforce it (custody_is_enforced).
                from remora.enforcement.custody import custody_is_enforced

                dispatcher.bind_surface_observer(
                    lambda: _observed_surface(dispatcher),
                    require_digest=custody_is_enforced())
                # CR-006 (A2): what the deployment declared must be bound is
                # compared at dispatch, and a missing comparator refuses.
                policy = _binding_policy()
                if policy is not None:
                    # The effect resolver, when configured, is bound by
                    # _bind_premise_checks below; with resolved_effect
                    # REQUIRED and none configured, startup already refused.
                    dispatcher.bind_binding_policy(policy)
                    dispatcher.bind_effect_policy(_effect_policy_check)
                _bind_premise_checks(dispatcher)
                limits = _limit_guard()
                if limits is not None:
                    dispatcher.bind_limit_guard(limits)
                # SDD unified capability execution v1.1, P0 item 7: the
                # operator's stop switch, read before anything is spent.
                # Bound only with a durable authority store; without one
                # there is no stop, and the API reference says so. The
                # module function is looked up at each call, so a test
                # can make the store unreachable.
                if _stop_epochs() is not None:
                    dispatcher.bind_stop_source(lambda tenant: _execution_stopped(tenant))
                # ADR-UE-03 item 5: a lease is checked against the manifest
                # this process runs under. Bound always, so a lease minted
                # under a manifest refuses where none is loaded.
                dispatcher.bind_cam_digest(_cam_digest)
                spec = _os.environ.get("REMORA_TOOL_REGISTRY_MODULE", "").strip()
                if spec:
                    import importlib

                    registry = importlib.import_module(spec)
                    # Each callable is measured against its signed spec before
                    # it can execute (verified_registration); a mismatch refuses here.
                    registry.register_tools(
                        _authz_verified_registration(_toolspec_bundle(), dispatcher.register))
                    if policy is not None and policy.required("effect_mediation"):
                        # CR-005: a registration that breaks the signed effect
                        # policy refuses the dispatcher, not the first call.
                        broken = [
                            f"{name}: {refusal}"
                            for name in dispatcher.registered_tool_names()
                            if (refusal := _effect_policy_check(
                                name, dispatcher.is_mediated(name))) is not None]
                        if broken:
                            from remora.profiles import RuntimeProfileError

                            raise RuntimeProfileError(
                                "effect_mediation is REQUIRED and the registry breaks "
                                "the signed effect policy: " + "; ".join(broken))
                    if _os.environ.get("REMORA_EFFECT_ENDPOINT", "").strip():
                        # Three domains (NTA-2 phase 3): mediated effects go to
                        # the effect domain; this process holds no executor.
                        from remora.enforcement.effect_client import (
                            RemoteEffectClient,
                            http_post_from_env,
                        )

                        dispatcher.bind_effect_domain(
                            RemoteEffectClient(post=http_post_from_env()))
                    elif hasattr(registry, "register_effect_executors"):
                        # Optional: the primitives mediated effects run on,
                        # registered like tool callables because they close
                        # over the same kind of credential.
                        registry.register_effect_executors(
                            dispatcher.bind_effect_executors)
                _DISPATCHER = dispatcher
    return _DISPATCHER


def _local_dispatcher(presented_lease: Any) -> GovernedToolDispatcher | None:
    """The tool dispatcher, only when this process will execute the call.

    A lease minted here with an execution domain configured is forwarded, and
    ``dispatch_under_lease`` needs no dispatcher for that. Building one anyway
    imports the registry and registers its callables, which the custody guard
    refuses in the authority domain under a strict profile, so a strict
    authority could not forward at all. A presented lease always runs where
    it arrived.
    """
    from remora.execution.remote_dispatch import execution_endpoint

    if presented_lease is None and execution_endpoint():
        return None
    return _tool_dispatcher()


def _effect_policy_check(tool_name: str, mediated: bool) -> str | None:
    """The CR-005 effect-policy refusal for one registered tool, or None."""
    from remora.execution.effect_policy import effect_policy_refusal

    bundle = _authz_load_bundle(_os.environ)
    if bundle is None:
        return "effect_policy_unverifiable"
    try:
        spec = bundle.get(tool_name)
    except ToolSpecRefused:
        return "effect_mode_missing"
    return effect_policy_refusal(spec, mediated=mediated)


def _observed_surface(dispatcher: GovernedToolDispatcher) -> str:
    """The execution surface this dispatcher offers (CR-006).

    Raises when no bundle is configured: an observer that cannot see the
    signed surface has not observed an unchanged one, and the dispatcher
    turns the raise into ``surface_unobservable`` when enforcing.
    """
    from remora.execution.execution_surface import observed_surface_digest

    bundle = _authz_load_bundle(_os.environ)
    if bundle is None:
        raise LookupError("no signed ToolSpec bundle: the surface is unobservable")
    return observed_surface_digest(bundle, dispatcher.registered_tool_names())


def _toolspec_identity(tool_name: str) -> tuple[str, int] | None:
    """The signed spec identity this process would run for ``tool_name``.

    ``None`` means no bundle is configured -- the unenforced research path,
    which stays permitted and is reported as ``enforced=False`` everywhere
    else. It does NOT mean "the lookup failed": a bundle that is configured
    and cannot answer raises, and the dispatcher refuses on a raise. Collapsing
    the two would turn "I could not check" into "there was nothing to check".
    """
    bundle = _authz_load_bundle(_os.environ)
    if bundle is None:
        return None
    spec = bundle.get(tool_name)          # raises ToolSpecRefused if unknown
    return spec.toolspec_hash, int(spec.version)


_EFFECT_DOMAIN: Any = None
#: The raw JSON body of an effect request; the effect domain parses and
#: refuses it itself, so no request model sits in front of its own checks.
_EFFECT_BODY = Body(...)


def _effect_domain() -> Any:
    """This process's EffectDomain (NTA-2 phase 3), built once.

    Its effect executors come from the registry module's
    ``register_effect_executors``; whether a lease was dispatched is read from
    the durable nonce store the executor consumed it in. Without a durable
    store this process cannot tell, and every effect refuses as
    ``execution_state_unverifiable``: the executor's in-process ledger is in
    another process.
    """
    global _EFFECT_DOMAIN
    if _EFFECT_DOMAIN is None:
        from remora.enforcement.custody import assert_may_hold_effect_executors
        from remora.enforcement.effect_domain import EffectDomain

        executors: dict[str, Any] = {}

        def collect(mapping: Any) -> None:
            assert_may_hold_effect_executors()
            executors.update(mapping)

        spec = _os.environ.get("REMORA_TOOL_REGISTRY_MODULE", "").strip()
        if spec:
            import importlib

            registry = importlib.import_module(spec)
            if hasattr(registry, "register_effect_executors"):
                registry.register_effect_executors(collect)
        store = _lease_nonce_store()

        def started(lease: ExecutionLease) -> bool:
            if store is None or not hasattr(store, "consumed"):
                raise RuntimeError("no durable nonce store shared with the executor")
            return bool(store.consumed(lease.nonce, tenant_id=lease.tenant_id))

        _EFFECT_DOMAIN = EffectDomain(
            ceilings=_downstream_ceiling, executors=executors, execution_started=started,
            epochs=_capability_epoch_source(), ledger=store)
    return _EFFECT_DOMAIN


def _effect_request(payload: dict[str, Any], request: Request) -> Any:
    tenant, role, _ = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "execute")
    lease = payload.get("lease") if isinstance(payload, dict) else None
    if not isinstance(lease, dict) or lease.get("tenant_id") != tenant:
        raise HTTPException(status_code=409,
                            detail="effect refused: the lease is not for the authenticated tenant")
    return _effect_domain()


@router.post("/effects")
def serve_effect(request: Request, payload: dict[str, Any] = _EFFECT_BODY) -> dict[str, Any]:
    """One mediated effect, served by the effect domain (NTA-2 phase 3).

    The body carries the lease, the lease-bound capability set, the
    capability, the resource and the arguments. The effect domain verifies
    the lease, checks it was dispatched, derives the authority from its own
    ToolSpec ceiling and answers REFUSED or EXECUTED; it never raises for a
    refusal.
    """
    return dict(_effect_request(payload, request).serve(payload))


@router.post("/effects/close")
def close_effects(request: Request, payload: dict[str, Any] = _EFFECT_BODY) -> dict[str, Any]:
    """End a mediated execution in the effect domain."""
    return dict(_effect_request(payload, request).close(payload))


def _downstream_ceiling(tool_name: str) -> Any:
    """The signed ToolSpec's downstream ceiling for ``tool_name`` (NTA-2).

    ``None`` when no bundle is configured or the spec declares none; a
    mediated tool then runs with no effect authority at all. A configured
    bundle that cannot answer raises, and the dispatcher refuses on a raise.
    """
    bundle = _authz_load_bundle(_os.environ)
    if bundle is None:
        return None
    return bundle.get(tool_name).downstream_capabilities


def _reset_tool_dispatcher() -> None:
    """Test hook: drop the cached dispatcher (e.g. after env changes)."""
    global _DISPATCHER, _EFFECT_RESOLVER, _CAPABILITY_RESOLVER, _EFFECT_DOMAIN, _LIMIT_GUARD
    _DISPATCHER = None
    _LIMIT_GUARD = None
    _EFFECT_DOMAIN = None
    _EFFECT_RESOLVER = None
    _CAPABILITY_RESOLVER = None


# ── Semantic bundle (SHELF-020) ────────────────────────────────────────────
#
# With REMORA_SEMANTIC_BUNDLE_MODULE configured, the assess/execute
# observation is built by build_full_observation — the same authoritative
# context builder the benchmarks lock — over the deployment-declared
# contract bundle. The cache is keyed on the module spec so a test (or a
# redeployment) that unsets the variable falls back to the registry-only
# path instead of consulting a stale bundle.

_SEMANTIC: tuple[str, SemanticBundle | None, IntentResolver | None] | None = None


def _semantic_bundle() -> tuple[SemanticBundle | None, IntentResolver | None]:
    global _SEMANTIC
    spec = _os.environ.get("REMORA_SEMANTIC_BUNDLE_MODULE", "").strip()
    cached = _SEMANTIC
    if cached is None or cached[0] != spec:
        with _LAZY_INIT_LOCK:
            cached = _SEMANTIC
            if cached is None or cached[0] != spec:
                if not spec:
                    cached = (spec, None, None)
                else:
                    cached = (
                        spec, load_semantic_bundle(), load_intent_resolver()
                    )
                _SEMANTIC = cached
    assert cached is not None
    return cached[1], cached[2]


def _reset_semantic_bundle() -> None:
    """Test hook: drop the cached bundle (e.g. after env changes)."""
    global _SEMANTIC
    _SEMANTIC = None


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

#: Semantic context with no bundle configured: absent, never defaulted.
_NO_SEMANTIC_CONTEXT: dict[str, Any] = {
    "tool_contract_bundle_hash": "",
    "state_hash": "",
    "intent_authority_hash": "",
    "tool_matches_goal": None,
    "expected_effect_matches": None,
    "argument_values_grounded": None,
    "ungrounded_arguments": [],
    "argument_scope_valid": None,
    "scope_violating_arguments": [],
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
    # REMORA's own classification wins; a deployment may additionally
    # classify tools REMORA has never heard of (REMORA_TOOL_METADATA_FILE).
    # Neither → critical/unknown, the fail-closed floor, unchanged.
    registry_entry, tool_is_classified = resolve_tool_metadata(req.tool_name)
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
        return _with_flow(_registry_only_observation(req, tenant, registry_entry),
                          req, tenant), context

    target_environment = _effective_target_environment(
        registry_entry.get("target_environment"), req.target_environment
    )
    args_preview = json.dumps(
        req.arguments, sort_keys=True, separators=(",", ":"), default=str
    )[:120]
    obs = dataclasses.replace(
        full,
        question=full.question or f"{req.tool_name}({args_preview})",
        risk_tier=str(registry_entry.get("risk_tier", "critical")),
        action_type=(str(registry_entry.get("action_type"))
                     if tool_is_classified else full.action_type),
        # Server-resolved, never client-asserted: the hash is non-empty only
        # when THIS deployment's intent source recognised the intent_ref. An
        # intent_ref that was presented and did not resolve is False, which is
        # not the same as None (none presented) and must not read as one.
        intent_authority_present=(
            bool(context.get("intent_authority_hash"))
            if req.intent_ref else None),
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
    return _with_flow(obs, req, tenant), context


def semantic_call_context(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    tenant: str,
    intent_ref: str | None = None,
    untrusted_context: str | None = None,
    domain: str = "unknown",
    user_task: str = "",
    derivations: tuple[dict[str, Any], ...] = (),
) -> tuple[PolicyObservation | None, dict[str, Any]]:
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

    detailed_resolver = load_intent_resolution_provider()
    intent_resolution_status: str | None = None
    if intent_ref and detailed_resolver is not None:
        resolution = detailed_resolver(intent_ref)
        resolved = resolution.resolved
        intent_resolution_status = resolution.status
    elif intent_ref and resolver is not None:
        resolved = resolver(intent_ref)
        intent_resolution_status = (
            "resolved" if resolved is not None else "intent_not_authorized"
        )
    else:
        resolved = None
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
    scope_validator = load_argument_scope_validator()
    if scope_validator is not None:
        scope = scope_validator(tool_name, arguments, tenant)
        full = dataclasses.replace(
            full,
            argument_scope_valid=scope.valid,
            scope_violating_arguments=scope.violating_arguments,
        )
    from remora.enforcement.custody import custody_is_enforced

    full = dataclasses.replace(
        full,
        intent_resolution_status=intent_resolution_status,
        # Property D: under the strict profiles an intent that did not resolve
        # from a deployment-owned source cannot reach review. Research keeps
        # the permissive posture and says so.
        intent_provenance_required=custody_is_enforced(),
        intent_provenance_resolved=(intent_resolution_status == "resolved"),
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
        "argument_values_grounded": full.argument_values_grounded,
        "ungrounded_arguments": list(full.ungrounded_arguments),
        "argument_scope_valid": full.argument_scope_valid,
        "scope_violating_arguments": list(full.scope_violating_arguments),
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
        target_environment=_effective_target_environment(
            registry_entry.get("target_environment"), req.target_environment),
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


#: Environment names that mean "live", from the policy engine's canonical set.
#: Restated as a local frozenset only to avoid importing the private engine
#: constant across the server boundary; the test suite asserts they agree.
_PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production", "live"})


def _effective_target_environment(
    declared: str | None, requested: str | None
) -> str:
    """The riskier of the declared and requested environments.

    A pinned environment used to win outright, which made the pin a way to
    LOWER risk: a tool declared ``staging`` stayed staging even when the call
    said ``prod``, and a read pinned that way could reach the grounded ACCEPT
    path while actually touching live data. Now that deployments can write
    their own declarations, that pin would be a self-service trust upgrade.

    Same principle as ``_downgrade_only_bool``, in the direction that matters
    for an environment: a declaration may raise risk, never lower it. If
    either side says production, the call is production.

    Not symmetric with "declared wins" for non-production values: a tool
    declared ``staging`` and requested ``dev`` stays ``staging``, because the
    declaration is still the authority on where the tool actually operates —
    it just cannot deny a production claim.
    """
    declared_norm = (declared or "").strip().lower()
    requested_norm = (requested or "").strip().lower()
    if requested_norm in _PRODUCTION_ENVIRONMENTS:
        return requested_norm
    return declared_norm or requested_norm


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

    from servers import api as api_mod

    # The permission and request checks come before any stored answer: a
    # cached response is still an assess response (code review of 898758f,
    # finding 4).
    api_mod._require_tenant_capability(role, tenant, "assess")
    _task_or_refuse(req)
    _delegation_or_refuse(req, tenant, principal)
    _limits_or_refuse(req, tenant, principal)
    claim = None
    if req.idempotency_key:
        claim = _idempotency_claim(tenant, principal, req.idempotency_key, req)
        if claim.response is not None:
            return claim.response
    try:
        # FT-02 lazy sweep (same discipline as REM-032's TTL sweep): a dispatch
        # whose worker never reported back is settled as UNKNOWN before new
        # work is considered, so a stranded intent cannot linger unnoticed.
        reconcile_stale_dispatches(tenant)
        # Orchestration lives in remora.execution.service (issue #241, slice 7);
        # this route binds the module's ambient state and stays HTTP conversion.
        try:
            response = _assess_proposal_with_loop_state(
                tenant=tenant, principal=principal, req=req)
        except LoopSafetyStoreUnavailable as exc:
            # 503 and no decision. Assessing without the context's history
            # would read an outage as "nothing accumulated".
            raise HTTPException(
                status_code=503,
                detail="loop safety store unavailable; nothing was assessed "
                       "and this call must be retried") from exc
        except ExecutionContextRefused as exc:
            raise HTTPException(status_code=409, detail=exc.reason) from exc
    except BaseException:
        if claim is not None:
            _idempotency_store().release(claim)
        raise
    api_mod.record_execution_assess(response["decision"])

    if claim is not None and not _idempotency_store().complete(claim, response):
        # The reservation went stale and another request took the key over
        # while this one was still assessing. That request answers the key;
        # this answer, and the token in it, is withheld. The token exists
        # nowhere else (the chain records only its jti), so withholding it
        # leaves one usable grant per key instead of two.
        _CHAIN.append(tenant, {
            "event": "idempotency_reservation_lost",
            "proposal_id": response.get("proposal_id"),
            "actor": principal,
            "decision": response.get("decision"),
            "withheld_grant_jti": (response.get("execution_token") or {}).get("jti"),
        })
        raise HTTPException(
            status_code=409,
            detail="idempotency_key reservation_lost: another request took "
                   "this key over; retry to receive its answer")
    return response


def _toolspec_description(tool_name: str) -> str | None:
    """The signed ToolSpec's description, for the semantic shadow's state.

    Taken from the spec, never from the agent. ``None`` when no bundle is
    configured or the tool is not in it; the shadow then sends none.
    """
    bundle = _toolspec_bundle()
    if bundle is None:
        return None
    try:
        return bundle.get(tool_name).description
    except ToolSpecRefused:
        return None


# Off unless REMORA_SEMANTIC_SHADOW is set, and refused at startup when it is
# set without the rest of its configuration (servers/semantic_shadow.py).
from servers.semantic_shadow import (
    SemanticShadow,
    build_semantic_shadow_from_env,
)

# Refused at startup when REMORA_WS1_MODE is set without a usable deployment,
# and when REMORA_WS1_ADMISSION=atomic lacks a transactional backend or a skew.
_ws1_gate()
_admission()
_limit_guard()

_SEMANTIC_SHADOW = build_semantic_shadow_from_env(
    engine=_ENGINE, tool_description=_toolspec_description,
)


def _assess_proposal_with_loop_state(
    *, tenant: str, principal: str, req: ToolCallRequest,
) -> dict[str, Any]:
    return _assess_proposal(
        tenant=tenant, principal=principal, proposal=req,
        engine=_ENGINE, chain=_CHAIN,
        transaction=db_transaction_state, item_tenant=_ITEM_TENANT,
        build_observation=_observation_with_context,
        resolve_toolspec=_resolve_toolspec,
        lifecycle_guard=_lifecycle_guard,
        resolution_plan_for=_resolution_plan_for,
        note_proposal_id=_note_proposal_id,
        token_audience=PEP_AUDIENCE,
        token_ttl_seconds=EXECUTION_TOKEN_TTL_SECONDS,
        policy_bundle_hash=_current_policy_bundle_hash,
        limits_policy_hash=_limits_policy_hash,
        cam_digest=_cam_digest,
        loop_safety=_loop_safety_monitor(),
        capability_gate=(lambda proposal: _capability_block(proposal, principal, tenant))
        if _capability_resolver() is not None else None,
        semantic_shadow=_SEMANTIC_SHADOW,
        execution_context_provider=context_provider(),
        require_execution_context=context_required(),
        ws1_gate=_ws1_gate(),
    )


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

    def _authorize_approval(item: Any) -> ApprovalAuthority:
        # Profile-specific approval role (review-8 finding): a generic
        # reviewer must not approve what the tenant's risk profile reserves
        # for domain_expert/senior_authority. Raises the same HTTP errors it
        # always did — a route-layer policy injected into the service.
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
        # What admitted this approver, kept with the approval so execution
        # can tell whether that requirement is still the one in force.
        requirement = _approval_requirement(tenant, risk_tier)
        return ApprovalAuthority(
            approver_role=(role or "").strip().lower(),
            required_role=requirement["approval_role"],
            policy_hash=_approval_requirement_hash(requirement),
        )

    try:
        response = _approve_item(
            tenant=tenant, principal=principal, item_id=req.item_id,
            approval_ttl_seconds=req.approval_ttl_seconds,
            on_behalf_of=req.on_behalf_of,
            transaction=db_transaction_state, item_tenant=_ITEM_TENANT,
            chain=_CHAIN, authorize_approval=_authorize_approval,
            lifecycle_guard=_lifecycle_guard,
            note_proposal_id=_note_proposal_id,
            transactional_append=chain_append_transactional,
            require_execution_context=context_required(),
            require_distinct_approver=_distinct_approver_required(),
        )
    except ExecutionContextRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    except SeparationOfDutiesRefused as exc:
        raise HTTPException(status_code=403, detail=exc.reason) from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    api_mod.record_execution_approval()
    return response


@router.get("/capabilities", responses={
    200: {"description": "The tools this principal may see for the task, projected for an agent."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No capability policy is configured."},
})
def capability_projection(request: Request, task_type: str = "",
                          target_environment: str = "prod") -> dict[str, Any]:
    """The agent-facing tool list for one task (WS8 Q8.3).

    Resolved from the deployment's capability policy for the AUTHENTICATED
    principal and tenant, exactly as the execution routes resolve it, and
    projected as an OpenAI tool list. Everything outside the set is absent.
    The same set is enforced again on every call, so a client that ignores
    this list gains nothing.
    """
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "assess")
    call = SimpleNamespace(target_environment=target_environment, task_type=task_type or None)
    try:
        capability_set = _resolve_capability(call, principal, tenant)
    except Exception as exc:
        raise HTTPException(status_code=503,
                            detail="capability_epoch_unverifiable") from exc
    if capability_set is None:
        raise HTTPException(status_code=404, detail="no capability policy is configured")
    from remora.capabilities import CapabilityProjector

    bundle = _toolspec_bundle()
    specs: dict[str, dict[str, Any]] = {}
    for name, entry in TOOL_REGISTRY.items():
        schema: Any = None
        if bundle is not None:
            try:
                schema = dict(bundle.get(name).argument_schema)
            except Exception:
                schema = None
        specs[name] = {"description": f"{entry.get('action_type', '')} "
                                      f"({entry.get('risk_tier', '')} risk)".strip(),
                       "parameters": schema}
    projector = CapabilityProjector(capability_set)
    return {"capability_set": capability_set.to_dict(),
            "projection": projector.project(specs).to_dict(),
            "tools": projector.for_openai(specs)}


@router.get("/loop-safety/{context_id}", responses={
    200: {"description": "What this context has accumulated since its last reset."},
    **_AUTH_RESPONSES,
    503: {"model": ErrorDetail, "description": "Loop safety store unavailable."},
})
def loop_safety_state(context_id: str, request: Request) -> dict[str, Any]:
    """Read a context's loop safety state (Q7.2). Reviewer capability."""
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    try:
        verdict = _loop_safety_monitor().assess(tenant, context_id)
    except LoopSafetyStoreUnavailable as exc:
        raise HTTPException(status_code=503,
                            detail="loop safety store unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state = verdict.state
    return {
        "context_id": context_id,
        "action": verdict.action,
        "reached": list(verdict.reached),
        "counts": dict(state.counts),
        "tasks": list(state.tasks),
        "events_since_reset": state.events_since_reset,
    }


contexts_router = APIRouter(
    prefix="/v1/contexts",
    tags=["flow"],
    dependencies=[Depends(_enforce_execution_domain)],
)


@contexts_router.post("", response_model=ContextMintResponse, responses={
    200: {"description": "A fresh context; pass its context_id on every later call."},
    **_AUTH_RESPONSES,
    403: {"model": ErrorDetail, "description": "The user principal belongs to another tenant, or a processor may not read this tenant's data (processing_not_authorized)."},
    404: {"model": ErrorDetail, "description": "The parent context is unknown to this tenant and principal (flow_context_unknown)."},
    409: {"model": ErrorDetail, "description": "Flow control is not enabled in this deployment (flow_control_disabled)."},
    422: {"model": ErrorDetail, "description": "A principal is missing or not canonical."},
    503: {"model": ErrorDetail, "description": "Flow store unavailable (flow_state_unavailable)."},
})
def mint_context(req: ContextMintRequest, request: Request) -> ContextMintResponse:
    """Mint a flow context for the authenticated principal (SDD v1.3 §3.2, IFC-02).

    The id is minted here, never chosen by the caller, and the context starts
    at the bottom label (a child starts at its parent's label). Processors
    must be authorized for the tenant's data. The mint is recorded on the
    tenant chain. Requires the ``assess`` capability.
    """
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "assess")
    if not _flow_control_enabled():
        raise HTTPException(status_code=409, detail="flow_control_disabled")
    from remora.capabilities.resource import ResourceRefused, canonical_resource
    from remora.flow.context import (
        FlowContextUnknown,
        FlowStoreUnavailable,
        ProcessingNotAuthorized,
    )

    try:
        user = canonical_resource(req.user_principal)
    except ResourceRefused as exc:
        raise HTTPException(status_code=422, detail="user_principal is not canonical") from exc
    if not user.startswith(f"user://{tenant.lower()}/"):
        raise HTTPException(status_code=403, detail="principal_mismatch")
    try:
        state = _flow_contexts().mint(
            tenant, principal, user_principal=user, model_principal=req.model_principal,
            q_principal=req.q_principal, parent_context_id=req.parent_context_id)
    except ProcessingNotAuthorized as exc:
        raise HTTPException(status_code=403, detail="processing_not_authorized") from exc
    except FlowContextUnknown as exc:
        raise HTTPException(status_code=404, detail="flow_context_unknown") from exc
    except FlowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail="flow_state_unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _CHAIN.append(tenant, {
        "event": "flow_context_minted",
        "context_id": state.context_id,
        "parent_context_id": state.parent_context_id,
        "root_context_id": state.root_context_id,
        "principal": principal,
        "processors": sorted(state.processors),
    })
    return ContextMintResponse(context_id=state.context_id, label_epoch=state.epoch)


@router.post("/loop-safety/reset", responses={
    200: {"description": "Reset recorded; the context's count starts again."},
    **_AUTH_RESPONSES,
    503: {"model": ErrorDetail, "description": "Loop safety store unavailable."},
})
def loop_safety_reset(req: LoopSafetyResetRequest, request: Request) -> dict[str, Any]:
    """Reset a context's loop safety count under a named policy decision.

    Reviewer capability, as for revoking a principal: it is a human decision
    about authority. The store keeps the earlier events, and the reset is
    appended to the tenant chain with the reviewer, the policy reference and
    the reason. The agent whose history it is has no route to this.
    """
    tenant, role, reviewer = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    try:
        _loop_safety_monitor().reset(tenant, req.context_id,
                                     policy_ref=req.policy_ref, reason=req.reason)
    except LoopSafetyStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="loop safety store unavailable; the context was NOT reset",
        ) from exc
    _CHAIN.append(tenant, {
        "event": "loop_safety_reset",
        "context_id": req.context_id,
        "reset_by": reviewer,
        "policy_ref": req.policy_ref,
        "reason": req.reason,
    })
    return {"context_id": req.context_id, "reset_by": reviewer, "status": "reset"}


def _limits_or_404() -> Any:
    guard = _limit_guard()
    if guard is None:
        raise HTTPException(status_code=404, detail="no cumulative limits are configured")
    return guard


def _record_limit_resolutions(guard: Any, tenant: str) -> set[str]:
    """Project every resolved limit operation the chain does not carry yet.

    The ledger commits a resolution first (``audit_recorded=0``) and this
    sweep appends ``limit_operation_resolved`` afterwards, keyed by the
    operation through ``append_once`` so a crash after the append and before
    the mark cannot write the record twice. It runs on every limits route,
    like the stale-dispatch reconciler: a crash between the two steps leaves
    a resolution the next call records, never one that is lost. Returns the
    operation ids still unrecorded after the sweep (an unreachable chain).
    """
    left: set[str] = set()
    for op in guard.unrecorded_resolutions(tenant):
        payload = {
            "event": "limit_operation_resolved",
            "operation_id": op["operation_id"],
            "executed": str(op.get("resolution") or "").startswith("executed"),
            "resolved_by": op["resolved_by"],
            "evidence_ref": op.get("evidence_ref") or "",
            "evidence_checked_by": _limit_settings()[5],
            "reason": op.get("reason") or "",
            "resolved_at": op.get("resolved_at"),
        }
        try:
            if hasattr(_CHAIN, "append_once"):
                _CHAIN.append_once(tenant, f"limit_resolution:{op['operation_id']}", payload)
            else:  # pragma: no cover - every shipped chain has append_once
                _CHAIN.append(tenant, payload)
            guard.mark_recorded(op["operation_id"])
        except Exception as exc:
            # The ledger keeps the resolution and the gap stays visible; the
            # next limits call retries. Raising here would tell the reviewer
            # that a resolution the ledger already holds did not happen.
            _LOGGER.error("limits.resolution_unrecorded tenant_id=%s operation_id=%s "
                          "error_type=%s", tenant, op["operation_id"], type(exc).__name__)
            left.add(op["operation_id"])
    return left


@router.get("/limits/unresolved", responses={
    200: {"description": "Limit operations of this tenant whose outcome is unknown."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No cumulative limits are configured."},
})
def limits_unresolved(request: Request) -> dict[str, Any]:
    """The reservations held because a tool's outcome is unknown, oldest first.

    Each holds budget until a reviewer resolves it against the rail or plant
    (``POST /limits/resolve``). Reviewer capability, as for resolving.
    """
    tenant, role, _ = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    guard = _limits_or_404()
    _record_limit_resolutions(guard, tenant)
    return {"operations": guard.unresolved(tenant)}


@router.post("/limits/resolve", responses={
    200: {"description": "The operation is settled; a reservation was returned or kept."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No limits, or no such operation."},
    409: {"model": ErrorDetail,
          "description": "The operation's outcome is not unknown, the reviewer is the "
                         "principal it was charged to, or the evidence could not be "
                         "checked or disagrees with the reviewer."},
})
def limits_resolve(req: LimitResolveRequest, request: Request) -> dict[str, Any]:
    """Resolve an unknown outcome from what the rail or plant reports.

    A reviewer, never the principal the operation was charged to, states
    whether the call executed and names the evidence. Before anything
    changes, the deployment's evidence checker
    (``REMORA_LIMITS_EVIDENCE_MODULE``) asks the authoritative source about
    that evidence; the resolution is refused when no checker is configured
    (``limit_evidence_unchecked``), when it fails or cannot tell
    (``limit_evidence_unavailable``), and when it disagrees with the
    reviewer (``limit_evidence_disputed``). ``executed=false`` then returns
    the reservation, so a legitimate retry is no longer refused;
    ``executed=true`` keeps it and makes a duplicate refuse. The ledger
    records the decision first; it is then appended to the tenant chain as
    ``limit_operation_resolved`` with the reviewer, the evidence, the module
    that checked it and the reason. ``audit_recorded`` says whether that
    append succeeded; when it did not, the ledger keeps the resolution and
    the next limits call appends it (``recorded_late``).
    """
    tenant, role, reviewer = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    guard = _limits_or_404()
    refusal = guard.resolve(tenant=tenant, operation_id=req.operation_id,
                            executed=req.executed, resolved_by=reviewer,
                            reason=req.reason, evidence_ref=req.evidence_ref)
    if refusal == "limit_operation_not_found":
        raise HTTPException(status_code=404, detail=refusal)
    if refusal == "limit_ledger_unavailable":
        raise HTTPException(status_code=503, detail=refusal)
    if refusal is not None:
        raise HTTPException(status_code=409, detail=refusal)
    unrecorded = _record_limit_resolutions(guard, tenant)
    return {"operation_id": req.operation_id, "executed": req.executed,
            "resolved_by": reviewer, "status": "resolved",
            "audit_recorded": req.operation_id not in unrecorded}


@router.post("/revoke-principal", responses={
    200: {"description": "Revocation recorded; pending executions approved "
                         "by this principal will be refused at the re-gate."},
    **_AUTH_RESPONSES,
})
def revoke_principal(req: RevokePrincipalRequest, request: Request) -> dict[str, Any]:
    """Withdraw a principal's authority after the fact (property B).

    Same capability as approving, because it is the same authority acting in
    the other direction. The revoker is the authenticated principal, never
    the body. A principal may not revoke themself through this route: the
    chain would then show a self-cancelling authority with no second party.
    """
    tenant, role, revoker = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    if req.principal == revoker:
        raise HTTPException(status_code=409, detail="a principal cannot revoke themself")
    # REM-047: the revocation and the record of it commit together. This was
    # the plainest case of the defect — the revocation committed inside the
    # transaction and ``principal_revoked`` was appended after it, so a crash
    # in that window left a principal revoked with nothing saying who did it
    # or why. The reason is part of the key: a re-revocation carrying a
    # different reason is a different event, and an identical repeat is the
    # same one.
    revocation_key = _audit_outbox.encode_key(
        tenant, "principal_revoked", req.principal, revoker, req.reason or "")
    try:
        with db_transaction_state(tenant) as q:
            q.revoke_principal(req.principal, reason=req.reason or "")
            chain_append_transactional(tenant, {
                "event": "principal_revoked",
                "principal": req.principal,
                "revoked_by": revoker,
                "reason": req.reason or "",
            }, key=revocation_key)
    except RevocationStoreUnavailable as exc:
        # 503, not 500, and emphatically not a success body. A caller told
        # "revoked" by a route that could not record it would stop chasing a
        # revocation that never took effect.
        raise HTTPException(
            status_code=503,
            detail=(
                "revocation store unavailable; the principal was NOT revoked "
                "and this call must be retried"
            ),
        ) from exc
    return {"principal": req.principal, "revoked_by": revoker, "status": "revoked"}


@router.post("/stop", responses={
    200: {"description": "Execution for the tenant is stopped: the authority "
                         "mints nothing and every governed dispatch refuses "
                         "as execution_stopped, with its nonce unspent."},
    **_AUTH_RESPONSES,
    409: {"model": ErrorDetail,
          "description": "No durable authority state, so there is nothing "
                         "an executor could read."},
    503: {"model": ErrorDetail,
          "description": "The authority store did not answer; the flag did "
                         "NOT change."},
})
def stop_execution(req: ExecutionStopRequest, request: Request) -> dict[str, Any]:
    """The operator's stop switch (SDD unified capability execution v1.1, P0
    item 7; gate G10).

    Writes one durable flag for the tenant, the authority-epoch subject
    ``execution:stop``, in the store the lease nonce ledger uses, with an
    ``execution_stopped`` event in the same transaction. The governed
    dispatcher reads it before anything is spent, so a valid lease is
    refused with its nonce unspent and runs after ``/resume`` if it has not
    expired; the authority refuses to mint while stopped. Nothing that
    executed is touched and no evidence is deleted. A call past the nonce
    finishes: effects cannot be undone. Same capability as
    ``revoke-principal``.
    """
    return _set_execution_stop(req, request, stopped=True)


@router.post("/resume", responses={
    200: {"description": "Execution for the tenant resumes."},
    **_AUTH_RESPONSES,
    409: {"model": ErrorDetail, "description": "No durable authority state."},
    503: {"model": ErrorDetail,
          "description": "The authority store did not answer; the flag did "
                         "NOT change."},
})
def resume_execution(req: ExecutionStopRequest, request: Request) -> dict[str, Any]:
    """Lift the stop. Recorded as ``execution_resumed`` with the operator."""
    return _set_execution_stop(req, request, stopped=False)


@router.get("/stop", responses={
    200: {"description": "Whether execution for the tenant is stopped, and the "
                         "epoch of the last change."},
    **_AUTH_RESPONSES,
    409: {"model": ErrorDetail, "description": "No durable authority state."},
})
def execution_stop_status(request: Request) -> dict[str, Any]:
    """Read the stop switch. The read capability, like the audit reader."""
    from remora.governance.authority_epochs import EXECUTION_STOP_SUBJECT

    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    store = _stop_epochs()
    if store is None:
        raise HTTPException(status_code=409, detail=_NO_STOP_STORE)
    try:
        epoch, stopped = store.read((EXECUTION_STOP_SUBJECT,),
                                    tenant_id=tenant)[EXECUTION_STOP_SUBJECT]
    except Exception as exc:
        raise HTTPException(status_code=503,
                            detail="authority store unavailable") from exc
    return {"stopped": bool(stopped), "epoch": int(epoch)}


_NO_STOP_STORE = ("execution stop needs durable authority state (REMORA_PG_DSN or "
                  "REMORA_CHAIN_DB); nothing an executor could read exists here")


def _set_execution_stop(req: ExecutionStopRequest, request: Request, *,
                        stopped: bool) -> dict[str, Any]:
    from uuid import uuid4

    from remora.governance.authority_epochs import EXECUTION_STOP_SUBJECT

    tenant, role, operator = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    store = _stop_epochs()
    if store is None:
        raise HTTPException(status_code=409, detail=_NO_STOP_STORE)
    event = "execution_stopped" if stopped else "execution_resumed"
    # One key per change: every call moves the epoch, so no two are the same event.
    key = _audit_outbox.encode_key(
        tenant, event, EXECUTION_STOP_SUBJECT, operator, req.reason or "", uuid4().hex)
    try:
        with db_transaction_state(tenant):
            epoch = store.advance(EXECUTION_STOP_SUBJECT, tenant_id=tenant, revoked=stopped)
            chain_append_transactional(tenant, {
                "event": event, "epoch": epoch, "stopped_by": operator,
                "reason": req.reason or "",
            }, key=key)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="authority store unavailable; the stop flag did NOT change and "
                   "this call must be retried") from exc
    try:
        drain_audit_outbox(tenant)
    except Exception:
        # Committed and enqueued: the next drain projects the event.
        _LOGGER.warning("audit outbox drain after an execution stop change failed "
                        "for tenant %s", tenant, exc_info=True)
    return {"stopped": stopped, "epoch": epoch, "stopped_by": operator}


@router.post("/revoke-authority", responses={
    200: {"description": "The evidence source's authority epoch advanced; "
                         "receipts read before it no longer admit."},
    **_AUTH_RESPONSES,
    409: {"model": ErrorDetail,
          "description": "Atomic admission is not enabled, or the subject is "
                         "not an evidence source."},
})
def revoke_authority(req: RevokeAuthorityRequest, request: Request) -> dict[str, Any]:
    """Revoke or reinstate an evidence source for WS1-M4 admission.

    Advances the source's authority epoch under the tenant lock admission
    takes, with its audit event in the same transaction. Either way the epoch
    moves, so evidence read before the change no longer admits (INV-M4-02).
    Same capability as ``revoke-principal``. Only under
    ``REMORA_WS1_ADMISSION=atomic``: without it nothing reads the epoch, and
    answering "revoked" would claim an effect the deployment does not have.
    """
    tenant, role, revoker = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    admission = _admission()
    if admission is None:
        raise HTTPException(status_code=409,
                            detail="atomic admission is not enabled (REMORA_WS1_ADMISSION)")
    if not req.subject_key.startswith("source:") or not req.subject_key[7:].strip():
        raise HTTPException(status_code=409, detail="subject_key must name source:<id>")
    from uuid import uuid4

    event = "authority_revoked" if req.revoked else "authority_reinstated"
    # One key per change: every call moves the epoch, so no two are the same event.
    key = _audit_outbox.encode_key(
        tenant, event, req.subject_key, revoker, req.reason or "", uuid4().hex)

    def record(epoch: int) -> None:
        chain_append_transactional(tenant, {
            "event": event, "subject_key": req.subject_key, "epoch": epoch,
            "revoked_by": revoker, "reason": req.reason or "",
        }, key=key)

    try:
        epoch = admission.advance_authority(tenant, req.subject_key,
                                            revoked=req.revoked, record=record)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="authority store unavailable; the epoch did NOT advance and this "
                   "call must be retried") from exc
    return {"subject_key": req.subject_key, "epoch": epoch, "revoked": req.revoked,
            "revoked_by": revoker}


def _resolution_plan_for(
    *,
    action: DecisionAction,
    report: Any,
    tenant: str,
    item: Any,
) -> dict[str, Any] | None:
    """What would resolve this decision, in machine-readable form.

    Two kinds exist and are discriminated by ``type`` rather than merged:

    - ``machine_resolution`` — the engine produced a bounded lookup
      (``remora.policy.resolution.ResolutionPlan``); it is surfaced
      verbatim, not re-invented, so there is one vocabulary for it;
    - ``human_approval`` — a person holding a named role must act.

    ``None`` for ACCEPT (nothing to resolve) and for ABSTAIN, where no
    bounded step is known: promising a resolution that does not exist is
    the failure mode ABSTAIN exists to avoid.
    """
    from servers import api as api_mod

    engine_plan = getattr(report, "resolution_plan", None)
    if engine_plan is not None:
        return {
            "type": "machine_resolution",
            "resolver": engine_plan.resolver,
            "target_arguments": list(engine_plan.target_arguments),
            "source_tools": list(engine_plan.source_tools),
            "max_attempts": engine_plan.max_attempts,
            "reenter_router": engine_plan.reenter_router,
            "resubmit_required": False,
        }
    if action not in (DecisionAction.VERIFY, DecisionAction.ESCALATE):
        return None
    if item is None:
        return None

    risk_tier = getattr(item.observation, "risk_tier", None)
    _, profile_cfg = api_mod._resolve_tenant_policy_profile(
        tenant, str(risk_tier) if risk_tier is not None else None
    )
    requirements = api_mod._extract_review_requirements(profile_cfg)
    required_role = requirements.get("approval_role") or "reviewer"
    if action is DecisionAction.ESCALATE and required_role == "reviewer":
        # An escalation a normal reviewer may approve is not an escalation
        # (AAE §5). When the tenant profile does not name a higher role,
        # fall back to the security reviewer rather than silently letting
        # ESCALATE collapse into VERIFY.
        required_role = "security_reviewer"

    checks = ["confirm_intent_ref", "confirm_target", "confirm_argument_values"]
    reasons = [r.value for r in getattr(report, "reasons", [])]
    if reasons:
        checks.append("address_decision_reasons")
    return {
        "type": "human_approval",
        "requirements": checks,
        "decision_reasons": reasons,
        "required_role": required_role,
        "expires_at": item.queue_deadline.isoformat(),
        # The proposal already carries everything the reviewer needs; a
        # resubmission would mint a new proposal id and detach the review
        # from what was assessed.
        "resubmit_required": False,
    }


from remora.observability.otel import get_remora_tracer

_EXEC_TRACER = get_remora_tracer(service_name="remora-execution")


def _flow_at_dispatch(tenant: str, tool_call: ToolCallRequest, expected: tuple[int, str],
                      proposal_id: str,
                      ) -> tuple[str | None, Any, dict[str, Any] | None, Callable[[], None] | None,
                                 frozenset[str] | None]:
    """Re-check the flow decision right before dispatch, hold the context, and
    bind the result commit.

    SDD v2 WP-04 (AR-017, AR-018) and IFC-06. ``expected`` is the epoch and
    digest the flow check had when the call was decided. If the context's
    label moved since, or the check now differs, the call is refused before a
    lease is minted. The check then takes the dispatch fence: one ``dispatch``
    event on the context stream at the sequence the check saw. A context held
    by another proposal's unexpired dispatch, or a fence lost to a concurrent
    writer, refuses as ``flow_dispatch_contended`` before anything is spent;
    so two calls judged at the same epoch cannot both run, and a raise that
    lands while the holder runs still withholds the holder's result.

    The returned commit labels the raw result, persists the handles it mints,
    raises the context label, releases the fence and only then hands back the
    rendered result. A failed commit withholds the result. The third value is
    the call's arguments with every handle resolved to its value, which is
    what the tool receives; the fourth releases the fence, and the caller runs
    it on every path that does not commit, so a refusal or a raising tool
    does not hold the context until the fence expires (the lease TTL). The
    fifth is the recipient set the verdict approved (IFC-12).
    """
    import time as _time

    from remora.enforcement.lease import DEFAULT_LEASE_TTL_SECONDS
    from remora.flow.labeler import (
        FlowLabeler,
        commit_labeled_result,
        verify_flow_at_dispatch,
    )

    flow = _flow_spec(tool_call.tool_name)
    principal, context_id = _FLOW_PRINCIPAL.get(), tool_call.context_id
    if flow is None or not principal or not context_id:
        return "flow_state_unavailable", None, None, None, None
    contexts, handles = _flow_contexts(), _flow_handles()
    ok, reason, resolved = verify_flow_at_dispatch(
        contexts=contexts, handles=handles, tenant_id=tenant, principal=principal,
        context_id=context_id, flow=flow, arguments=tool_call.arguments,
        expected_epoch=expected[0], expected_digest=expected[1])
    if not ok:
        return reason, None, None, None, None
    # IFC-12: the recipients the clean verdict approved for this call, for
    # the lease (signed as a digest) and for the mediator, which admits a
    # network effect only on a host among them.
    from remora.flow.check import recipients as _recipients_of

    approved, _unresolved = _recipients_of(flow, resolved)
    now = _time.time()
    try:
        dispatch_id = contexts.begin_dispatch(
            tenant, principal, context_id, proposal_id=proposal_id,
            expires_at=now + DEFAULT_LEASE_TTL_SECONDS, now=now)
    except Exception:
        return "flow_state_unavailable", None, None, None, None
    if dispatch_id is None:
        return "flow_dispatch_contended", None, None, None, None
    released = False

    def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        try:
            contexts.end_dispatch(tenant, principal, context_id, dispatch_id)
        except Exception:
            # The hold expires with the lease TTL; until then the context
            # refuses other proposals, which is the fail-closed side.
            _LOGGER.warning("flow dispatch fence %s on context %s not released",
                            dispatch_id, context_id, exc_info=True)

    def commit(raw: Any) -> tuple[Any, dict[str, Any]]:
        try:
            done = commit_labeled_result(
                FlowLabeler(), flow, contexts=contexts, handles=handles, tenant_id=tenant,
                principal=principal, context_id=context_id, proposal_id=proposal_id,
                arguments=tool_call.arguments, raw_result=raw, expected_epoch=expected[0])
        finally:
            release()
        return done.rendered_result, {"raw_result_sha256": done.raw_result_sha256,
                                      "epoch": done.new_epoch,
                                      "minted_handles": len(done.minted_handle_ids)}

    return None, commit, resolved, release, approved


def _dispatch_under_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: ToolCallRequest,
    semantic: dict[str, Any],
    now: datetime,
    gate_allowed: bool = True,
    toolspec: dict[str, Any] | None = None,
    proposal_id: str = "",
    grant_jti: str = "",
    presented_lease: Any = None,
    task_identity: TaskIdentity | None = None,
    plan: Any = None,
    capability_set: Any = None,
    report_lease: bool = False,
    flow_expected: tuple[int, str] | None = None,
    not_after: datetime | None = None,
) -> dict[str, Any]:
    """Governed dispatch (see remora.execution.dispatch); binds this module's
    dispatcher and current policy bundle hash. Shared by /execute,
    /execute-accepted and /dispatch-leased so all three get identical
    enforcement -- which is why the custody-split path goes through here rather
    than calling the implementation directly.

    Wrapped in the GenAI governance span: until now the enforcing path
    emitted zero spans and tool_governance_span had no production caller
    (issue #45 gap 6). The span carries the proposal id as the tool-call id,
    so a trace joins the audit chain on the same key everything else uses.
    """
    if presented_lease is None:
        # P0 item 7: the authority mints nothing while the operator has
        # stopped execution; a presented lease is judged by the dispatcher.
        try:
            stopped = _execution_stopped(tenant)
        except Exception:
            return {"executed": False, "refusal_reason": "execution_stop_unverifiable",
                    "proposal_id": proposal_id}
        if stopped:
            return {"executed": False, "refusal_reason": "execution_stopped",
                    "proposal_id": proposal_id}
    if presented_lease is None:
        # Q8.2, the fresh check of SDD §15: resolved again at the moment the
        # lease is minted, and signed into it.
        # Resolved on the clock the dispatch is judged by. Resolving on a
        # later clock made issued_at fall after the dispatch time, and every
        # lease refused as capability_not_yet_valid.
        try:
            capability_set = _resolve_capability(tool_call, principal, tenant, now=now)
        except Exception:
            return {"executed": False, "refusal_reason": "capability_epoch_unverifiable",
                    "proposal_id": proposal_id}
        if capability_set is not None:
            refusal = capability_set.check(
                tool_call.tool_name, principal_id=principal, tenant_id=tenant,
                environment=tool_call.target_environment or "", now=now,
            ) or capability_set.check_arguments(
                tool_call.tool_name, tool_call.arguments, _capability_state_reader())
            if refusal is not None:
                return {"executed": False, "refusal_reason": refusal.value,
                        "proposal_id": proposal_id}
    result_commit = None
    resolved_arguments: dict[str, Any] | None = None
    release_fence: Callable[[], None] | None = None
    flow_recipients: frozenset[str] | None = None
    if flow_expected is not None:
        (flow_refusal, result_commit, resolved_arguments, release_fence,
         flow_recipients) = _flow_at_dispatch(tenant, tool_call, flow_expected, proposal_id)
        if flow_refusal is not None:
            return {"executed": False, "refusal_reason": flow_refusal,
                    "proposal_id": proposal_id}
    try:
        return _dispatch_under_lease_fenced(
            tenant=tenant, principal=principal, tool_call=tool_call, semantic=semantic, now=now,
            gate_allowed=gate_allowed, toolspec=toolspec, proposal_id=proposal_id,
            grant_jti=grant_jti, presented_lease=presented_lease, task_identity=task_identity,
            plan=plan, capability_set=capability_set, report_lease=report_lease,
            not_after=not_after, flow_expected=flow_expected, result_commit=result_commit,
            resolved_arguments=resolved_arguments, flow_recipients=flow_recipients)
    finally:
        if release_fence is not None:
            # The commit released it on the executed path; every other path
            # (a refusal below, a lease that could not be minted, a raising
            # tool) releases it here, so the context is not held until expiry.
            release_fence()


def _dispatch_under_lease_fenced(
    *,
    tenant: str,
    principal: str,
    tool_call: ToolCallRequest,
    semantic: dict[str, Any],
    now: datetime,
    gate_allowed: bool,
    toolspec: dict[str, Any] | None,
    proposal_id: str,
    grant_jti: str,
    presented_lease: Any,
    task_identity: TaskIdentity | None,
    plan: Any,
    capability_set: Any,
    report_lease: bool,
    not_after: datetime | None,
    flow_expected: tuple[int, str] | None,
    result_commit: Any,
    resolved_arguments: dict[str, Any] | None,
    flow_recipients: frozenset[str] | None = None,
) -> dict[str, Any]:
    """The rest of ``_dispatch_under_lease`` once the flow fence is held.

    Split out only so the fence is released in one ``finally`` around every
    path below; it is not a second entry point, and the mediation checker
    holds the route handlers to ``_dispatch_under_lease``.
    """
    flow_binding: tuple[int, str, str] | None = None
    if flow_expected is not None and presented_lease is None:
        # IFC-06: signed into the lease, so the executing domain compares
        # its live context and the arguments it is about to run against
        # what this authority judged, not against a value of its own.
        flow_binding = (flow_expected[0], flow_expected[1], canonical_tool_call_hash(
            name=tool_call.tool_name,
            arguments=(resolved_arguments if resolved_arguments is not None
                       else tool_call.arguments),
            tenant=tenant, target=tool_call.target_environment or ""))
    resolved_effect = None
    resolver = _effect_resolver() if presented_lease is None else None
    if resolver is not None:
        from remora.enforcement.resolved_effect import UnresolvedReference

        try:
            resolved_effect = resolver.resolve(
                tool_call.tool_name, tool_call.arguments,
                tool_call.target_environment or "")
        except UnresolvedReference:
            # Closed world: a reference the registry does not know is not
            # authorised by guessing what it probably meant.
            return {"executed": False, "refusal_reason": "unresolved_reference",
                    "proposal_id": proposal_id}
    # CR-006: the signed surface this lease is granted under. Empty without a
    # bundle, which leaves the unenforced research path as it was.
    surface = ""
    if presented_lease is None:
        bundle = _authz_load_bundle(_os.environ)
        if bundle is not None:
            from remora.execution.execution_surface import signed_surface_digest

            surface = signed_surface_digest(bundle)
    with _EXEC_TRACER.tool_governance_span(
        tool_call.tool_name,
        invocation_id=proposal_id or None,
        agent_id=principal or None,
        tenant_id=tenant,
    ) as _span:
        result = _dispatch_under_lease_impl(
            tenant=tenant,
            principal=principal,
            tool_call=tool_call,
            semantic=semantic,
            now=now,
            dispatcher=_local_dispatcher(presented_lease),
            policy_bundle_hash=_current_policy_bundle_hash(),
            gate_allowed=gate_allowed,
            toolspec=toolspec,
            proposal_id=proposal_id,
            grant_jti=grant_jti,
            presented_lease=presented_lease,
            task_identity=task_identity,
            resolved_effect=resolved_effect,
            plan=plan,
            surface_digest=surface,
            capability_set=capability_set,
            report_lease=report_lease,
            result_commit=result_commit,
            # The tool gets the values the flow check judged; the lease binds
            # the handle form the approver saw (IFC-06).
            invocation_arguments=(
                resolved_arguments if resolved_arguments not in (None, tool_call.arguments)
                else None),
            not_after=not_after,
            flow_binding=flow_binding,
            flow_recipients=flow_recipients,
            cam_digest=_cam_digest() or "",
        )
        _span.set_attribute("remora.executed", bool(result.get("executed")))
        if result.get("refusal_reason"):
            _span.set_attribute("remora.refusal_reason",
                                str(result["refusal_reason"]))
        return result


@router.post("/execute", response_model=None, responses={
    200: {"model": ExecutionExecuteResponse,
          "description": "Outcome of enforcement; refusal outcomes carry no "
                         "grant/pep/tool_execution keys."},
    202: {"model": ExecutionPendingResponse,
          "description": "REMORA_ASYNC_DISPATCH mode (issue #82): durable "
                         "authorization complete — queue EXECUTE outcome and "
                         "dispatch-intent row committed together; the "
                         "standalone worker performs the dispatch half. "
                         "Poll the proposal lifecycle for the outcome."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "Review item not found for this tenant."},
    409: {"model": ErrorDetail, "description": "Item not in an executable state, or "
                                               "execution is stopped (execution_stopped); "
                                               "a stopped item stays approved."},
    503: {"model": ErrorDetail, "description": "The stop flag could not be read "
                                               "(execution_stop_unverifiable); nothing "
                                               "was spent."},
})
def execute(req: ExecuteRequest, request: Request) -> dict[str, Any] | JSONResponse:
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
    _task_or_refuse(req.tool_call)
    _capability_or_refuse(req.tool_call, principal, tenant)
    _stop_or_refuse(tenant)
    reconcile_stale_dispatches(tenant)  # FT-02 lazy sweep (see assess)
    # Issue #82: async mode answers 202 after durable authorization; the
    # dispatch half belongs to the standalone worker
    # (scripts/run_dispatch_worker.py). Default stays synchronous.
    async_mode = _os.environ.get(
        "REMORA_ASYNC_DISPATCH", "").strip().lower() in {"1", "true", "yes", "on"}
    # Orchestration lives in remora.execution.service (issue #241, slice 8);
    # this route binds the module's ambient state and maps domain errors.
    try:
        response = _with_flow_principal(_proposer_of_item(tenant, req.item_id), lambda: _execute_approved_item(
            tenant=tenant, principal=principal, item_id=req.item_id,
            tool_call=req.tool_call,
            transaction=db_transaction_state, item_tenant=_ITEM_TENANT,
            chain=_CHAIN, gate=_GATE, outbox=_outbox,
            worker_id=f"api:{_os.getpid()}",
            build_observation=_observation_with_context,
            resolve_toolspec=_resolve_toolspec,
            assessed_record=_assessed_record,
            record_dispatch_intent=_record_dispatch_intent,
            dispatch_under_lease=_dispatch_under_lease,
            lifecycle_guard=_lifecycle_guard,
            note_proposal_id=_note_proposal_id,
            not_found=ReviewNotFound, conflict=ReviewConflict,
            token_audience=PEP_AUDIENCE,
            token_ttl_seconds=EXECUTION_TOKEN_TTL_SECONDS,
            policy_coverage=_policy_coverage,
            policy_bundle_hash=_current_policy_bundle_hash,
            limits_policy_hash=_limits_policy_hash,
            async_dispatch=async_mode,
            transactional_append=chain_append_transactional,
            require_execution_context=context_required(),
            approval_policy=_approval_policy_for(tenant),
            ws1_gate=_ws1_gate(),
            ws1_capability=_ws1_capability(tenant),
            admission=_admission(),
        ))
    except ExecutionContextRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except ToolSpecChanged as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except ApprovalContextRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    if response.get("dispatch") == "pending":
        api_mod.record_execution_execute(
            executed=False, refusal="dispatch_pending")
        return JSONResponse(status_code=202, content=response)
    tool_execution = response.get("tool_execution")
    if tool_execution is None:
        api_mod.record_execution_execute(
            executed=False, refusal=response["outcome"]
        )
    else:
        api_mod.record_execution_execute(
            executed=bool(tool_execution["executed"]),
            refusal=tool_execution.get("refusal_reason"),
        )
    return response


@router.post("/execute-accepted", responses={
    200: {"model": ExecutionExecuteResponse,
          "description": "Outcome of governed dispatch under an ACCEPT token."},
    **_AUTH_RESPONSES,
    409: {"model": ErrorDetail,
          "description": "Token refused: replayed/consumed, payload binding "
                         "mismatch, expired, wrong audience, or not an ACCEPT; "
                         "or execution is stopped (execution_stopped), with the "
                         "token unspent."},
    503: {"model": ErrorDetail,
          "description": "The stop flag could not be read "
                         "(execution_stop_unverifiable); the token is unspent."},
})
def execute_accepted(req: ExecuteAcceptedRequest, request: Request) -> dict[str, Any]:
    """Execute a directly-ACCEPTed proposal under its single-use token.

    The governed dispatch path for ACCEPT, closing the gap where an ACCEPT
    decision produced a token no endpoint could redeem. Every guarantee the
    review path enforces applies here too, in this order:

    1. the payload is re-hashed and must match the token's binding — a
       mutated call is a different act and is refused before anything runs;
    2. the grant is consumed exactly once, so a replayed token cannot
       dispatch twice;
    3. a dispatch intent is recorded before the side effect and settled
       after it (FT-02), so a crash leaves a durable record;
    4. dispatch goes through the same GovernedToolDispatcher under a lease
       bound to the current policy bundle — the caller never holds the
       credentials.

    What it deliberately does NOT do: re-run the decision engine. The token
    is a short-lived, exactly-bound authorization; re-deciding here would
    make the token meaningless and reintroduce the assess/execute drift the
    binding exists to prevent. Freshness is the token's TTL.
    """
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "execute")
    _task_or_refuse(req.tool_call)
    _capability_or_refuse(req.tool_call, principal, tenant)
    _stop_or_refuse(tenant)
    reconcile_stale_dispatches(tenant)

    try:
        token = PolicyDecisionToken.from_dict(req.execution_token)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409, detail=f"malformed execution token: {exc}"
        ) from exc

    # Flow contexts belong to the proposer. A delegate the proposal named
    # (and only that delegate) redeems in the proposer's context, as the
    # review path and the worker do; anyone else reads its own context and,
    # if it is not the proposer, is refused later as context_mismatch.
    from remora.execution.service import _acting_for, _assessed_payload

    flow_principal = _acting_for(
        _assessed_payload(_CHAIN, tenant, str(token.request_id or "")), principal) or principal

    # Orchestration lives in remora.execution.service (issue #241, slice 9);
    # this route binds the module's ambient state and maps domain errors.
    try:
        response = _with_flow_principal(flow_principal, lambda: _redeem_accept_token(
            tenant=tenant, principal=principal, token=token,
            tool_call=req.tool_call,
            chain=_CHAIN, gate=_GATE, outbox=_outbox,
            worker_id=f"api:{_os.getpid()}",
            build_observation=_observation_with_context,
            record_dispatch_intent=_record_dispatch_intent,
            dispatch_under_lease=_dispatch_under_lease,
            lifecycle_guard=_lifecycle_guard,
            note_proposal_id=_note_proposal_id,
            resolve_toolspec=_resolve_toolspec,
            assessed_toolspec=_assessed_toolspec_for_proposal,
            policy_bundle_hash=_current_policy_bundle_hash,
            require_execution_context=context_required(),
            ws1_gate=_ws1_gate(),
            ws1_capability=_ws1_capability(tenant),
            admission=_admission(),
        ))
    except ExecutionContextRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except ToolSpecChanged as exc:
        api_mod.record_execution_execute(executed=False, refusal=exc.reason)
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except TokenRefused as exc:
        api_mod.record_execution_execute(executed=False, refusal=exc.refusal)
        raise HTTPException(status_code=409, detail=exc.refusal) from exc
    tool_execution = response["tool_execution"]
    api_mod.record_execution_execute(
        executed=bool(tool_execution["executed"]),
        refusal=tool_execution.get("refusal_reason"),
    )
    return response


@router.post("/dispatch-leased", responses={
    200: {"model": ExecutionExecuteResponse,
          "description": "Outcome of governed dispatch under a presented lease."},
    **_AUTH_RESPONSES,
    409: {"model": ErrorDetail,
          "description": "The lease is malformed, does not verify against this "
                         "domain's public key, or does not bind this call."},
})
def dispatch_leased(req: DispatchLeasedRequest, request: Request) -> dict[str, Any]:
    """The execution domain's half of the custody split (ADR-A).

    This process holds the PUBLIC lease verification key and the downstream
    credentials. It cannot mint authority -- ``ExecutionLease.issue`` refuses
    when only verification material is present -- and it does not try to. It
    receives a lease from the authority domain and either dispatches exactly
    what that lease binds, or refuses.

    The verification is not a formality and not a signature check alone.
    ``GovernedToolDispatcher.dispatch`` re-derives the argument hash, compares
    every bound field against this concrete call, and consumes the nonce in
    durable tenant-scoped state before the tool runs. An authority-signed lease
    presented for a different call is refused here.
    """
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "execute")
    task = _task_or_refuse(req.tool_call)

    try:
        lease = ExecutionLease.from_dict(req.lease)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409, detail=f"malformed execution lease: {exc}"
        ) from exc

    # The tenant on the wire is advisory; the authenticated tenant governs.
    # A lease bound to another tenant is refused by verify_binding below, so
    # this only decides which tenant's chain records the attempt.
    if req.tenant_id and req.tenant_id != tenant:
        raise HTTPException(
            status_code=409,
            detail="lease dispatch refused: presented tenant does not match "
                   "the authenticated tenant")

    dispatcher = _tool_dispatcher()
    if dispatcher is None:
        raise HTTPException(
            status_code=503,
            detail="no tool dispatcher on this domain: the execution surface "
                   "needs a policy bundle and a tool registry")

    now = _dt.datetime.now(_dt.UTC)
    semantic = {"tool_contract_bundle_hash": lease.tool_contract_bundle_hash,
                "intent_authority_hash": lease.intent_authority_hash}
    if req.execution_context is not None:
        try:
            context = ExecutionContextV1.from_dict(req.execution_context)
        except ExecutionContextRefused as exc:
            raise HTTPException(status_code=409, detail=exc.reason) from exc
        semantic["execution_context_canonical"] = context.canonical_bytes().decode("utf-8")
    # Flow control in the execution domain (SDD v2 WP-04): with
    # REMORA_FLOW_CONTROL=1 this process reads the call's flow context from
    # its own store, as the lease's actor, and refuses unless the verdict is
    # clean. A domain that does not share the authority's durable flow store
    # sees an unknown context and refuses, which is the intended failure.
    flow_expected: tuple[int, str] | None = None
    if _flow_control_enabled():
        from remora.execution.service import _flow_refusal

        # The flow check below takes the context's dispatch fence, a write to
        # its event stream. A lease whose signature, decision or window does
        # not verify must not get that far: it is refused here with the
        # reason the dispatcher would give, and the stream is untouched.
        authentic = lease.verify_authenticity(now=now.isoformat())
        if not authentic.verified:
            api_mod.record_execution_execute(executed=False, refusal=authentic.reason)
            return {"outcome": "refused",
                    "tool_execution": {"executed": False,
                                       "refusal_reason": authentic.reason,
                                       "proposal_id": lease.proposal_id}}
        # IFC-06: the expected epoch and digest come from the SIGNED lease,
        # what the authority judged when it granted the call. Until this
        # change they were computed here, a moment before being compared
        # with themselves. A lease that carries no flow decision cannot be
        # checked against one and is refused while flow control is on.
        refusal = "flow_lease_unbound" if not lease.flow_digest else None
        if refusal is None:
            flow_obs = _with_flow_principal(lease.actor_identity, lambda: _with_flow(
                PolicyObservation(question="dispatch-leased"), req.tool_call, tenant))
            refusal = _flow_refusal(flow_obs)
        if refusal is not None:
            api_mod.record_execution_execute(executed=False, refusal=refusal)
            return {"outcome": "refused",
                    "tool_execution": {"executed": False, "refusal_reason": refusal,
                                       "proposal_id": lease.proposal_id}}
        flow_expected = (int(lease.flow_epoch), str(lease.flow_digest))
    tool_execution = _with_flow_principal(lease.actor_identity, lambda: _dispatch_under_lease(
        tenant=tenant,
        # From the SIGNED lease, never the request body and never the hop's
        # own principal. The body form let a caller with a stolen lease assert
        # the victim's identity; the hop principal is the authority, not the
        # end actor, so using it would refuse every legitimate call.
        principal=lease.actor_identity,
        tool_call=req.tool_call,
        semantic=semantic,
        now=now,
        proposal_id=lease.proposal_id,
        grant_jti=lease.grant_jti,
        presented_lease=lease,
        # From the call being executed, checked against the task the signed
        # lease was granted under: a lease from another task refuses.
        task_identity=task,
        # The plan the lease was signed over; its premises are re-read here.
        plan=_plan_or_refuse(req.tool_call),
        # The capability set the lease was minted under, checked against its
        # signed digest and against this call by the dispatcher.
        capability_set=_presented_capability_set(req.capability_set),
        flow_expected=flow_expected,
    ))
    api_mod.record_execution_execute(
        executed=bool(tool_execution["executed"]),
        refusal=tool_execution.get("refusal_reason"),
    )
    return {"outcome": "tool_execution" if tool_execution["executed"]
                       else "refused",
            "tool_execution": tool_execution}


@router.post("/reject", responses={
    200: {"description": "The refusal was recorded; the item is terminal."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "Review item not found for this tenant."},
    409: {"model": ErrorDetail, "description": "Item is not pending."},
})
def reject(req: RejectRequest, request: Request) -> dict[str, Any]:
    """Refuse a pending review item, terminally.

    The counterpart to :func:`approve`, and subject to the same identity
    rule: the recorded reviewer is the authenticated principal, never a
    value from the body. A rejected item can never be approved or executed
    afterwards — the queue refuses any later transition, so a refusal
    cannot be worked around by calling approve again.
    """
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "review")
    try:
        return _reject_item(
            tenant=tenant, principal=principal, item_id=req.item_id,
            reason=req.reason,
            transaction=db_transaction_state, item_tenant=_ITEM_TENANT,
            chain=_CHAIN, lifecycle_guard=_lifecycle_guard,
            note_proposal_id=_note_proposal_id,
            transactional_append=chain_append_transactional,
        )
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc


# Lifecycle/effect projections (issue #241, extraction slice 5): the derived
# read projections live in remora/execution/projections.py. Wrappers bind this
# module's chain and outbox; record_effect_verification keeps its public name
# (used by the SDK effect surface and tests).
from remora.execution.projections import (
    EFFECT_STATE as _EFFECT_STATE,  # noqa: F401  (name kept for tests)
)
from remora.execution.projections import (
    EffectVerificationReplay,
    is_claimed_verdict,
)
from remora.execution.projections import (
    current_state as _current_state_impl,
)
from remora.execution.projections import (
    dispatch_projection as _dispatch_projection_impl,
)
from remora.execution.projections import (
    effect_projection as _effect_projection,
)
from remora.execution.projections import (
    envelope_projection as _envelope_projection,
)
from remora.execution.projections import (
    proposal_events as _proposal_events_impl,
)
from remora.execution.projections import (
    record_effect_verification as _record_effect_verification_impl,
)


def _proposal_events(tenant: str, proposal_id: str) -> list[dict[str, Any]]:
    return _proposal_events_impl(_CHAIN, tenant, proposal_id)


def _dispatch_projection(tenant: str, proposal_id: str) -> dict[str, Any] | None:
    return _dispatch_projection_impl(_outbox(), tenant, proposal_id)


def _verifier_bindings() -> dict[str, set[str]]:
    """Which authenticated principal may claim which verifier identity.

    ``REMORA_EFFECT_VERIFIER_BINDINGS`` is a comma-separated list of
    ``principal=verifier_identity`` pairs.

    An allowlist of verifier NAMES was not enough, and this is the correction.
    The name arrived in the request body, so a submitter authorised to record
    receipts could simply type a permitted name -- the allowlist constrained
    which strings were acceptable, not who could send them. Binding the name to
    the authenticated principal is what makes ``verifier_identity`` mean
    "this party observed it" rather than "someone typed this".

    Unset means the verifier identity must EQUAL the authenticated principal:
    fail closed, and unspoofable without a second credential. That is stricter
    than the previous default, deliberately.
    """
    raw = _os.environ.get("REMORA_EFFECT_VERIFIER_BINDINGS", "").strip()
    out: dict[str, set[str]] = {}
    for pair in raw.split(","):
        principal, _, identity = pair.partition("=")
        if principal.strip() and identity.strip():
            out.setdefault(principal.strip(), set()).add(identity.strip())
    return out


def _assessed_tool_identity(events: list[dict[str, Any]]) -> tuple[str, str]:
    """``(tool_name, toolspec_hash)`` of the latest assessment in the chain."""
    for event in reversed(events):
        if event.get("event") == "assessed":
            payload = event.get("payload") or event
            return (str(payload.get("tool_name") or ""),
                    str(payload.get("toolspec_hash") or ""))
    return "", ""


def _authorised_verifier(principal: str, verifier_identity: str) -> bool:
    bindings = _verifier_bindings()
    if not bindings:
        return verifier_identity == principal
    return verifier_identity in bindings.get(principal, set())


def _effect_audit_is_durable() -> bool:
    """Whether effect evidence and its replay key share durable storage.

    ``REMORA_STATE_ENDPOINT`` currently makes the grant/nonce ledgers durable,
    but the tenant audit chain has no D1 adapter. Treating that endpoint as a
    durable effect-evidence store would recreate the exact split-write bug this
    receipt path is closing, only across a process restart. PostgreSQL and
    SQLite are the two backends where ``append_once`` commits the key and audit
    record in the same transaction.
    """
    return bool(
        _os.environ.get("REMORA_PG_DSN", "").strip()
        or _os.environ.get("REMORA_CHAIN_DB", "").strip()
    )


def record_effect_verification(tenant: str, verification: Any, *,
                               submitted_by: str = "",
                               dispatch_id: str = "",
                               settled_dispatch_id: str = "",
                               self_attested: bool = False) -> dict[str, Any]:
    """Append one effect verification to the tenant audit chain (see
    remora.execution.projections for the appending/never-editing contract)."""
    return _record_effect_verification_impl(
        _CHAIN, tenant, verification, submitted_by=submitted_by,
        dispatch_id=dispatch_id, settled_dispatch_id=settled_dispatch_id,
        self_attested=self_attested,
    )


def _effect_separation_required() -> bool:
    """Whether an effect verifier must be independent of the call (RMR-AUD-004).

    True in production and under the strict runtime profiles. There the
    verifier holds the ``verify_effect`` capability, its identity comes from
    ``REMORA_EFFECT_VERIFIER_BINDINGS``, and it is neither the proposer nor the
    executor of the call. A development deployment outside the strict profiles
    may still record a receipt from the executing principal, marked
    ``self_attested`` so it is never read as an independent observation.
    """
    from remora.profiles import (
        STRICT_PROFILES,
        current_runtime_profile,
        deployment_environment,
    )

    return (deployment_environment() == "production"
            or current_runtime_profile() in STRICT_PROFILES)


def _postcondition_spec_for(tool_id: str) -> Any:
    """The tool's signed ToolSpec when it declares a ``postcondition`` block.

    None when no bundle is loaded, the tool is not in it, or its spec has no
    postcondition: REMORA then has no contract to evaluate an effect against.
    """
    bundle = _toolspec_bundle()
    if bundle is None or tool_id not in bundle:
        return None
    spec = bundle.get(tool_id)
    return spec if spec is not None and spec.postcondition is not None else None


def _computed_postcondition_verdict(
        *, events: list[dict[str, Any]], lineage: Any, tenant: str,
        proposal_id: str, tool_id: str, toolspec_hash: str, spec: Any,
        arguments: dict[str, Any], observed: Any,
        verifier_identity: str, pre_state_revision: str = "",
        source_revision: str = "") -> Any:
    """The effect verdict REMORA computes itself (SDD L7, CAPR-07).

    The contract comes from the signed ToolSpec ``postcondition`` block and the
    approved arguments, accepted only when they hash to the dispatched call.
    Shared by the signed and the unsigned receipt paths, so neither can record
    a verdict the other would not compute.
    """
    if spec.toolspec_hash != toolspec_hash:
        raise HTTPException(
            status_code=409,
            detail=("effect receipt refused (toolspec_changed_since_assessment): "
                    "the dispatch was assessed under another spec"))

    # The arguments are the approved call's only if they hash to it.
    from remora.policy.observation import canonical_tool_call_hash

    target = next((str((e.get("payload") or e).get("target_environment") or "")
                   for e in events if e.get("event") == "assessed"), "")
    try:
        argument_hash = canonical_tool_call_hash(
            name=tool_id, arguments=arguments, tenant=tenant,
            target=target or None)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=(
            f"effect receipt refused (arguments_not_the_dispatched_call): {exc}")) from exc
    if argument_hash != lineage.tool_call_hash:
        raise HTTPException(
            status_code=409,
            detail=("effect receipt refused (arguments_not_the_dispatched_call): "
                    "the arguments do not hash to the dispatched call"))

    from remora.governance.effect_verification import (
        EffectStatus,
        PostconditionContract,
        verify_declared_delta,
    )
    from remora.toolcall.postcondition_spec import PostconditionSpecError

    try:
        contract: PostconditionContract = spec.postcondition.instantiate(
            tool_id=tool_id, reader=str(spec.postcondition_reader),
            arguments=arguments)
    except PostconditionSpecError as exc:
        raise HTTPException(status_code=409, detail=(
            f"effect receipt refused (postcondition_not_instantiable): {exc}")) from exc

    execution_id = lineage.execution_id or lineage.dispatch_id
    computed = verify_declared_delta(
        contract, observed, proposal_id=proposal_id,
        execution_id=execution_id, toolspec_hash=toolspec_hash,
        verifier_identity=verifier_identity)
    if (pre_state_revision and source_revision
            and pre_state_revision == source_revision
            and computed.status in (EffectStatus.VERIFIED, EffectStatus.MISMATCH)):
        # The object did not change across the dispatch, so whatever it holds
        # is not attributable to this call (NEGATIVE_RESULTS §85, narrowed
        # for systems that expose revisions).
        computed = dataclasses.replace(computed, status=EffectStatus.UNOBSERVABLE,
                           reason_code="postcondition_no_attributable_change",
                           detail=("pre-state and observed revisions are equal "
                                   f"({source_revision}); no change is "
                                   "attributable to this dispatch"))
    return computed


def _current_state(events: list[dict[str, Any]],
                   dispatch: dict[str, Any] | None) -> str:
    return _current_state_impl(events, dispatch)


@router.get("/proposals/{proposal_id}", responses={
    200: {"description": "The decision and where the proposal stands."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
})
def get_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    """One proposal's decision and current lifecycle state.

    Tenant-scoped by construction: the chain is read per tenant, so a
    proposal belonging to someone else is simply absent — a 404, never a
    redacted 200 that leaks its existence.
    """
    _note_proposal_id(proposal_id)
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    events = _proposal_events(tenant, proposal_id)
    if not events:
        raise HTTPException(status_code=404, detail="proposal not found")

    assessed: dict[str, Any] = next(
        (e["payload"] for e in events if e["event"] == "assessed"), {}
    )
    dispatch = _dispatch_projection(tenant, proposal_id)
    return {
        "proposal_id": proposal_id,
        "decision": assessed.get("decision"),
        "reasons": assessed.get("reasons", []),
        "tool_name": assessed.get("tool_name"),
        "tool_call_hash": assessed.get("tool_call_hash"),
        "actor": assessed.get("actor"),
        # Who may execute besides the actor, as admitted at assess. Shown so
        # a reviewer approves the delegation along with the call.
        "delegated_executor": assessed.get("delegated_executor"),
        "review_item_id": assessed.get("review_item_id"),
        "current_state": _current_state(events, dispatch),
        "event_count": len(events),
        "dispatch": dispatch,
        "effect": _effect_projection(events),
    }


@router.get("/proposals/{proposal_id}/semantic-assessment", responses={
    200: {"description": "Jev's advisory reading of the proposal, for the verifier or approver."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
})
def get_semantic_assessment(proposal_id: str, request: Request) -> dict[str, Any]:
    """The semantic shadow's reading of one proposal, for whoever resolves it.

    At VERIFY that is a bounded machine lookup, which the reading tells what
    to check; at ESCALATE it is the human approver. Advisory only: nothing on
    the approval, resolution or execution path reads it, and the response
    says so. ``status`` is ``available`` with the reading, ``failed`` when
    the provider could not answer, or the reason there is none:
    ``not_enabled``, ``pending``, ``tenant_not_opted_in``,
    ``request_not_resolved``, ``dropped`` or ``unknown``. Tenant-scoped like
    every proposal read: another tenant's proposal is a 404.
    """
    _note_proposal_id(proposal_id)
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    if not _proposal_events(tenant, proposal_id):
        raise HTTPException(status_code=404, detail="proposal not found")

    from remora.decision_providers.review import ADVISORY, reviewer_view

    shadow = _SEMANTIC_SHADOW
    if not isinstance(shadow, SemanticShadow):
        status, record = "not_enabled", None
    else:
        status, record = shadow.lookup(proposal_id, tenant)
    if record is not None:
        return reviewer_view(record)
    return {"proposal_id": proposal_id, "status": status, "authoritative": False,
            "advisory": ADVISORY}


@router.post("/proposals/{proposal_id}/effect", responses={
    200: {"description": "The verification was appended to the audit chain."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
})
def record_effect(proposal_id: str, req: EffectVerificationRequest,
                  request: Request) -> dict[str, Any]:
    """Append one effect verification to this proposal's trail.

    The verdict is recorded exactly as reported, including a mismatch. A
    product reporting one is reporting bad news about itself, and an
    overlay that softened those would be worse than not having one.

    What is refused is anything that would make the record unreadable
    later: an unknown proposal, another tenant's proposal (a 404, never a
    redacted 200 that leaks its existence), a status outside the published
    five, and a record that does not say who observed it.
    """
    _note_proposal_id(proposal_id)
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    separation = _effect_separation_required()
    # RMR-AUD-004: recording an effect is its own capability. It used to be
    # "execute", so the agent that ran a call could attest to its effect.
    # Outside production and the strict profiles "execute" is still accepted,
    # and the record is marked self-attested below when it is one.
    try:
        api_mod._require_tenant_capability(role, tenant, "verify_effect")
    except HTTPException:
        if separation:
            raise
        api_mod._require_tenant_capability(role, tenant, "execute")
    events = _proposal_events(tenant, proposal_id)
    if not events:
        raise HTTPException(status_code=404, detail="proposal not found")

    from remora.profiles import current_runtime_profile, deployment_environment

    if current_runtime_profile() == "controlled_pilot":
        # Owner decision 4 (CAPR-08): a pilot accepts only signed receipts,
        # whose verdict REMORA computes. An unsigned digest attestation names
        # its verifier by a string, which is not separation by trust domain.
        raise HTTPException(
            status_code=409,
            detail=("effect receipt refused (unsigned_receipt_refused): the "
                    "controlled_pilot profile records only signed receipts; "
                    "submit to /proposals/{id}/effect-receipt"))

    if deployment_environment() == "production" and not _effect_audit_is_durable():
        raise HTTPException(
            status_code=503,
            detail=("effect receipt audit store unavailable: production "
                    "requires REMORA_PG_DSN or REMORA_CHAIN_DB so receipt "
                    "uniqueness and its audit evidence commit together; "
                    "REMORA_STATE_ENDPOINT does not yet store the tenant "
                    "audit chain"),
        )
    if separation and not _verifier_bindings():
        # Unset bindings mean "the verifier is whoever submits", which in a
        # deployment where the agent holds the receipt credential is the agent.
        raise HTTPException(
            status_code=503,
            detail=("effect receipt refused (effect_verifier_bindings_required): "
                    "production and the strict profiles require "
                    "REMORA_EFFECT_VERIFIER_BINDINGS to name which principal "
                    "observes effects under which verifier identity"),
        )

    # NOT defaulted to the server clock: substituting our time for a missing
    # observation time fabricates the freshness the check depends on. A
    # settled verdict without one is refused below.
    verified_at = req.verified_at

    # The verifier identity is bound to the authenticated principal, so it
    # names who observed rather than what the submitter typed.
    if not _authorised_verifier(principal, req.verifier_identity):
        raise HTTPException(
            status_code=403,
            detail=(f"effect receipt refused (verifier_not_bound): "
                    f"{principal!r} may not submit receipts as "
                    f"{req.verifier_identity!r}"))

    # SDD L7: EFFECT_VERIFIED is a verdict REMORA computes, never a status it
    # records. When the tool's signed ToolSpec declares a postcondition, the
    # receipt must carry the observed object, and the status recorded is the
    # one REMORA computes from it, exactly as on the signed path. Without a
    # postcondition there is nothing to compute, so a reported VERIFIED is
    # kept as a claim: it shows as EFFECT_CLAIMED and settles nothing.
    # Reported bad news (MISMATCH, UNOBSERVABLE, ...) cannot raise the state
    # and is recorded as reported, as before.
    from remora.governance.effect_receipt import resolve_lineage
    from remora.governance.effect_verification import EffectStatus

    tool_id, toolspec_hash = _assessed_tool_identity(events)
    spec = _postcondition_spec_for(tool_id)
    computed: Any = None
    claim_only = False
    if spec is not None and req.observed is not None:
        if req.arguments is None:
            raise HTTPException(
                status_code=409,
                detail=("effect receipt refused (arguments_required): an "
                        "observation is evaluated against the approved call, "
                        "so the call's arguments must come with it"))
        try:
            computed_lineage = resolve_lineage(events)
        except ReceiptRefused as exc:
            raise _receipt_refused(exc) from exc
        computed = _computed_postcondition_verdict(
            events=events, lineage=computed_lineage, tenant=tenant,
            proposal_id=proposal_id, tool_id=tool_id,
            toolspec_hash=toolspec_hash, spec=spec, arguments=req.arguments,
            observed=req.observed, verifier_identity=req.verifier_identity,
            pre_state_revision=req.pre_state_revision,
            source_revision=req.source_revision)
    elif spec is not None and req.status is EffectStatus.VERIFIED:
        raise HTTPException(
            status_code=409,
            detail=(f"effect receipt refused (postcondition_observation_required): "
                    f"{tool_id!r} declares a signed postcondition, so REMORA "
                    "computes EFFECT_VERIFIED from the observed object; submit "
                    "observed and arguments, or a signed receipt"))
    elif spec is None and req.status is EffectStatus.VERIFIED:
        claim_only = True

    # A settled verdict is accepted only when bound to a real dispatch.
    # Everything the receipt is checked against is read from the audit chain;
    # nothing here trusts the request about which dispatch it describes.
    try:
        lineage, status = verify_effect_receipt(
            events=events,
            proposal_id=proposal_id,
            claimed_status=computed.status if computed is not None else req.status,
            tool_call_hash=req.tool_call_hash,
            grant_jti=req.grant_jti,
            expected_sha256=(computed.expected_sha256 if computed is not None
                             else req.expected_sha256),
            observed_sha256=(computed.observed_sha256 if computed is not None
                             else req.observed_sha256),
            verified_at=verified_at,
            verifier_identity=req.verifier_identity,
            # Bound to the authenticated principal just above, so it is the
            # one identity trusted for this receipt. An empty allowlist would
            # trust nobody.
            trusted_verifiers=(req.verifier_identity,),
            reason_code=(computed.reason_code if computed is not None
                         else req.reason_code),
            # A claim settles nothing, so it cannot make a later verdict a
            # replay.
            already_recorded=[
                e.get("payload", {}) for e in events
                if e.get("event") == "effect_verified"
                and not is_claimed_verdict(e.get("payload", {}))
            ],
        )
    except ReceiptRefused as exc:
        # 409, not 400: the receipt is well-formed and the conflict is with
        # the recorded history, which is what the caller needs told.
        raise HTTPException(
            status_code=409,
            detail=f"effect receipt refused ({exc.reason}): {exc.detail}",
        ) from exc

    # A principal that proposed or executed the call is not an independent
    # observer of its effect, whatever verifier identity it is bound to.
    self_attested = principal in lineage.executors
    if self_attested and separation:
        raise HTTPException(
            status_code=403,
            detail=(f"effect receipt refused (verifier_is_executor): "
                    f"{principal!r} proposed or executed this call and may not "
                    "attest to its effect"))

    # The record names the governed tool and spec, so both come from the
    # assessment in the chain. Copying them from the request let a receipt
    # store evidence about a tool or spec the dispatch never ran under.
    for name, claimed, recorded in (("tool_id", req.tool_id, tool_id),
                                    ("toolspec_hash", req.toolspec_hash,
                                     toolspec_hash)):
        if claimed and claimed != recorded:
            raise HTTPException(
                status_code=409,
                detail=(f"effect receipt refused ({name}_mismatch): the "
                        f"dispatch was assessed under {name}="
                        f"{recorded or '<none>'!r}"))

    if computed is not None:
        verdict_source = "computed"
        verification = dataclasses.replace(
            computed, status=status, verified_at=verified_at,
            dispatch_id=lineage.dispatch_id,
            tool_call_hash=lineage.tool_call_hash,
            observed_state_hash=req.source_revision or req.observed_state_hash,
            verifier_version=req.verifier_version, detail=req.detail or computed.detail,
            submitted_by=principal,
            execution_context_hash=req.execution_context_hash,
            evidence_refs=("verdict:computed", "receipt:unsigned",
                           f"claimed_status:{req.status.value}"),
        )
    else:
        verdict_source = "claimed" if claim_only else "attested"
        verification = EffectVerification(
            proposal_id=proposal_id,
            execution_id=req.execution_id,
            tool_id=tool_id,
            toolspec_hash=toolspec_hash,
            status=status,
            reason_code=req.reason_code,
            verifier_identity=req.verifier_identity,
            expected={}, observed={},
            expected_sha256=req.expected_sha256,
            observed_sha256=req.observed_sha256,
            verified_at=verified_at,
            detail=req.detail,
            dispatch_id=lineage.dispatch_id,
            tool_call_hash=lineage.tool_call_hash,
            observed_state_hash=req.observed_state_hash,
            verifier_version=req.verifier_version,
            submitted_by=principal,
            execution_context_hash=req.execution_context_hash,
            evidence_refs=(("verdict:claimed",) if claim_only else ()),
        )
    try:
        audit = record_effect_verification(
            tenant, verification,
            submitted_by=principal,
            dispatch_id=lineage.dispatch_id,
            # A claim settles nothing: a later computed verdict must still be
            # able to settle the dispatch.
            settled_dispatch_id=(lineage.dispatch_id
                                 if status.is_terminal and not claim_only
                                 else ""),
            self_attested=self_attested,
        )
    except EffectVerificationReplay as exc:
        raise HTTPException(
            status_code=409,
            detail=("effect receipt refused (receipt_replayed): this "
                    "dispatch already has a settled verdict"),
        ) from exc
    except ExecutionContextRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    return {
        "proposal_id": proposal_id,
        # The recorded status, in EffectStatus vocabulary so clients keep
        # parsing it. verdict_source says what REMORA stands behind: a
        # computed verdict, an attested status that cannot raise the state,
        # or a claim (a reported VERIFIED it had no contract to check), which
        # the proposal shows as effect_state EFFECT_CLAIMED (SDD L7).
        "status": status.value,
        "verdict_source": verdict_source,
        "effect_state": "EFFECT_CLAIMED" if claim_only else None,
        "claimed_status": req.status.value,
        "claim_disagrees": (computed is not None
                            and req.status.value != status.value),
        "dispatch_id": lineage.dispatch_id,
        "reason_code": verification.reason_code,
        "verifier_identity": req.verifier_identity,
        "self_attested": self_attested,
        # RMR-CR-008: an attestation by a verifier of this deployment, about
        # the declared delta only.
        "vantage": verification.vantage,
        "scope": verification.scope,
        "audit": audit,
    }


def _receipt_refused(exc: ReceiptRefused) -> HTTPException:
    return HTTPException(status_code=409,
                         detail=f"effect receipt refused ({exc.reason}): {exc.detail}")


def _receipt_vantage(record: Any, executors: frozenset[str]) -> Any:
    """The observation vantage of a signed receipt, derived, never declared.

    ``independent`` needs three facts, all from configuration rather than the
    receipt: the executor's control domain is declared
    (``REMORA_EXECUTOR_CONTROL_DOMAIN``), the verifier key is registered for a
    different one, and its credential on the system of record is read-only. A
    verifier that can write could have produced the state it reports.
    """
    from remora.evidence.admission.models import ObservationVantage

    executor_domain = _os.environ.get("REMORA_EXECUTOR_CONTROL_DOMAIN", "").strip()
    return ObservationVantage(
        observer_id=record.kid,
        observed_party=",".join(sorted(executors)) or "executor",
        control_domain=record.control_domain,
        # Undeclared: the executor's domain is not known to differ, so the
        # vantage cannot be established and stays same_deployment.
        observed_control_domain=executor_domain or record.control_domain,
        can_observed_party_forge=not record.read_only,
        can_observed_party_suppress=False,
    )


@router.post("/proposals/{proposal_id}/effect-receipt", responses={
    200: {"description": "REMORA computed the verdict and appended it to the audit chain."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
    409: {"model": ErrorDetail, "description": "The receipt cannot be bound or evaluated."},
    503: {"model": ErrorDetail, "description": "No verifier keys are registered."},
})
def record_signed_effect_receipt(proposal_id: str, req: SignedEffectReceiptRequest,
                                 request: Request) -> dict[str, Any]:
    """Compute and record an effect verdict from a signed receipt (CAPR-07/08).

    The digest endpoint above records an attestation. This one records a
    verdict REMORA computed: the contract comes from the signed ToolSpec v5
    ``postcondition`` block and the approved arguments, the observation from
    a receipt signed by a registered verifier key, and the vantage from that
    key's registry record. A status the receipt claims is kept beside the
    computed one and never replaces it.
    """
    _note_proposal_id(proposal_id)
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    # No "execute" fallback on this path: it exists for verifiers.
    api_mod._require_tenant_capability(role, tenant, "verify_effect")
    events = _proposal_events(tenant, proposal_id)
    if not events:
        raise HTTPException(status_code=404, detail="proposal not found")

    from remora.profiles import deployment_environment

    if deployment_environment() == "production" and not _effect_audit_is_durable():
        raise HTTPException(
            status_code=503,
            detail=("effect receipt audit store unavailable: production "
                    "requires REMORA_PG_DSN or REMORA_CHAIN_DB"))
    from remora.crypto import Signature
    from remora.governance.effect_receipt import resolve_lineage
    from remora.governance.effect_receipt_signing import (
        EffectReceipt,
        VerifierKeyRegistry,
        verify_signed_receipt,
    )

    try:
        registry = VerifierKeyRegistry.from_env()
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"effect receipt refused (effect_verifier_keys_invalid): {exc}",
        ) from exc
    if not len(registry):
        raise HTTPException(
            status_code=503,
            detail=("effect receipt refused (effect_verifier_keys_required): "
                    "REMORA_EFFECT_VERIFIER_KEYS registers no verifier key"))
    try:
        receipt = EffectReceipt.from_dict(req.receipt)
        record = verify_signed_receipt(
            receipt, Signature.from_dict(req.signature.model_dump()), registry,
            tenant=tenant)
        lineage = resolve_lineage(events)
    except ReceiptRefused as exc:
        raise _receipt_refused(exc) from exc

    # A principal that proposed or executed the call is not an observer of
    # its effect, whichever key it holds.
    if principal in lineage.executors:
        raise HTTPException(
            status_code=403,
            detail=(f"effect receipt refused (verifier_is_executor): "
                    f"{principal!r} proposed or executed this call"))

    tool_id, toolspec_hash = _assessed_tool_identity(events)
    spec = _postcondition_spec_for(tool_id)
    if spec is None:
        raise HTTPException(
            status_code=409,
            detail=(f"effect receipt refused (postcondition_not_declared): "
                    f"{tool_id!r} has no signed postcondition block, so REMORA "
                    "has no contract to evaluate"))
    computed = _computed_postcondition_verdict(
        events=events, lineage=lineage, tenant=tenant, proposal_id=proposal_id,
        tool_id=tool_id, toolspec_hash=toolspec_hash, spec=spec,
        arguments=req.arguments, observed=receipt.observed,
        verifier_identity=record.kid,
        pre_state_revision=receipt.pre_state_revision,
        source_revision=receipt.source_revision)

    try:
        lineage, status = verify_effect_receipt(
            events=events, proposal_id=proposal_id,
            claimed_status=computed.status,
            tool_call_hash=receipt.tool_call_hash, grant_jti=receipt.grant_jti,
            expected_sha256=computed.expected_sha256,
            observed_sha256=computed.observed_sha256,
            verified_at=receipt.observed_at, verifier_identity=record.kid,
            trusted_verifiers=(record.kid,), reason_code=computed.reason_code,
            already_recorded=[e.get("payload", {}) for e in events
                              if e.get("event") == "effect_verified"
                              and not is_claimed_verdict(e.get("payload", {}))],
        )
    except ReceiptRefused as exc:
        raise _receipt_refused(exc) from exc

    claim = receipt.claimed_status
    refs = ["verdict:computed", f"receipt_kid:{record.kid}",
            f"receipt_signature:{req.signature.signature}"]
    if claim:
        refs.append(f"claimed_status:{claim}")
    verification = dataclasses.replace(
        computed, status=status, verified_at=receipt.observed_at,
        dispatch_id=lineage.dispatch_id, tool_call_hash=lineage.tool_call_hash,
        observed_state_hash=receipt.source_revision, submitted_by=principal,
        execution_context_hash=lineage.execution_context_hash,
        evidence_refs=tuple(refs),
    ).observed_from(_receipt_vantage(record, lineage.executors))
    try:
        audit = record_effect_verification(
            tenant, verification, submitted_by=principal,
            dispatch_id=lineage.dispatch_id,
            settled_dispatch_id=lineage.dispatch_id if status.is_terminal else "")
    except EffectVerificationReplay as exc:
        raise HTTPException(
            status_code=409,
            detail=("effect receipt refused (receipt_replayed): this dispatch "
                    "already has a settled verdict")) from exc
    except ExecutionContextRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    return {
        "proposal_id": proposal_id,
        "status": status.value,
        "verdict_source": "computed",
        "reason_code": computed.reason_code,
        "claimed_status": claim or None,
        "claim_disagrees": bool(claim) and claim != status.value,
        "dispatch_id": lineage.dispatch_id,
        "verifier_kid": record.kid,
        "vantage": verification.vantage,
        "scope": verification.scope,
        "audit": audit,
    }


@router.get("/proposals/{proposal_id}/lifecycle", responses={
    200: {"description": "The ordered event trail for one proposal."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
})
def get_lifecycle(proposal_id: str, request: Request) -> dict[str, Any]:
    """The full ordered trail: every chain entry plus the dispatch verdict."""
    _note_proposal_id(proposal_id)
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    events = _proposal_events(tenant, proposal_id)
    if not events:
        raise HTTPException(status_code=404, detail="proposal not found")
    dispatch = _dispatch_projection(tenant, proposal_id)
    return {
        "proposal_id": proposal_id,
        "events": events,
        "dispatch": dispatch,
        "current_state": _current_state(events, dispatch),
    }


@router.get("/proposals/{proposal_id}/envelope", responses={
    200: {"description": "The DecisionEnvelope for one proposal, derived from "
                         "the audit chain."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
})
def get_envelope(proposal_id: str, request: Request) -> dict[str, Any]:
    """One envelope binding proposal to effect (issue #37).

    Derived from the chain on read, never stored: a written copy could drift
    from the records it describes, which is the divergence the lifecycle trail
    exists to prevent. ``effect`` is populated from what was actually recorded
    — the dispatch verdict, the outbox row and any effect verification — so an
    envelope no longer stops at the decision.
    """
    _note_proposal_id(proposal_id)
    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    events = _proposal_events(tenant, proposal_id)
    if not events:
        raise HTTPException(status_code=404, detail="proposal not found")
    envelope = _envelope_projection(
        events, _dispatch_projection(tenant, proposal_id),
        proposal_id=proposal_id, tenant=tenant,
    )
    return envelope.to_dict()


@router.get("/proposals/{proposal_id}/evidence", responses={
    200: {"description": "Exportable evidence bundle with a hashed manifest."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
})
def export_evidence(proposal_id: str, request: Request) -> dict[str, Any]:
    """Everything recorded about one proposal, with a hashed manifest.

    The manifest hashes each section it lists, so a bundle cannot be
    edited without the manifest disagreeing. That is tamper-EVIDENCE:
    anyone recomputing the hashes sees the change. It is not tamper-proof
    — a party who rewrites both bundle and manifest produces a
    self-consistent forgery, which is why the audit chain's own
    verification travels with the bundle rather than being replaced by it.
    """
    _note_proposal_id(proposal_id)
    import hashlib as _hashlib

    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    events = _proposal_events(tenant, proposal_id)
    if not events:
        raise HTTPException(status_code=404, detail="proposal not found")

    dispatch = _dispatch_projection(tenant, proposal_id)
    valid, problems = _CHAIN.verify(tenant)
    sections: dict[str, Any] = {
        "proposal": {
            "proposal_id": proposal_id,
            "current_state": _current_state(events, dispatch),
            "tenant": tenant,
        },
        "lifecycle": {"events": events, "dispatch": dispatch},
        # Always present, even when empty: a missing section cannot be
        # distinguished from an export that predates verification.
        "effect_verification": _effect_projection(events),
        "policy_identity": api_mod._policy_component_hashes(),
        "audit_verification": {
            "valid": valid,
            "problems": problems,
            "records_checked": len(_CHAIN.entries(tenant)),
        },
        # Q7.3: authentic is not complete. Each contract names the evidence
        # its claim needs; the verdict says whether this proposal has it.
        "evidence_coverage": _evidence_coverage(events, problems),
        # Q8.7: which capability set each assessment was checked against.
        "capability_decision": _capability_decision(events),
    }
    try:
        context = historical_context(_CHAIN, tenant, proposal_id)
    except ExecutionContextRefused as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    if context is not None:
        sections["execution_context"] = {
            "canonical": context.canonical_bytes().decode("utf-8"),
            "sha256": context.digest(),
        }

    def _digest(value: Any) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                               default=str)
        return _hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    bundle: dict[str, Any] = dict(sections)
    bundle["manifest"] = {
        "proposal_id": proposal_id,
        "tenant": tenant,
        "remora_version": api_mod.__dict__.get("__version__")
        or _remora_version(),
        "exported_at": datetime.now(UTC).isoformat(),
        "event_count": len(events),
        "section_sha256": {name: _digest(v) for name, v in sections.items()},
    }
    return bundle


@router.get("/proposals/{proposal_id}/invocation-evidence", responses={
    200: {"description": "One executed direct-ACCEPT invocation, signed under "
                         "REMORA/EVIDENCE/v1 for offline verification."},
    **_AUTH_RESPONSES,
    404: {"model": ErrorDetail, "description": "No such proposal for this tenant."},
    409: {"model": ErrorDetail,
          "description": "The proposal is not one executed direct ACCEPT with its "
                         "grant recorded."},
    503: {"model": ErrorDetail, "description": "No evidence signing key is configured."},
})
def export_invocation_evidence(proposal_id: str, request: Request) -> dict[str, Any]:
    """The signed per-invocation export (remora/execution/invocation_evidence.py).

    Unlike ``/evidence`` it carries the signed grant and lease with the exact
    bytes their signatures cover, the chain entries with the strings their
    hashes cover, and a signature over the whole, so a verifier holding only
    public keys can check it without this service.
    """
    _note_proposal_id(proposal_id)
    from remora.execution.invocation_evidence import (
        InvocationEvidenceUnavailable,
        build_invocation_evidence,
        evidence_signing_key,
    )

    tenant, role, _principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "read")
    try:
        return build_invocation_evidence(
            _CHAIN.entries(tenant), tenant=tenant, proposal_id=proposal_id,
            signing_key=evidence_signing_key())
    except InvocationEvidenceUnavailable as exc:
        status = {"proposal_not_found": 404,
                  "evidence_key_unavailable": 503}.get(exc.reason, 409)
        raise HTTPException(status_code=status, detail=exc.reason) from exc


def _evidence_coverage(events: list[dict[str, Any]],
                       problems: list[str]) -> dict[str, Any]:
    """Coverage of this proposal's chain entries against the two claims a
    reader usually makes about an execution (remora/governance/evidence_coverage.py)."""
    from remora.governance.evidence_coverage import (
        AUTHORIZED_EXECUTION,
        EXECUTED_EFFECT,
        SUCCESS_ESTABLISHED,
        SUCCESS_ESTABLISHED_V2,
        assess_coverage,
        chain_event_items,
    )

    items = chain_event_items(events, problems)
    return {contract.contract_id: assess_coverage(contract, items).to_dict()
            for contract in (AUTHORIZED_EXECUTION, EXECUTED_EFFECT, SUCCESS_ESTABLISHED,
                             SUCCESS_ESTABLISHED_V2)}


def _capability_decision(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The capability checks recorded for one proposal (Q8.7), latest last.

    Always present, even when empty: an absent capability decision must be
    distinguishable from an export that predates the section.
    """
    decisions = [dict(e["payload"]["capability"]) for e in events
                 if e.get("event") == "assessed"
                 and isinstance((e.get("payload") or {}).get("capability"), dict)]
    return {"decisions": decisions,
            "latest": decisions[-1] if decisions else None}


def _remora_version() -> str:
    try:
        import remora

        return str(getattr(remora, "__version__", "unknown"))
    except Exception:  # pragma: no cover - version lookup must never fail a read
        return "unknown"


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
    entries = _CHAIN.entries(tenant)
    records_checked = len(entries)
    from remora.governance.tenant_chain import verification_statuses

    return {
        "tenant": tenant,
        "valid": ok,
        "problems": problems,
        # An empty chain is trivially valid; auditors and the evidence bundle
        # must be able to tell "verified history" from "nothing to verify".
        "records_checked": records_checked,
        "empty": records_checked == 0,
        # RMR-CR-007: "valid" alone read as intact even when no signature was
        # compared. These say which checks ran.
        **verification_statuses(entries, problems),
    }
