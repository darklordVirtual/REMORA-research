# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Loop safety state that does not decay between task iterations (Q7.2).

REMORA judges each call on its own. An agent that is denied, switches to
another tool, is denied again, and probes for authority it does not hold
presents a series of calls each of which is individually unremarkable.
Wu et al. (2026), *Safety Does Not Compose: Non-Decaying Loop State for
Autonomous LLM Agents* (arXiv:2608.27141), describe exactly this: monitors
scoped to one trajectory reset every iteration, so risk spread across
iterations stays under every threshold while it accumulates.

This module keeps that state across iterations. It does not implement the
paper's LoopHarness; it implements the part REMORA's design needs, the store
the state lives in and the rules for reading it
(``docs/design/task-bound-execution-authority-v1.md``, scope item 3).

keyed on the context, not the task
    State is keyed on ``(tenant_id, context_id)``. A new ``task_id`` inside
    the same context is a new iteration of the same loop, and must see what
    the earlier iterations accumulated. Starting a new task never resets it.
append-only
    Every observation appends one event. The state is a fold over the events
    since the last reset, so there is no update that could overwrite risk
    with a smaller number, and no delete.
reset only by policy
    ``reset`` appends a marker that must name the policy decision behind it.
    The events before it stay in the store. There is no other way to clear
    state: an agent that could reset its own history would reset it.
fail closed
    An unreachable store raises ``LoopSafetyStoreUnavailable``. Unknown is
    never reported as "nothing accumulated", or an outage becomes the way
    around the control; the revocation store follows the same rule.

The durable store follows ``remora/governance/revocation_store.py`` and uses
the backends the durability guard in ``servers/api.py`` admits.

Wired at ``POST /v1/execution/assess`` (``servers/execution_api.py``): read
before deciding, recorded after. The thresholds in ``LoopSafetyPolicy`` are
defaults, not calibrated values.
"""
from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from remora.errors import RemoraError
from remora.governance.task_identity import TaskIdentity

__all__ = [
    "AUTHORITY_PROBE",
    "DENIED_INTENT",
    "IRREVERSIBLE_EFFECT",
    "SIGNALS",
    "TOOL_SWITCH_AFTER_DENIAL",
    "DurableLoopSafetyStore",
    "InMemoryLoopSafetyStore",
    "LoopEvent",
    "LoopSafetyMonitor",
    "LoopSafetyPolicy",
    "LoopSafetyState",
    "LoopSafetyStore",
    "LoopSafetyStoreUnavailable",
    "LoopVerdict",
    "fold",
]

DENIED_INTENT = "denied_intent"
AUTHORITY_PROBE = "authority_probe"
TOOL_SWITCH_AFTER_DENIAL = "tool_switch_after_denial"
IRREVERSIBLE_EFFECT = "irreversible_effect"
#: The signals a single call cannot see and a context can.
SIGNALS = (DENIED_INTENT, AUTHORITY_PROBE, TOOL_SWITCH_AFTER_DENIAL, IRREVERSIBLE_EFFECT)
#: The marker a policy reset appends. Not a signal: it ends the fold.
_RESET = "reset"


class LoopSafetyStoreUnavailable(RemoraError, RuntimeError):
    """The store could not be reached or could not answer.

    Never read as an empty history. A caller that cannot learn what a context
    accumulated must not proceed as if it accumulated nothing.
    """

    code = "loop_safety_store_unavailable"
    category = "governance"


@dataclass(frozen=True)
class LoopEvent:
    """One observation in a context, in store order.

    ``signals`` is empty for a call that raised nothing; it is still recorded,
    because whether a denial was followed by a different tool depends on
    what came immediately after it.
    """

    seq: int
    task_id: str
    tool_name: str
    signals: tuple[str, ...]
    detail: str = ""


@dataclass(frozen=True)
class LoopSafetyState:
    """What a context has accumulated since its last policy reset."""

    tenant_id: str
    context_id: str
    counts: Mapping[str, int]
    #: Tasks seen since the last reset, in first-seen order.
    tasks: tuple[str, ...]
    #: The tool of the most recent event when that event was a denial, else
    #: None. A following call to a different tool is a switch after denial.
    last_denied_tool: str | None
    events_since_reset: int

    def count(self, signal: str) -> int:
        return self.counts.get(signal, 0)


def fold(tenant_id: str, context_id: str, events: Sequence[LoopEvent]) -> LoopSafetyState:
    """The state after ``events``, which are in store order.

    Only the events after the last reset count. Pure, so every store reads
    state the same way and the rule is testable without one.
    """
    start = 0
    for index, event in enumerate(events):
        if _RESET in event.signals:
            start = index + 1
    live = events[start:]
    counts = {signal: 0 for signal in SIGNALS}
    tasks: list[str] = []
    for event in live:
        for signal in event.signals:
            if signal in counts:
                counts[signal] += 1
        if event.task_id and event.task_id not in tasks:
            tasks.append(event.task_id)
    last = live[-1] if live else None
    return LoopSafetyState(
        tenant_id=tenant_id,
        context_id=context_id,
        counts=MappingProxyType(counts),
        tasks=tuple(tasks),
        last_denied_tool=(
            last.tool_name if last is not None and DENIED_INTENT in last.signals else None
        ),
        events_since_reset=len(live),
    )


@runtime_checkable
class LoopSafetyStore(Protocol):
    """Append-only, tenant-scoped event log keyed on the context."""

    def append(self, *, tenant_id: str, context_id: str, task_id: str,
               tool_name: str, signals: tuple[str, ...], detail: str = "") -> None:
        """Append one event. Raises ``LoopSafetyStoreUnavailable`` when the
        outcome is unknown, so a caller is never told it was recorded when it
        may not have been."""
        ...

    def events(self, *, tenant_id: str, context_id: str) -> list[LoopEvent]:
        """Every event of the context in store order. Raises
        ``LoopSafetyStoreUnavailable``; never returns [] to mean unknown."""
        ...


class InMemoryLoopSafetyStore:
    """Process-local store with the durable store's semantics.

    For library and research use and as the control in the durability
    tests. Not a fallback: falling back to it when a durable backend fails
    would forget the history the control exists to keep.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], list[LoopEvent]] = {}
        self._seq = 0

    def append(self, *, tenant_id: str, context_id: str, task_id: str,
               tool_name: str, signals: tuple[str, ...], detail: str = "") -> None:
        _require_scope(tenant_id, context_id)
        with self._lock:
            self._seq += 1
            self._events.setdefault((tenant_id, context_id), []).append(
                LoopEvent(self._seq, task_id, tool_name, tuple(signals), detail))

    def events(self, *, tenant_id: str, context_id: str) -> list[LoopEvent]:
        _require_scope(tenant_id, context_id)
        with self._lock:
            return list(self._events.get((tenant_id, context_id), ()))


class DurableLoopSafetyStore:
    """The event log over REMORA's durable state backends.

    The same three the durability guard in ``servers/api.py`` admits, for the
    reason ``revocation_store.py`` records: a backend the guard accepts and
    the consumer never learned to use is how that defect class recurs.
    """

    def __init__(self, *, dsn: str = "", db_path: str = "",
                 state_endpoint: str = "") -> None:
        if not (dsn or db_path or state_endpoint):
            raise ValueError(
                "DurableLoopSafetyStore needs one of dsn, db_path or "
                "state_endpoint; an unconfigured durable store would be an "
                "in-memory store wearing the durable name"
            )
        from remora.persistence.sqlite_path import refuse_memory_db

        refuse_memory_db(db_path, what="loop safety store")
        self._dsn = dsn
        self._db_path = db_path
        self._state_endpoint = state_endpoint
        self._ready = False

    def _connect(self) -> Any:
        if self._dsn:
            import psycopg
            return psycopg.connect(self._dsn)
        if self._db_path:
            import sqlite3
            return sqlite3.connect(self._db_path)
        from remora.persistence import d1_connection
        return d1_connection.connect(self._state_endpoint)

    def _placeholder(self) -> str:
        return "%s" if self._dsn else "?"

    def _ensure_table(self, conn: Any) -> None:
        if self._ready:
            return
        # The sequence is the store's, not the caller's: event order decides
        # whether a call followed a denial, so a clock would not do.
        seq = "BIGSERIAL PRIMARY KEY" if self._dsn else "INTEGER PRIMARY KEY AUTOINCREMENT"
        conn.execute(
            "CREATE TABLE IF NOT EXISTS loop_safety_events ("
            f"seq {seq}, tenant_id TEXT NOT NULL, context_id TEXT NOT NULL, "
            "task_id TEXT NOT NULL DEFAULT '', tool_name TEXT NOT NULL DEFAULT '', "
            "signals TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', "
            "recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        commit = getattr(conn, "commit", None)
        if commit is not None:
            commit()
        self._ready = True

    def append(self, *, tenant_id: str, context_id: str, task_id: str,
               tool_name: str, signals: tuple[str, ...], detail: str = "") -> None:
        _require_scope(tenant_id, context_id)
        p = self._placeholder()
        sql = (
            "INSERT INTO loop_safety_events "
            "(tenant_id, context_id, task_id, tool_name, signals, detail) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})"
        )
        try:
            with self._connect() as conn:
                self._ensure_table(conn)
                conn.execute(sql, (tenant_id, context_id, task_id, tool_name,
                                   ",".join(signals), detail))
                commit = getattr(conn, "commit", None)
                if commit is not None:
                    commit()
        except Exception as exc:  # noqa: BLE001 - the outcome is unknown
            raise LoopSafetyStoreUnavailable(f"loop safety store unreachable: {exc}") from exc

    def events(self, *, tenant_id: str, context_id: str) -> list[LoopEvent]:
        _require_scope(tenant_id, context_id)
        p = self._placeholder()
        sql = (
            "SELECT seq, task_id, tool_name, signals, detail FROM loop_safety_events "
            f"WHERE tenant_id = {p} AND context_id = {p} ORDER BY seq"
        )
        try:
            with self._connect() as conn:
                self._ensure_table(conn)
                rows = conn.execute(sql, (tenant_id, context_id)).fetchall()
        except Exception as exc:  # noqa: BLE001 - never read as an empty history
            raise LoopSafetyStoreUnavailable(f"loop safety store unreachable: {exc}") from exc
        return [
            LoopEvent(int(seq), task_id, tool_name,
                      tuple(s for s in str(signals).split(",") if s), detail)
            for seq, task_id, tool_name, signals, detail in rows
        ]


@dataclass(frozen=True)
class LoopSafetyPolicy:
    """Per-signal limits within one context. None means no limit.

    The defaults are a starting point, not calibrated values: no REMORA
    study has measured where these thresholds should sit.
    """

    limits: Mapping[str, int | None] = field(default_factory=lambda: MappingProxyType({
        DENIED_INTENT: 3,
        AUTHORITY_PROBE: 1,
        TOOL_SWITCH_AFTER_DENIAL: 2,
        IRREVERSIBLE_EFFECT: None,
    }))

    def assess(self, state: LoopSafetyState) -> LoopVerdict:
        """ESCALATE when any signal has reached its limit, else CONTINUE."""
        reached = tuple(
            signal for signal in SIGNALS
            if (limit := self.limits.get(signal)) is not None and state.count(signal) >= limit
        )
        return LoopVerdict("escalate" if reached else "continue", reached, state)


@dataclass(frozen=True)
class LoopVerdict:
    action: str
    reached: tuple[str, ...]
    state: LoopSafetyState


class LoopSafetyMonitor:
    """Records what each call contributes to its context and reads it back."""

    def __init__(self, store: LoopSafetyStore, *,
                 policy: LoopSafetyPolicy | None = None) -> None:
        self._store = store
        self._policy = policy or LoopSafetyPolicy()

    def state(self, tenant_id: str, context_id: str) -> LoopSafetyState:
        return fold(tenant_id, context_id,
                    self._store.events(tenant_id=tenant_id, context_id=context_id))

    def observe(self, tenant_id: str, task: TaskIdentity, tool_name: str, *,
                denied: bool, authority_probe: bool = False,
                irreversible: bool = False) -> LoopVerdict:
        """Record one decided call and return the context's verdict after it.

        A call to a different tool immediately after a denial is recorded as
        a switch after denial. The history is read before the append, and a
        store that cannot answer raises before anything is recorded.
        """
        before = self.state(tenant_id, task.context_id)
        signals: list[str] = []
        if denied:
            signals.append(DENIED_INTENT)
        if authority_probe:
            signals.append(AUTHORITY_PROBE)
        if before.last_denied_tool is not None and tool_name != before.last_denied_tool:
            signals.append(TOOL_SWITCH_AFTER_DENIAL)
        if irreversible and not denied:
            signals.append(IRREVERSIBLE_EFFECT)
        self._store.append(tenant_id=tenant_id, context_id=task.context_id,
                           task_id=task.task_id, tool_name=tool_name,
                           signals=tuple(signals))
        return self._policy.assess(self.state(tenant_id, task.context_id))

    def assess(self, tenant_id: str, context_id: str) -> LoopVerdict:
        return self._policy.assess(self.state(tenant_id, context_id))

    def reset(self, tenant_id: str, context_id: str, *, policy_ref: str,
              reason: str = "") -> None:
        """Start the context's count again, under a named policy decision.

        The earlier events stay in the store. ``policy_ref`` names the policy
        decision that authorised the reset (a decision or envelope id); an
        empty one is refused, so a reset cannot be issued anonymously.
        """
        if not policy_ref or not policy_ref.strip():
            raise ValueError("a loop safety reset must name the policy decision behind it")
        detail = f"policy_ref={policy_ref.strip()}"
        if reason:
            detail += f"; reason={reason}"
        self._store.append(tenant_id=tenant_id, context_id=context_id, task_id="",
                           tool_name="", signals=(_RESET,), detail=detail)


def _require_scope(tenant_id: str, context_id: str) -> None:
    if not tenant_id or not tenant_id.strip():
        # An empty tenant would pool every unattributed context into one
        # namespace, so one tenant's history would count against another's.
        raise ValueError("loop safety state requires a tenant scope")
    if not context_id or not context_id.strip():
        raise ValueError("loop safety state requires a context_id")
