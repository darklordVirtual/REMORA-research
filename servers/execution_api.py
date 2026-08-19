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
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.lease import (
    GovernedToolDispatcher,
)
from remora.toolcall.deployment_registry import resolve_tool_metadata
from remora.enforcement.token import PolicyDecisionToken
from remora.enforcement.outbox import (
    ExecutionOutbox,
    OutboxState,
    PostgresExecutionOutbox,
    SQLiteExecutionOutbox,
)
from remora.governance.effect_verification import (
    EffectVerification,
)
from remora.governance.proposal_lineage import (
    derive_lineage,
    lineage_key_for,
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
from remora.toolcall.toolspec import ToolSpecBundle, ToolSpecRefused
from remora.toolcall.semantic_bundle import (
    IntentResolver,
    SemanticBundle,
    compute_intent_authority_hash,
    load_intent_resolver,
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
    ExecuteAcceptedRequest,
    ExecuteRequest,
    ExecutionApproveResponse,
    ExecutionAssessResponse,
    ExecutionAuditVerifyResponse,
    ExecutionExecuteResponse,
    ExecutionGrant,
    ExecutionOutcome,
    GovernanceAction,
    PepResult,
    RejectRequest,
    SemanticAssessment,
    ToolCallRequest,
    ToolExecutionResult,
    ToolResultEnvelopeModel,
)

router = APIRouter(prefix="/v1/execution", tags=["execution"])

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
    )


_ENGINE = _engine_from_env()
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
from remora.execution.authorization import (
    assessed_record as _authz_assessed_record,
    load_toolspec_bundle as _authz_load_bundle,
    reset_toolspec_bundle_cache as _reset_toolspec_bundle,  # noqa: F401  (test hook name kept)
    resolve_toolspec as _authz_resolve_toolspec,
)


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
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _assessed_toolspec(tenant: str, item_id: str) -> str:
    """The ToolSpec hash recorded at assessment for this review item."""
    return _assessed_record(tenant, item_id)[0]


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
):
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
from uuid import uuid4

# Review-state persistence (issue #241 extraction slice 2): the transaction
# adapter lives in remora/persistence/execution_state.py. to_dict/from_dict
# are re-imported so existing imports through this module keep working.
from remora.persistence.execution_state import (  # noqa: F401
    from_dict,
    to_dict,
    transaction_state as _transaction_state,
)


def db_transaction_state(tenant: str):
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
    toolspec_identity = _resolve_toolspec(
        req.tool_name, req.arguments, req.target_environment
    )
    # Popped, not recorded: the roles are spec data the lineage key needs,
    # and copying them into every audit record and response would grow
    # both without telling a reader anything the spec hash does not.
    _argument_roles = toolspec_identity.pop("argument_roles", {})
    proposal_id = str(uuid4())
    _note_proposal_id(proposal_id)
    obs = dataclasses.replace(obs, proposal_id=proposal_id)
    report = _ENGINE.decide(obs)
    now = datetime.now(UTC)
    # Derived from the chain, never from the request: a caller-declared
    # "this supersedes X" would be defeated by the one caller it exists to
    # catch, who simply omits it. Read BEFORE any transaction opens —
    # reading the chain inside one deadlocks against SQLite's exclusive
    # write lock, the trap the outbox and the ToolSpec lookup both hit.
    _lineage_key = lineage_key_for(
        actor=principal,
        tool_name=req.tool_name,
        target_environment=req.target_environment or "",
        arguments=req.arguments,
        argument_roles=_argument_roles,
    )
    _lineage = derive_lineage(
        [{"timestamp": e.timestamp, "payload": e.payload}
         for e in _CHAIN.entries(tenant)],
        _lineage_key, now=datetime.now(UTC).isoformat(),
    )

    record: dict[str, Any] = {
        "event": "assessed",
        "proposal_id": proposal_id,
        "actor": principal,
        "tool_name": req.tool_name,
        "tool_call_hash": obs.tool_call_hash,
        # Carried so a LATER derivation can match this proposal. Without
        # them the lineage key could never be reconstructed from the
        # chain, and every proposal would look like a first attempt.
        "target_environment": req.target_environment or "",
        "lineage_resource": _lineage_key.resource,
        "superseded_proposal_id": _lineage.superseded_proposal_id,
        "lineage": _lineage.to_dict(),
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "policy_version": report.policy_version,
        # SHELF-020: the decision names the declaration set and intent source
        # it was made under. Empty strings mean "no bundle configured" — the
        # registry-only path, recorded rather than assumed away.
        "tool_contract_bundle_hash": semantic["tool_contract_bundle_hash"],
        "state_hash": semantic["state_hash"],
        "intent_authority_hash": semantic["intent_authority_hash"],
        "toolspec_hash": toolspec_identity["hash"],
        "toolspec_version": toolspec_identity["version"],
    }
    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "tool_call_hash": obs.tool_call_hash,
        "semantic": dict(semantic),
        "toolspec": dict(toolspec_identity),
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
    # Shadow only: the decision above was NOT influenced by this. A
    # consumer must be able to see the probing signal without being misled
    # into thinking it changed the routing.
    response["lineage"] = _lineage.to_dict()
    response["resolution_plan"] = _resolution_plan_for(
        action=report.action, report=report, tenant=tenant,
        item=item if report.action is not DecisionAction.ACCEPT else None,
    )
    entry = _CHAIN.append(tenant, record)
    response["audit"] = {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash}
    api_mod.record_execution_assess(report.action.value)

    if idemp_key:
        _idempotency_put(idemp_key, response)
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
    _note_proposal_id(proposal_id)
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


def _dispatch_under_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: "ToolCallRequest",
    semantic: dict[str, Any],
    now: datetime,
    gate_allowed: bool = True,
    toolspec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Governed dispatch (see remora.execution.dispatch); binds this module's
    dispatcher and current policy bundle hash. Shared by /execute and
    /execute-accepted so both get identical enforcement."""
    return _dispatch_under_lease_impl(
        tenant=tenant,
        principal=principal,
        tool_call=tool_call,
        semantic=semantic,
        now=now,
        dispatcher=_tool_dispatcher(),
        policy_bundle_hash=_current_policy_bundle_hash(),
        gate_allowed=gate_allowed,
        toolspec=toolspec,
    )


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
    # FT-03: the spec in force NOW, re-checked against the same call. A
    # redeployed bundle is caught below by comparing it with the hash the
    # assessment recorded — an approval granted under one spec must never
    # execute under another.
    toolspec_identity = _resolve_toolspec(
        req.tool_call.tool_name, req.tool_call.arguments,
        req.tool_call.target_environment,
    )
    toolspec_identity.pop("argument_roles", None)
    _assessed_toolspec_hash, _assessed_proposal_id = _assessed_record(
        tenant, req.item_id)
    _note_proposal_id(_assessed_proposal_id)
    # Refuse BEFORE authorizing, not after. The check has everything it
    # needs here, and running it later left a dispatch intent behind for a
    # call that was never allowed to happen — harmless only because an
    # unclaimed intent provably never ran, which is a thin thing to rely
    # on. Found by the end-to-end vertical (handoff gate §3).
    if (toolspec_identity["enforced"] and _assessed_toolspec_hash
            and toolspec_identity["hash"] != _assessed_toolspec_hash):
        _CHAIN.append(tenant, {
            "event": "execution_toolspec_changed",
            "proposal_id": _assessed_proposal_id,
            "actor": principal,
            "item_id": req.item_id,
            "assessed_toolspec_hash": _assessed_toolspec_hash,
            "current_toolspec_hash": toolspec_identity["hash"],
        })
        raise HTTPException(
            status_code=409,
            detail=(
                "toolspec_changed_between_assess_and_dispatch: the spec "
                "in force is not the one this approval was granted under"
            ),
        )

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
            _note_proposal_id(proposal_id)
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
        "toolspec": dict(toolspec_identity),
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

    tool_execution = _dispatch_under_lease(
        tenant=tenant,
        principal=principal,
        tool_call=req.tool_call,
        semantic=fresh_semantic,
        now=now,
        gate_allowed=gate_result.allowed,
        toolspec=toolspec_identity,
    )

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

    obs, semantic = _observation_with_context(req.tool_call, tenant)
    proposal_id = token.request_id or None
    _note_proposal_id(proposal_id)

    # (1) Binding first, and WITHOUT consuming: a mismatched payload must not
    # burn the grant for the call the token actually authorizes.
    if token.observation_hash != (obs.tool_call_hash or ""):
        _CHAIN.append(tenant, {
            "event": "execution_binding_refused",
            "proposal_id": proposal_id,
            "actor": principal,
            "tool_call_hash": obs.tool_call_hash,
            "detail": "payload does not match the token binding",
        })
        api_mod.record_execution_execute(executed=False, refusal="binding_refused")
        raise HTTPException(
            status_code=409,
            detail="binding refused: the presented tool call does not match "
                   "the one this token authorizes",
        )

    if str(token.action).lower() != "accept":
        raise HTTPException(
            status_code=409,
            detail=f"token authorizes {token.action!r}, not an autonomous "
                   "execution; only an ACCEPT may be redeemed here",
        )

    # (2) Consume exactly once. A refused check here is expiry, audience
    # mismatch, a bad signature, or a replay — all terminal for this token.
    gate_result = _GATE.check(token, obs.tool_call_hash, consume=True)
    if not gate_result.allowed:
        _CHAIN.append(tenant, {
            "event": "execution_grant_refused",
            "proposal_id": proposal_id,
            "actor": principal,
            "grant_jti": token.jti,
            "detail": gate_result.reason,
        })
        api_mod.record_execution_execute(executed=False, refusal=str(gate_result.reason))
        raise HTTPException(
            status_code=409, detail=f"execution grant refused: {gate_result.reason}"
        )

    _lifecycle_guard("ASSESSED", "direct_accept_token")

    now = datetime.now(UTC)
    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "outcome": ExecutionDecision.EXECUTE.value,
        "detail": "authorized by single-use ACCEPT token",
        "execution_grant": token.to_dict(),
        "pep": {"allowed": gate_result.allowed, "reason": gate_result.reason},
    }

    # (3) Durable dispatch intent before any side effect (FT-02).
    intent = _record_dispatch_intent(
        proposal_id=str(proposal_id or token.jti),
        tenant=tenant,
        item_id=f"accept:{token.jti}",
        tool_name=req.tool_call.tool_name,
        tool_call_hash=obs.tool_call_hash or "",
        grant_jti=token.jti,
    )
    intent_entry = _CHAIN.append(tenant, {
        "event": "execution_authorized",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": f"accept:{token.jti}",
        "tool_call_hash": obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
        "tool_contract_bundle_hash": semantic["tool_contract_bundle_hash"],
        "intent_authority_hash": semantic["intent_authority_hash"],
    })
    if intent is not None:
        _outbox().claim(intent.outbox_id, worker_id=f"api:{_os.getpid()}")

    # (4) Governed dispatch — same dispatcher, same lease discipline.
    tool_execution = _dispatch_under_lease(
        tenant=tenant,
        principal=principal,
        tool_call=req.tool_call,
        semantic=semantic,
        now=now,
    )

    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        if tool_execution["executed"]:
            settled_state = OutboxState.SUCCEEDED
        elif reason == "tool_failed_nonce_burned":
            settled_state = OutboxState.FAILED
        else:
            settled_state = OutboxState.REFUSED
        _outbox().settle(intent.outbox_id, settled_state, detail=reason)

    result_record: dict[str, Any] = {
        "event": "execution_result",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": f"accept:{token.jti}",
        "tool_call_hash": obs.tool_call_hash,
        "grant_jti": token.jti,
        "intent_sequence_no": intent_entry.sequence_no,
        "tool_executed": tool_execution["executed"],
    }
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    entry = _CHAIN.append(tenant, result_record)

    response["tool_execution"] = tool_execution
    response["audit"] = {
        "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
    }
    api_mod.record_execution_execute(
        executed=bool(tool_execution["executed"]),
        refusal=tool_execution.get("refusal_reason"),
    )
    return response


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
        with db_transaction_state(tenant) as q:
            if _ITEM_TENANT.get(req.item_id) != tenant:
                raise KeyError(req.item_id)
            q.expire_due()
            item = q.reject(req.item_id, reviewer=principal, reason=req.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review item not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _lifecycle_guard("REVIEW_PENDING", "human_rejection")
    proposal_id = getattr(item.observation, "proposal_id", None)
    _note_proposal_id(proposal_id)
    entry = _CHAIN.append(tenant, {
        "event": "rejected",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": req.item_id,
        "reason": req.reason,
    })
    return {
        "status": "rejected",
        "proposal_id": proposal_id,
        "item_id": req.item_id,
        "reason": req.reason,
        "audit": {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash},
    }


# Lifecycle/effect projections (issue #241, extraction slice 5): the derived
# read projections live in remora/execution/projections.py. Wrappers bind this
# module's chain and outbox; record_effect_verification keeps its public name
# (used by the SDK effect surface and tests).
from remora.execution.projections import (  # noqa: E402
    EFFECT_STATE as _EFFECT_STATE,  # noqa: F401  (name kept for tests)
    current_state as _current_state_impl,
    dispatch_projection as _dispatch_projection_impl,
    effect_projection as _effect_projection,  # noqa: F401  (pure; direct use)
    proposal_events as _proposal_events_impl,
    record_effect_verification as _record_effect_verification_impl,
)


def _proposal_events(tenant: str, proposal_id: str) -> list[dict[str, Any]]:
    return _proposal_events_impl(_CHAIN, tenant, proposal_id)


def _dispatch_projection(tenant: str, proposal_id: str) -> dict[str, Any] | None:
    return _dispatch_projection_impl(_outbox(), tenant, proposal_id)


def record_effect_verification(tenant: str, verification: Any, *,
                               submitted_by: str = "") -> dict[str, Any]:
    """Append one effect verification to the tenant audit chain (see
    remora.execution.projections for the appending/never-editing contract)."""
    return _record_effect_verification_impl(
        _CHAIN, tenant, verification, submitted_by=submitted_by
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
    assessed = next(
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
    if not _proposal_events(tenant, proposal_id):
        raise HTTPException(status_code=404, detail="proposal not found")

    verification = EffectVerification(
        proposal_id=proposal_id,
        execution_id=req.execution_id,
        tool_id=req.tool_id,
        toolspec_hash=req.toolspec_hash,
        status=req.status,
        reason_code=req.reason_code,
        verifier_identity=req.verifier_identity,
        expected={}, observed={},
        expected_sha256=req.expected_sha256,
        observed_sha256=req.observed_sha256,
        verified_at=req.verified_at or datetime.now(UTC).isoformat(),
        detail=req.detail,
    )
    audit = record_effect_verification(tenant, verification,
                                       submitted_by=principal)
    return {
        "proposal_id": proposal_id,
        "status": req.status.value,
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
