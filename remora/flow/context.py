# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Flow contexts and the high-water label (SDD v1.3 §3.2, IFC-02).

A context is minted server-side (``ctx_`` + 128 random bits) for an
authenticated principal of one tenant. Its state is folded from a flow event
stream that is separate from the loop-safety stream. A loop-safety ``reset``
truncates the loop fold and must never lower a flow label, so the flow fold
has no reset at all.

Every writer goes through ``append_if(expected_seq, event)``. The event lands
only when the stream's last sequence is ``expected_seq``; concurrent writers
with the same ``expected_seq`` get exactly one winner. This holds on every
backend the loop-safety store admits: in-process, SQLite, Postgres and the D1
state endpoint.

Events: ``fork`` (the first event of every context; a root context is a fork
of nothing), ``raise`` (the label rises to the join), ``charge`` (bits charged
to the budget ledger, which lives on the root context's stream) and
``declassify`` (recorded; IFC-07/08 give it meaning). The label only rises.
No API lowers it, and ending a context is the only way out of its label.

The model provider is a principal (§3.2.1). At mint, the context's
processors (``model_principal`` and ``q_principal``) must be authorized for
the tenant's data by the deployment's processing policy, or the mint is
refused with ``processing_not_authorized``. Afterwards every raise keeps the
invariant ``flows_to(label, model_principal)``; a raise that would break it
is a bug in the caller and raises :class:`FlowInvariantViolation`.
"""
from __future__ import annotations

import base64
import contextlib
import json
import secrets
import time
import threading
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

from remora.capabilities.resource import ResourceRefused, canonical_resource, resource_within
from remora.errors import RemoraError
from remora.flow.label import (
    BOTTOM,
    PUBLIC,
    Integrity,
    Label,
    canonical_bytes,
    flows_to,
    join,
)

__all__ = [
    "EVENT_KINDS",
    "FlowContextState",
    "FlowContextStore",
    "FlowContextUnknown",
    "FlowDispatchFenceLost",
    "FlowEvent",
    "FlowEventStore",
    "FlowInvariantViolation",
    "FlowStoreUnavailable",
    "DurableFlowEventStore",
    "InMemoryFlowEventStore",
    "OpenDispatch",
    "ProcessingNotAuthorized",
    "ProcessingPolicy",
    "fold",
    "label_from_payload",
    "label_payload",
    "new_context_id",
]

#: ``dispatch`` and ``dispatch_end`` are the dispatch fence (IFC-06): a call
#: holds the context from the moment its flow decision is re-checked until
#: its result is committed, so a second call in the same context refuses
#: before its tool runs instead of running and losing its result.
EVENT_KINDS: Final = frozenset({"fork", "raise", "charge", "declassify", "dispatch",
                                "dispatch_end"})
_MAX_RETRIES: Final = 16


class FlowStoreUnavailable(RemoraError, RuntimeError):
    """The flow store could not be reached or answered something unreadable.

    Never read as an empty history (A6): a caller that cannot learn a
    context's label must not proceed as if it were the bottom label.
    """

    code = "flow_state_unavailable"
    category = "governance"


class FlowContextUnknown(RemoraError, LookupError):
    """No such context for this tenant and principal."""

    code = "flow_context_unknown"
    category = "governance"


class FlowDispatchFenceLost(RemoraError, RuntimeError):
    """The dispatch fence a commit relies on is no longer held unexpired.

    Another proposal may have begun in the context while the hold had lapsed,
    so the holder's result must not become visible.
    """

    code = "flow_dispatch_fence_expired"
    category = "governance"


class ProcessingNotAuthorized(RemoraError, PermissionError):
    """A processor of the context may not read the tenant's data (§3.2.1)."""

    code = "processing_not_authorized"
    category = "governance"


class FlowInvariantViolation(RemoraError, RuntimeError):
    """A raise would put data in front of a provider that may not read it.

    A bug in the caller: by-value rendering is allowed only for fields the
    model provider may read, so a correct caller never asks for this raise.
    """

    code = "flow_invariant_violation"
    category = "governance"


# ── labels on the wire ──────────────────────────────────────────────────


def label_payload(label: Label) -> dict[str, Any]:
    """The label's canonical JSON object (the same bytes ``canonical_bytes`` hashes)."""
    return json.loads(canonical_bytes(label))


def label_from_payload(payload: Mapping[str, Any]) -> Label:
    if payload.get("v") != "remora/flow-label/v1":
        raise FlowStoreUnavailable("flow event carries an unknown label version")
    readers = payload.get("readers")
    integrity = Integrity(payload.get("integrity"))
    if readers == "PUBLIC":
        return Label(PUBLIC, integrity)
    if not isinstance(readers, list):
        raise FlowStoreUnavailable("flow event carries unreadable readers")
    return Label(readers, integrity)


# ── events and the fold ─────────────────────────────────────────────────


@dataclass(frozen=True)
class FlowEvent:
    kind: str
    payload: Mapping[str, Any]
    #: Random per event; the store reads it back to learn who won a race.
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    seq: int = 0

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown flow event kind {self.kind!r}")


@dataclass(frozen=True)
class OpenDispatch:
    """A call that re-checked its flow decision in this context and has not
    committed its result yet (IFC-06). ``expires_at`` is epoch seconds: a
    process that died mid-call must not hold the context forever."""

    dispatch_id: str
    proposal_id: str
    expires_at: float
    seq: int


@dataclass(frozen=True)
class FlowContextState:
    tenant_id: str
    context_id: str
    principal: str
    label: Label
    #: The sequence of the last raise (0 before the first).
    epoch: int
    #: The sequence of the last event of any kind; the next writer's expected_seq.
    seq: int
    root_context_id: str
    parent_context_id: str | None
    user_principal: str
    model_principal: str
    q_principal: str | None
    processors: frozenset[str]
    #: Charged bits per ledger key. Only the root context's stream carries charges.
    charged: Mapping[str, int] = field(default_factory=dict)
    declassifications: int = 0
    #: Dispatches that began and have not ended, in stream order (IFC-06).
    open_dispatches: tuple[OpenDispatch, ...] = ()

    def holding(self, now: float, *, proposal_id: str = "") -> OpenDispatch | None:
        """The unexpired open dispatch of another proposal, or None.

        The same proposal on another hop (the authority forwarding to the
        execution domain, which fences the same stream) does not contend
        with itself; an empty proposal id never matches anything.
        """
        for open_ in self.open_dispatches:
            if open_.expires_at <= now:
                continue
            if proposal_id and open_.proposal_id == proposal_id:
                continue
            return open_
        return None


def fold(tenant_id: str, context_id: str, events: Sequence[FlowEvent]) -> FlowContextState:
    """Fold a context's stream. There is no reset; the label only rises."""
    if not events:
        raise FlowContextUnknown("no such flow context")
    first = events[0]
    if first.kind != "fork" or first.seq != 1:
        raise FlowStoreUnavailable("flow stream does not start with its fork event")
    p = first.payload
    try:
        state = FlowContextState(
            tenant_id=tenant_id, context_id=context_id, principal=str(p["principal"]),
            label=label_from_payload(p["label"]), epoch=0, seq=1,
            root_context_id=str(p["root_context_id"]),
            parent_context_id=p.get("parent_context_id"),
            user_principal=str(p["user_principal"]), model_principal=str(p["model_principal"]),
            q_principal=p.get("q_principal"),
            processors=frozenset(str(x) for x in p["processors"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FlowStoreUnavailable(f"unreadable fork event: {exc}") from exc
    label, epoch, charged, declassified = state.label, 0, dict(state.charged), 0
    open_: dict[str, OpenDispatch] = {}
    last = 1
    for event in events[1:]:
        if event.seq != last + 1:
            raise FlowStoreUnavailable("flow stream has a gap or a reordering")
        last = event.seq
        if event.kind == "raise":
            label = join(label, label_from_payload(event.payload["label"]))
            epoch = event.seq
        elif event.kind == "charge":
            key = str(event.payload["key"])
            charged[key] = charged.get(key, 0) + int(event.payload["bits"])
        elif event.kind == "declassify":
            declassified += 1
        elif event.kind == "dispatch":
            try:
                open_[str(event.payload["dispatch_id"])] = OpenDispatch(
                    dispatch_id=str(event.payload["dispatch_id"]),
                    proposal_id=str(event.payload.get("proposal_id", "")),
                    expires_at=float(event.payload["expires_at"]), seq=event.seq)
            except (KeyError, TypeError, ValueError) as exc:
                raise FlowStoreUnavailable(f"unreadable dispatch event: {exc}") from exc
        elif event.kind == "dispatch_end":
            open_.pop(str(event.payload.get("dispatch_id", "")), None)
        else:
            raise FlowStoreUnavailable("a fork event inside a stream")
    return FlowContextState(
        tenant_id=state.tenant_id, context_id=state.context_id, principal=state.principal,
        label=label, epoch=epoch, seq=last, root_context_id=state.root_context_id,
        parent_context_id=state.parent_context_id, user_principal=state.user_principal,
        model_principal=state.model_principal, q_principal=state.q_principal,
        processors=state.processors, charged=charged, declassifications=declassified,
        open_dispatches=tuple(open_.values()))


# ── stores ──────────────────────────────────────────────────────────────


@runtime_checkable
class FlowEventStore(Protocol):
    """Append-only, tenant-scoped flow event streams with a conditional append."""

    def append_if(self, *, tenant_id: str, context_id: str, expected_seq: int,
                  event: FlowEvent) -> bool:
        """Append ``event`` as sequence ``expected_seq + 1`` iff the stream's last
        sequence is ``expected_seq``. True when this event landed, False when
        another did. Raises ``FlowStoreUnavailable`` when the outcome is unknown."""
        ...

    def events(self, *, tenant_id: str, context_id: str) -> list[FlowEvent]:
        """Every event of the stream in sequence order. Raises
        ``FlowStoreUnavailable``; never returns [] to mean unknown."""
        ...


def _require_scope(tenant_id: str, context_id: str) -> None:
    if not tenant_id or not tenant_id.strip():
        raise ValueError("flow state requires a tenant scope")
    if not context_id or not context_id.strip():
        raise ValueError("flow state requires a context_id")


class InMemoryFlowEventStore:
    """Process-local store with the durable store's semantics; never a fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: dict[tuple[str, str], list[FlowEvent]] = {}

    def append_if(self, *, tenant_id: str, context_id: str, expected_seq: int,
                  event: FlowEvent) -> bool:
        _require_scope(tenant_id, context_id)
        with self._lock:
            stream = self._streams.setdefault((tenant_id, context_id), [])
            if len(stream) != expected_seq:
                return False
            stream.append(FlowEvent(event.kind, dict(event.payload), event.event_id,
                                    expected_seq + 1))
            return True

    def events(self, *, tenant_id: str, context_id: str) -> list[FlowEvent]:
        _require_scope(tenant_id, context_id)
        with self._lock:
            return list(self._streams.get((tenant_id, context_id), ()))


class DurableFlowEventStore:
    """Flow streams over the loop-safety store's durable backends.

    Postgres (``dsn``), SQLite (``db_path``) or the D1 state endpoint
    (``state_endpoint``), in the table ``flow_events`` with the primary key
    ``(tenant_id, context_id, seq)``. ``append_if`` inserts only when the
    stream's maximum sequence is ``expected_seq`` and the key is free, then
    reads the row back: the event whose ``event_id`` sits at
    ``expected_seq + 1`` won. D1 batches writes and reports no row count, so
    the read-back is the one rule every backend follows.
    """

    def __init__(self, *, dsn: str = "", db_path: str = "", state_endpoint: str = "") -> None:
        if not (dsn or db_path or state_endpoint):
            raise ValueError("DurableFlowEventStore needs one of dsn, db_path or state_endpoint")
        from remora.persistence.sqlite_path import refuse_memory_db

        refuse_memory_db(db_path, what="flow event store")
        self._dsn, self._db_path, self._state_endpoint = dsn, db_path, state_endpoint
        self._ready = False

    def _connect(self) -> Any:
        if self._dsn:
            import psycopg
            return psycopg.connect(self._dsn)
        if self._db_path:
            return _closing_sqlite(self._db_path)
        from remora.persistence import d1_connection
        return d1_connection.connect(self._state_endpoint)

    def _p(self) -> str:
        return "%s" if self._dsn else "?"

    def _ensure_table(self, conn: Any) -> None:
        if self._ready:
            return
        conn.execute(
            "CREATE TABLE IF NOT EXISTS flow_events ("
            "tenant_id TEXT NOT NULL, context_id TEXT NOT NULL, seq INTEGER NOT NULL, "
            "kind TEXT NOT NULL, payload TEXT NOT NULL, event_id TEXT NOT NULL, "
            "recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (tenant_id, context_id, seq))")
        commit = getattr(conn, "commit", None)
        if commit is not None:
            commit()
        self._ready = True

    def _owner(self, tenant_id: str, context_id: str, seq: int) -> str | None:
        p = self._p()
        with self._connect() as conn:
            self._ensure_table(conn)
            row = conn.execute(
                f"SELECT event_id FROM flow_events WHERE tenant_id = {p} AND context_id = {p} "
                f"AND seq = {p}", (tenant_id, context_id, seq)).fetchone()
        return None if row is None else str(row[0])

    def append_if(self, *, tenant_id: str, context_id: str, expected_seq: int,
                  event: FlowEvent) -> bool:
        _require_scope(tenant_id, context_id)
        if expected_seq < 0:
            raise ValueError("expected_seq is non-negative")
        p = self._p()
        payload = json.dumps(dict(event.payload), sort_keys=True, separators=(",", ":"))
        sql = (
            "INSERT INTO flow_events (tenant_id, context_id, seq, kind, payload, event_id) "
            f"SELECT {p}, {p}, {p}, {p}, {p}, {p} WHERE "
            "(SELECT COALESCE(MAX(seq), 0) FROM flow_events "
            f"WHERE tenant_id = {p} AND context_id = {p}) = {p} "
            "ON CONFLICT DO NOTHING")
        params = (tenant_id, context_id, expected_seq + 1, event.kind, payload, event.event_id,
                  tenant_id, context_id, expected_seq)
        write_error: Exception | None = None
        try:
            with self._connect() as conn:
                self._ensure_table(conn)
                conn.execute(sql, params)
                commit = getattr(conn, "commit", None)
                if commit is not None:
                    commit()
        except Exception as exc:
            # The write may or may not have landed; the read-back decides.
            write_error = exc
        try:
            owner = self._owner(tenant_id, context_id, expected_seq + 1)
        except Exception as exc:
            raise FlowStoreUnavailable(f"flow store unreachable: {exc}") from exc
        if owner is None and write_error is not None:
            # Nobody holds the slot and our write failed: the store refused it
            # for a reason other than a lost race. That is unavailable, never
            # "another writer won", or every later append would quietly fail.
            raise FlowStoreUnavailable(f"flow store refused the write: {write_error}") from write_error
        return owner == event.event_id

    def events(self, *, tenant_id: str, context_id: str) -> list[FlowEvent]:
        _require_scope(tenant_id, context_id)
        p = self._p()
        try:
            with self._connect() as conn:
                self._ensure_table(conn)
                rows = conn.execute(
                    "SELECT seq, kind, payload, event_id FROM flow_events "
                    f"WHERE tenant_id = {p} AND context_id = {p} ORDER BY seq",
                    (tenant_id, context_id)).fetchall()
        except Exception as exc:
            raise FlowStoreUnavailable(f"flow store unreachable: {exc}") from exc
        try:
            return [FlowEvent(str(kind), json.loads(payload), str(event_id), int(seq))
                    for seq, kind, payload, event_id in rows]
        except (TypeError, ValueError) as exc:
            raise FlowStoreUnavailable(f"unreadable flow event: {exc}") from exc


@contextlib.contextmanager
def _closing_sqlite(path: str) -> Any:
    import sqlite3

    conn = sqlite3.connect(path, timeout=30)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ── processing authorization ────────────────────────────────────────────


@dataclass(frozen=True)
class ProcessingPolicy:
    """Which processors may read a tenant's data, per data class (§3.2.1).

    A signed part of the deployment's policy bundle in production; here a
    plain mapping ``{tenant: {data_class: [principal patterns]}}``. An empty
    policy authorizes nothing, so an unconfigured deployment cannot mint.
    """

    grants: Mapping[str, Mapping[str, frozenset[str]]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Mapping[str, Iterable[str]]]) -> ProcessingPolicy:
        from remora.capabilities.resource import canonical_resource_pattern
        return cls({str(t): {str(c): frozenset(canonical_resource_pattern(x) for x in v)
                             for c, v in classes.items()}
                    for t, classes in raw.items()})

    def authorized(self, tenant_id: str, principal: str, data_class: str = "default") -> bool:
        patterns = self.grants.get(tenant_id, {}).get(data_class, frozenset())
        return resource_within(principal, patterns)


# ── the context store ───────────────────────────────────────────────────


def new_context_id() -> str:
    """``ctx_`` + base32 of 128 random bits, lower case, unpadded."""
    return "ctx_" + base64.b32encode(secrets.token_bytes(16)).decode("ascii").rstrip("=").lower()


def _principal(raw: str, what: str) -> str:
    try:
        return canonical_resource(raw)
    except ResourceRefused as exc:
        raise ValueError(f"{what} is not a canonical principal: {exc}") from exc


class FlowContextStore:
    """Mint, fork, load, raise and charge flow contexts. Nothing lowers a label."""

    def __init__(self, store: FlowEventStore, policy: ProcessingPolicy) -> None:
        self._store = store
        self._policy = policy

    def _events(self, tenant_id: str, context_id: str) -> list[FlowEvent]:
        return self._store.events(tenant_id=tenant_id, context_id=context_id)

    def load(self, tenant_id: str, principal: str, context_id: str) -> FlowContextState:
        """The context's state; unknown, foreign-tenant and foreign-principal look alike."""
        state = fold(tenant_id, context_id, self._events(tenant_id, context_id))
        if state.principal != principal:
            raise FlowContextUnknown("no such flow context")
        return state

    def mint(self, tenant_id: str, principal: str, *, user_principal: str,
             model_principal: str, q_principal: str | None = None,
             parent_context_id: str | None = None,
             data_class: str = "default") -> FlowContextState:
        user = _principal(user_principal, "user_principal")
        model = _principal(model_principal, "model_principal")
        q = _principal(q_principal, "q_principal") if q_principal else None
        processors = frozenset(x for x in (model, q) if x)
        for proc in sorted(processors):
            if not self._policy.authorized(tenant_id, proc, data_class):
                raise ProcessingNotAuthorized(f"{proc} may not process {tenant_id}'s data")
        label, root, parent = BOTTOM, None, None
        if parent_context_id is not None:
            parent = self.load(tenant_id, principal, parent_context_id)
            label, root = parent.label, parent.root_context_id
            if not flows_to(label, model):
                raise ProcessingNotAuthorized(
                    "the child's model provider may not read the parent's data")
        for _ in range(_MAX_RETRIES):
            context_id = new_context_id()
            event = FlowEvent("fork", {
                "principal": principal, "label": label_payload(label),
                "root_context_id": root or context_id,
                "parent_context_id": parent_context_id,
                "user_principal": user, "model_principal": model, "q_principal": q,
                "processors": sorted(processors),
            })
            if self._store.append_if(tenant_id=tenant_id, context_id=context_id,
                                     expected_seq=0, event=event):
                return self.load(tenant_id, principal, context_id)
        raise FlowStoreUnavailable("could not mint a fresh context id")

    def fork(self, tenant_id: str, principal: str, parent_context_id: str, *,
             model_principal: str | None = None,
             q_principal: str | None = None) -> FlowContextState:
        parent = self.load(tenant_id, principal, parent_context_id)
        return self.mint(tenant_id, principal, user_principal=parent.user_principal,
                         model_principal=model_principal or parent.model_principal,
                         q_principal=q_principal if q_principal is not None else parent.q_principal,
                         parent_context_id=parent_context_id)

    def raise_label(self, tenant_id: str, principal: str, context_id: str,
                    label: Label, *, dispatch_id: str | None = None) -> FlowContextState:
        """Raise the context's label to its join with ``label`` (commit before return).

        With ``dispatch_id`` (the fence the caller holds, IFC-06) the commit
        is bound to that fence: the hold must be present and unexpired in the
        very state the append is conditioned on, so the append succeeds only
        if no event (a competing dispatch included) landed after that state.
        A label that needs no raise appends the hold's renewal instead, so
        the ownership check is a compare-and-swap in both cases. A hold that
        is gone or expired raises :class:`FlowDispatchFenceLost`.
        """
        for _ in range(_MAX_RETRIES):
            state = self.load(tenant_id, principal, context_id)
            held = None
            if dispatch_id is not None:
                at = time.time()
                held = next((o for o in state.open_dispatches
                             if o.dispatch_id == dispatch_id and o.expires_at > at), None)
                if held is None:
                    raise FlowDispatchFenceLost(
                        "the dispatch fence lapsed before the result was committed")
            new = join(state.label, label)
            if new == state.label:
                if held is None:
                    return state
                event = FlowEvent("dispatch", {
                    "dispatch_id": held.dispatch_id, "proposal_id": held.proposal_id,
                    "expires_at": held.expires_at})
            else:
                if not flows_to(new, state.model_principal):
                    raise FlowInvariantViolation(
                        "the raise would show data to a model provider that may not read it")
                event = FlowEvent("raise", {"label": label_payload(new)})
            if self._store.append_if(tenant_id=tenant_id, context_id=context_id,
                                     expected_seq=state.seq, event=event):
                return self.load(tenant_id, principal, context_id)
        raise FlowStoreUnavailable("flow label raise lost every retry under contention")

    def begin_dispatch(self, tenant_id: str, principal: str, context_id: str, *,
                       expected_seq: int, proposal_id: str, expires_at: float,
                       now: float) -> str | None:
        """Hold the context for one dispatch (IFC-06); None when another holds it.

        One attempt at ``expected_seq``, the sequence the caller's check read:
        a stream that moved since that read (a raise, another dispatch, a
        charge on a root context), a context held by an unexpired dispatch of
        another proposal, or an append lost to a concurrent writer is
        contention, and the caller refuses before its tool runs. Loading the
        context afresh and appending at that load's sequence would let a raise
        that landed after the check through, with the call dispatched on a
        verdict computed from the old label. The holder's expiry bounds a
        process that dies mid-call (the holder renews it while its tool runs,
        ``renew_dispatch``); an expired hold is ignored, not removed. Returns
        the dispatch id to end with.
        """
        state = self.load(tenant_id, principal, context_id)
        if state.seq != expected_seq:
            return None
        if state.holding(now, proposal_id=proposal_id) is not None:
            return None
        dispatch_id = uuid.uuid4().hex
        event = FlowEvent("dispatch", {"dispatch_id": dispatch_id, "proposal_id": proposal_id,
                                       "expires_at": float(expires_at)})
        if not self._store.append_if(tenant_id=tenant_id, context_id=context_id,
                                     expected_seq=expected_seq, event=event):
            return None
        return dispatch_id

    def renew_dispatch(self, tenant_id: str, principal: str, context_id: str,
                       dispatch_id: str, *, expires_at: float, now: float) -> bool:
        """Extend the hold ``begin_dispatch`` took to ``expires_at``; False when
        the hold is gone.

        The holder renews while its tool runs, so the expiry bounds a process
        that died mid-call and never a call that is still running. A hold that
        has ended or already expired is not revived: another proposal may have
        begun in the context since, and the holder's commit refuses instead.
        The renewal re-appends the hold's ``dispatch`` event with the later
        expiry, and the fold keeps the latest; retried under contention.
        """
        for _ in range(_MAX_RETRIES):
            state = self.load(tenant_id, principal, context_id)
            held = next((o for o in state.open_dispatches if o.dispatch_id == dispatch_id), None)
            if held is None or held.expires_at <= now:
                return False
            event = FlowEvent("dispatch", {
                "dispatch_id": dispatch_id, "proposal_id": held.proposal_id,
                "expires_at": max(float(expires_at), held.expires_at)})
            if self._store.append_if(tenant_id=tenant_id, context_id=context_id,
                                     expected_seq=state.seq, event=event):
                return True
        raise FlowStoreUnavailable("flow dispatch renewal lost every retry under contention")

    def end_dispatch(self, tenant_id: str, principal: str, context_id: str,
                     dispatch_id: str) -> None:
        """Release the hold ``begin_dispatch`` took; retried under contention."""
        for _ in range(_MAX_RETRIES):
            state = self.load(tenant_id, principal, context_id)
            if all(o.dispatch_id != dispatch_id for o in state.open_dispatches):
                return
            if self._store.append_if(tenant_id=tenant_id, context_id=context_id,
                                     expected_seq=state.seq,
                                     event=FlowEvent("dispatch_end",
                                                     {"dispatch_id": dispatch_id})):
                return
        raise FlowStoreUnavailable("flow dispatch release lost every retry under contention")

    def charge_budget(self, tenant_id: str, principal: str, context_id: str, *,
                      key: str, bits: int) -> int:
        """Charge ``bits`` to the root context's ledger under ``key``; returns the new total."""
        if bits < 0:
            raise ValueError("a charge is never negative")
        root = self.load(tenant_id, principal, context_id).root_context_id
        for _ in range(_MAX_RETRIES):
            ledger = self.load(tenant_id, principal, root)
            if self._store.append_if(tenant_id=tenant_id, context_id=root,
                                     expected_seq=ledger.seq,
                                     event=FlowEvent("charge", {"key": key, "bits": bits})):
                return self.load(tenant_id, principal, root).charged.get(key, 0)
        raise FlowStoreUnavailable("budget charge lost every retry under contention")

    def charged(self, tenant_id: str, principal: str, context_id: str, key: str) -> int:
        root = self.load(tenant_id, principal, context_id).root_context_id
        return self.load(tenant_id, principal, root).charged.get(key, 0)
