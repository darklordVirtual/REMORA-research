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

from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.nonce_store import DurableNonceStore, NonceStore
from remora.governance.effect_receipt import (
    ReceiptRefused,
    verify_receipt as verify_effect_receipt,
)
from remora.enforcement.lease import (
    ExecutionLease,
    GovernedToolDispatcher,
)
from remora.toolcall.deployment_registry import resolve_tool_metadata
from remora.enforcement.token import PolicyDecisionToken
from remora.enforcement.outbox import (
    ExecutionOutbox,
    PostgresExecutionOutbox,
    SQLiteExecutionOutbox,
)
from remora.governance.effect_verification import (
    EffectVerification,
)
from remora.governance.lifecycle import (
    IllegalTransition,
    check_transition,
)
from remora.governance.review_queue import (
    ReviewQueue,
)
from remora.governance.revocation_store import (
    DurableRevocationStore,
    RevocationStore,
    RevocationStoreUnavailable,
)
from remora.governance import audit_outbox as _audit_outbox
from remora.governance.tenant_chain import TenantAuditChain
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation, canonical_tool_call_hash
from remora.policy.report import DecisionAction
from remora.toolcall.toolspec import ToolSpecBundle, ToolSpecRefused
from remora.toolcall.semantic_bundle import (
    IntentResolver,
    SemanticBundle,
    compute_intent_authority_hash,
    load_argument_scope_validator,
    load_intent_resolver,
    load_intent_resolution_provider,
    load_semantic_bundle,
)
# Wire contracts (issue #241 extraction slice 1): request/response Pydantic
# models live in servers/execution_contracts.py; re-imported here so existing
# `from servers.execution_api import ToolCallRequest` style access keeps
# working (test suites patch through this module's namespace).
from servers.execution_contracts import (  # noqa: F401
    _AUTH_RESPONSES,
    ApproveRequest,
    AuditRef,
    DerivationProposal,
    EffectVerificationRequest,
    ErrorDetail,
    DispatchLeasedRequest,
    ExecuteAcceptedRequest,
    ExecuteRequest,
    ExecutionApproveResponse,
    ExecutionAssessResponse,
    ExecutionAuditVerifyResponse,
    ExecutionExecuteResponse,
    ExecutionPendingResponse,
    ExecutionGrant,
    ExecutionOutcome,
    GovernanceAction,
    PepResult,
    RejectRequest,
    SemanticAssessment,
    ToolCallRequest,
    ToolExecutionResult,
    ToolResultEnvelopeModel,
    RevokePrincipalRequest,
)

#: The only path the execution domain serves.
#:
#: Exact equality, not a prefix or a substring. An allowlist that matches
#: loosely is the defect this repository already recorded once: a WITH ...
#: INSERT passed a read-only SQL check because the match was unanchored
#: (NEGATIVE_RESULTS section 51). A prefix test here would admit
#: /dispatch-leased-anything.
_EXECUTOR_PATHS = frozenset({"/v1/execution/dispatch-leased"})

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


def _execution_domain() -> str:
    value = (_os.getenv("REMORA_EXECUTION_DOMAIN_ROLE") or "").strip().lower()
    if value in (_DOMAIN_AUTHORITY, _DOMAIN_EXECUTOR):
        return value
    if value:
        # An unrecognised role is a configuration error, and guessing which
        # half was meant is the wrong way to resolve it.
        raise RuntimeError(
            f"REMORA_EXECUTION_DOMAIN_ROLE={value!r} is neither "
            f"{_DOMAIN_AUTHORITY!r} nor {_DOMAIN_EXECUTOR!r}")
    return _DOMAIN_AUTHORITY


def _enforce_execution_domain(request: Request) -> None:
    """Refuse authority routes when this process is the executor.

    Attached to the router rather than to each route: a per-route decorator is
    a list that a new endpoint silently fails to join, and that failure mode is
    an authority route quietly reachable from the execution domain.
    """
    if _execution_domain() != _DOMAIN_EXECUTOR:
        return
    if request.url.path in _EXECUTOR_PATHS:
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

    def _flag(name: str) -> bool:
        return _env.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

    return RemoraDecisionEngine(
        low_consequence_accept=_flag("REMORA_LOW_CONSEQUENCE_ACCEPT"),
        grounded_read_accept=_flag("REMORA_GROUNDED_READ_ACCEPT"),
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
from remora.persistence.idempotency import (  # noqa: E402
    IdempotencyStore,
    build_idempotency_store,
)

import threading as _threading

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


def _idempotency_get(tenant: str, key: str) -> dict[str, Any] | None:
    return _idempotency_store().get(tenant, key)


def _idempotency_put(tenant: str, key: str, response: dict[str, Any]) -> None:
    _idempotency_store().put(tenant, key, response)

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
import datetime as _dt
import dataclasses

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
CURRENT_PROPOSAL_ID: "_contextvars.ContextVar[dict[str, str | None] | None]" = (
    _contextvars.ContextVar("remora_current_proposal_id", default=None)
)


def _note_proposal_id(proposal_id: Any) -> None:
    holder = CURRENT_PROPOSAL_ID.get()
    if holder is not None and proposal_id:
        holder["id"] = str(proposal_id)

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



def chain_append_transactional(
    tenant: str, payload: "dict[str, Any]", *, key: str
) -> "Any | None":
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
    except Exception:  # noqa: BLE001
        # Recovery that raises would turn a durable, recoverable gap into a
        # failed request. The row stays pending and the next sweep retries.
        return 0


def reconcile_stale_dispatches(
    tenant: str, *, now: "datetime | None" = None
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
from remora.execution.dispatch import (
    dispatch_under_lease as _dispatch_under_lease_impl,
    record_dispatch_intent as _record_dispatch_intent_impl,
)
from remora.execution.service import (
    TokenRefused,
    ToolSpecChanged,
    assess_proposal as _assess_proposal,
    execute_approved_item as _execute_approved_item,
    redeem_accept_token as _redeem_accept_token,
)
from remora.execution.review_service import (
    ReviewConflict,
    ReviewNotFound,
    approve_item as _approve_item,
    reject_item as _reject_item,
)
from remora.execution.authorization import (
    assessed_record as _authz_assessed_record,
    load_toolspec_bundle as _authz_load_bundle,
    reset_toolspec_bundle_cache as _reset_toolspec_bundle,  # noqa: F401  (test hook name kept)
    resolve_toolspec as _authz_resolve_toolspec,
)


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
    from remora.execution.service import dispatch_pending_intent

    results: list[dict[str, Any]] = []
    for row in _outbox().pending(tenant):
        result = dispatch_pending_intent(
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
            resolve_toolspec=_resolve_toolspec,
            policy_coverage=_policy_coverage,
            rebuild_call=_rebuild_tool_call,
        )
        if result is not None:
            results.append(result)
    return results


def _toolspec_bundle() -> "ToolSpecBundle | None":
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


def _assessed_record(tenant: str, item_id: str) -> tuple[str, str]:
    return _authz_assessed_record(_CHAIN, tenant, item_id)


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
    return tenant, role, api_mod._authenticated_principal(request)


import json

# Review-state persistence (issue #241 extraction slice 2): the transaction
# adapter lives in remora/persistence/execution_state.py. to_dict/from_dict
# are re-imported so existing imports through this module keep working.
from remora.persistence.execution_state import (  # noqa: F401
    from_dict,
    to_dict,
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


def _lease_nonce_store() -> "NonceStore | None":
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
                )
                # RMR-004: the lease has always carried the signed spec
                # identity and verify() has always been able to check it.
                # Nothing supplied it, so the identity sat inside the
                # signature and was inert at the final PEP. This resolves the
                # spec THIS process would run, at the moment of dispatch, so a
                # bundle that moved between approval and execution refuses.
                dispatcher.bind_toolspec_identity(_toolspec_identity)
                spec = _os.environ.get("REMORA_TOOL_REGISTRY_MODULE", "").strip()
                if spec:
                    import importlib

                    importlib.import_module(spec).register_tools(
                        dispatcher.register
                    )
                _DISPATCHER = dispatcher
    return _DISPATCHER


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
        return _registry_only_observation(req, tenant, registry_entry), context

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
    idemp_key = req.idempotency_key or None
    if idemp_key:
        cached = _idempotency_get(tenant, idemp_key)
        if cached is not None:
            return cached

    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "assess")
    # FT-02 lazy sweep (same discipline as REM-032's TTL sweep): a dispatch
    # whose worker never reported back is settled as UNKNOWN before new
    # work is considered, so a stranded intent cannot linger unnoticed.
    reconcile_stale_dispatches(tenant)
    # Orchestration lives in remora.execution.service (issue #241, slice 7);
    # this route binds the module's ambient state and stays HTTP conversion.
    response = _assess_proposal(
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
    )
    api_mod.record_execution_assess(response["decision"])

    if idemp_key:
        _idempotency_put(tenant, idemp_key, response)
    return response


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

    def _authorize_approval(item: Any) -> None:
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

    try:
        response = _approve_item(
            tenant=tenant, principal=principal, item_id=req.item_id,
            approval_ttl_seconds=req.approval_ttl_seconds,
            on_behalf_of=req.on_behalf_of,
            transaction=db_transaction_state, item_tenant=_ITEM_TENANT,
            chain=_CHAIN, authorize_approval=_authorize_approval,
            lifecycle_guard=_lifecycle_guard,
            note_proposal_id=_note_proposal_id,
        )
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    api_mod.record_execution_approval()
    return response


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
    try:
        with db_transaction_state(tenant) as q:
            q.revoke_principal(req.principal, reason=req.reason or "")
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
    _CHAIN.append(tenant, {
        "event": "principal_revoked",
        "principal": req.principal,
        "revoked_by": revoker,
        "reason": req.reason or "",
    })
    return {"principal": req.principal, "revoked_by": revoker, "status": "revoked"}


def _resolution_plan_for(
    *,
    action: "DecisionAction",
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


def _dispatch_under_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: "ToolCallRequest",
    semantic: dict[str, Any],
    now: datetime,
    gate_allowed: bool = True,
    toolspec: dict[str, Any] | None = None,
    proposal_id: str = "",
    grant_jti: str = "",
    presented_lease: Any = None,
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
            dispatcher=_tool_dispatcher(),
            policy_bundle_hash=_current_policy_bundle_hash(),
            gate_allowed=gate_allowed,
            toolspec=toolspec,
            proposal_id=proposal_id,
            grant_jti=grant_jti,
            presented_lease=presented_lease,
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
    409: {"model": ErrorDetail, "description": "Item not in an executable state."},
})
def execute(req: ExecuteRequest, request: Request) -> "dict[str, Any] | JSONResponse":
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
    # Issue #82: async mode answers 202 after durable authorization; the
    # dispatch half belongs to the standalone worker
    # (scripts/run_dispatch_worker.py). Default stays synchronous.
    async_mode = _os.environ.get(
        "REMORA_ASYNC_DISPATCH", "").strip().lower() in {"1", "true", "yes", "on"}
    # Orchestration lives in remora.execution.service (issue #241, slice 8);
    # this route binds the module's ambient state and maps domain errors.
    try:
        response = _execute_approved_item(
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
            async_dispatch=async_mode,
        )
    except ToolSpecChanged as exc:
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
                         "mismatch, expired, wrong audience, or not an ACCEPT."},
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
    reconcile_stale_dispatches(tenant)

    try:
        token = PolicyDecisionToken.from_dict(req.execution_token)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409, detail=f"malformed execution token: {exc}"
        ) from exc

    # Orchestration lives in remora.execution.service (issue #241, slice 9);
    # this route binds the module's ambient state and maps domain errors.
    try:
        response = _redeem_accept_token(
            tenant=tenant, principal=principal, token=token,
            tool_call=req.tool_call,
            chain=_CHAIN, gate=_GATE, outbox=_outbox,
            worker_id=f"api:{_os.getpid()}",
            build_observation=_observation_with_context,
            record_dispatch_intent=_record_dispatch_intent,
            dispatch_under_lease=_dispatch_under_lease,
            lifecycle_guard=_lifecycle_guard,
            note_proposal_id=_note_proposal_id,
        )
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
    tenant, role, principal = _auth(request)
    from servers import api as api_mod

    api_mod._require_tenant_capability(role, tenant, "execute")

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
    tool_execution = _dispatch_under_lease(
        tenant=tenant,
        # From the SIGNED lease, never the request body and never the hop's
        # own principal. The body form let a caller with a stolen lease assert
        # the victim's identity; the hop principal is the authority, not the
        # end actor, so using it would refuse every legitimate call.
        principal=lease.actor_identity,
        tool_call=req.tool_call,
        semantic={"tool_contract_bundle_hash": lease.tool_contract_bundle_hash,
                  "intent_authority_hash": lease.intent_authority_hash},
        now=now,
        proposal_id=lease.proposal_id,
        grant_jti=lease.grant_jti,
        presented_lease=lease,
    )
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
        )
    except ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc


# Lifecycle/effect projections (issue #241, extraction slice 5): the derived
# read projections live in remora/execution/projections.py. Wrappers bind this
# module's chain and outbox; record_effect_verification keeps its public name
# (used by the SDK effect surface and tests).
from remora.execution.projections import (  # noqa: E402
    EFFECT_STATE as _EFFECT_STATE,  # noqa: F401  (name kept for tests)
    EffectVerificationReplay,
    current_state as _current_state_impl,
    dispatch_projection as _dispatch_projection_impl,
    effect_projection as _effect_projection,  # noqa: F401  (pure; direct use)
    envelope_projection as _envelope_projection,
    proposal_events as _proposal_events_impl,
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
                               settled_dispatch_id: str = "") -> dict[str, Any]:
    """Append one effect verification to the tenant audit chain (see
    remora.execution.projections for the appending/never-editing contract)."""
    return _record_effect_verification_impl(
        _CHAIN, tenant, verification, submitted_by=submitted_by,
        dispatch_id=dispatch_id, settled_dispatch_id=settled_dispatch_id,
    )


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
        "review_item_id": assessed.get("review_item_id"),
        "current_state": _current_state(events, dispatch),
        "event_count": len(events),
        "dispatch": dispatch,
        "effect": _effect_projection(events),
    }


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

    api_mod._require_tenant_capability(role, tenant, "execute")
    events = _proposal_events(tenant, proposal_id)
    if not events:
        raise HTTPException(status_code=404, detail="proposal not found")

    if _os.environ.get("REMORA_ENV", "").strip().lower() in {
        "prod", "production"
    } and not _effect_audit_is_durable():
        raise HTTPException(
            status_code=503,
            detail=("effect receipt audit store unavailable: production "
                    "requires REMORA_PG_DSN or REMORA_CHAIN_DB so receipt "
                    "uniqueness and its audit evidence commit together; "
                    "REMORA_STATE_ENDPOINT does not yet store the tenant "
                    "audit chain"),
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

    # A settled verdict is accepted only when bound to a real dispatch.
    # Everything the receipt is checked against is read from the audit chain;
    # nothing here trusts the request about which dispatch it describes.
    try:
        lineage, status = verify_effect_receipt(
            events=events,
            proposal_id=proposal_id,
            claimed_status=req.status,
            tool_call_hash=req.tool_call_hash,
            grant_jti=req.grant_jti,
            expected_sha256=req.expected_sha256,
            observed_sha256=req.observed_sha256,
            verified_at=verified_at,
            verifier_identity=req.verifier_identity,
            trusted_verifiers=(),
            already_recorded=[
                e.get("payload", {}) for e in events
                if e.get("event") == "effect_verified"
            ],
        )
    except ReceiptRefused as exc:
        # 409, not 400: the receipt is well-formed and the conflict is with
        # the recorded history, which is what the caller needs told.
        raise HTTPException(
            status_code=409,
            detail=f"effect receipt refused ({exc.reason}): {exc.detail}",
        ) from exc

    verification = EffectVerification(
        proposal_id=proposal_id,
        execution_id=req.execution_id,
        tool_id=req.tool_id,
        toolspec_hash=req.toolspec_hash,
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
    )
    try:
        audit = record_effect_verification(
            tenant, verification,
            submitted_by=principal,
            dispatch_id=lineage.dispatch_id,
            settled_dispatch_id=(lineage.dispatch_id
                                 if status.is_terminal else ""),
        )
    except EffectVerificationReplay as exc:
        raise HTTPException(
            status_code=409,
            detail=("effect receipt refused (receipt_replayed): this "
                    "dispatch already has a settled verdict"),
        ) from exc
    return {
        "proposal_id": proposal_id,
        # The adjudicated attestation status. REMORA binds and refuses; it
        # cannot re-run the deployment's postcondition comparison.
        "status": status.value,
        "claimed_status": req.status.value,
        "dispatch_id": lineage.dispatch_id,
        "reason_code": req.reason_code,
        "verifier_identity": req.verifier_identity,
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
