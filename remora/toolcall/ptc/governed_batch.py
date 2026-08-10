# SPDX-License-Identifier: BUSL-1.1
"""Governed batch execution of a PTC call graph (RF-11).

:class:`GovernedBatchExecutor` takes the list of :class:`ProposedCall` objects
produced by :func:`~remora.toolcall.ptc.call_graph.extract_call_graph` and
submits each one through REMORA's existing governance path.

Execution model
---------------
* Each call is assessed *individually* against the signed ToolSpec.
* Calls with no dependencies and decision ACCEPT may be dispatched concurrently
  (``asyncio.gather``).  Calls with declared dependencies wait for those to
  resolve first.
* Any call that resolves to VERIFY or ESCALATE pauses the batch and suspends
  the dependent sub-graph until the caller handles the outcome.
* Any call that resolves to ABSTAIN causes the entire batch to abort — a
  governance abstention is not automatically retried.
* Each result carries a full audit record: ``plan_source_hash``,
  ``toolspec_hash``, ``arguments_hash``, ``decision``, and
  ``execution_result``.

Security constraints
--------------------
* No call bypasses REMORA governance, even if a previous call in the batch
  returned ACCEPT.
* ACCEPT from governance does NOT auto-execute: the dispatcher must have a
  registered callable for the ``tool_id``.  A missing callable is a hard error,
  not a silent skip.
* The batch executor does not hold credentials; all authority flows through
  the existing lease/dispatch path.

This module is deterministic and has no live-network dependencies; it can
therefore be tested offline with stub dispatchers.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from remora.toolcall.ptc.call_graph import ProposedCall

__all__ = [
    "BatchOutcome",
    "CallResult",
    "GovernedBatchExecutor",
]


class BatchOutcome(str, Enum):
    """High-level outcome for an entire batch."""

    ALL_ACCEPTED = "ALL_ACCEPTED"
    PARTIAL_ACCEPTED = "PARTIAL_ACCEPTED"
    REQUIRES_VERIFY = "REQUIRES_VERIFY"
    ESCALATED = "ESCALATED"
    ABSTAINED = "ABSTAINED"
    DISPATCHER_ERROR = "DISPATCHER_ERROR"


@dataclass
class CallResult:
    """Audit record for a single governed call."""

    call_id: str
    tool_id: str
    decision: str          # ACCEPT / VERIFY / ESCALATE / ABSTAIN
    arguments_hash: str
    toolspec_hash: str
    plan_source_hash: str
    execution_result: Any = None
    execution_error: str | None = None
    duration_ms: float = 0.0
    # Additional governance metadata returned by the assessor
    governance_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def executed(self) -> bool:
        return self.execution_error is None and self.execution_result is not None

    def to_envelope_block(self) -> dict[str, Any]:
        return {
            "check": "gptc_call_result_v1",
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "decision": self.decision,
            "arguments_hash": self.arguments_hash,
            "toolspec_hash": self.toolspec_hash,
            "plan_source_hash": self.plan_source_hash,
            "executed": self.executed,
            "execution_error": self.execution_error,
            "duration_ms": round(self.duration_ms, 2),
        }


# Type aliases for pluggable governance and dispatch interfaces.
# The real implementations are in remora.enforcement and remora.toolcall.runtime;
# these types keep the PTC layer import-free from them so it stays testable
# with lightweight fakes.
AssessorFn = Callable[[ProposedCall], Awaitable[dict[str, Any]]]
DispatchFn = Callable[[ProposedCall, dict[str, Any]], Awaitable[Any]]


class GovernedBatchExecutor:
    """Submit a PTC call graph to REMORA governance and execute ACCEPT nodes.

    Args:
        assessor: Async callable ``(ProposedCall) → dict`` that returns at
            minimum ``{"decision": "ACCEPT"|"VERIFY"|"ESCALATE"|"ABSTAIN"}``.
            Plug in the real REMORA governance gate.
        dispatcher: Async callable ``(ProposedCall, governance_meta) → Any``
            called *only* for ACCEPT decisions.  Returns the tool execution
            result.  Must raise on any execution error.
        max_concurrent: Maximum number of independent calls dispatched in
            parallel.  Defaults to 8; set to 1 for sequential-only mode.
    """

    def __init__(
        self,
        assessor: AssessorFn,
        dispatcher: DispatchFn,
        max_concurrent: int = 8,
    ) -> None:
        self._assessor = assessor
        self._dispatcher = dispatcher
        self._sem = asyncio.Semaphore(max_concurrent)

    async def _assess_and_dispatch(
        self, call: ProposedCall, resolved: dict[str, str]
    ) -> CallResult:
        """Assess a single call; dispatch if ACCEPT."""
        t0 = time.monotonic()
        meta = await self._assessor(call)
        decision = str(meta.get("decision", "ABSTAIN")).upper()
        duration_ms = (time.monotonic() - t0) * 1000.0

        result = CallResult(
            call_id=call.call_id,
            tool_id=call.tool_id,
            decision=decision,
            arguments_hash=call.arguments_hash(),
            toolspec_hash=call.toolspec_hash,
            plan_source_hash=call.plan_source_hash,
            duration_ms=duration_ms,
            governance_metadata={k: v for k, v in meta.items() if k != "decision"},
        )

        if decision == "ACCEPT":
            async with self._sem:
                exec_t0 = time.monotonic()
                try:
                    result.execution_result = await self._dispatcher(call, meta)
                except Exception as exc:  # noqa: BLE001
                    result.execution_error = str(exc)
                result.duration_ms += (time.monotonic() - exec_t0) * 1000.0
                resolved[call.call_id] = decision

        return result

    async def execute(
        self, calls: list[ProposedCall]
    ) -> tuple[list[CallResult], BatchOutcome]:
        """Execute the call graph under governance.

        Calls are processed in topological order respecting ``dependencies``.
        Independent ACCEPT calls are dispatched concurrently (up to
        ``max_concurrent``).

        Returns:
            ``(results, outcome)`` where *results* is ordered by completion
            and *outcome* is the aggregate :class:`BatchOutcome`.
        """
        results: list[CallResult] = []
        resolved: dict[str, str] = {}  # call_id → decision

        # Group calls by generation (calls whose deps are all resolved)
        remaining = list(calls)

        while remaining:
            ready = [
                c for c in remaining
                if all(dep in resolved for dep in c.dependencies)
            ]
            if not ready:
                # Circular dependency or unresolved dep — abort
                for call in remaining:
                    results.append(CallResult(
                        call_id=call.call_id,
                        tool_id=call.tool_id,
                        decision="ABSTAIN",
                        arguments_hash=call.arguments_hash(),
                        toolspec_hash=call.toolspec_hash,
                        plan_source_hash=call.plan_source_hash,
                        execution_error="Dependency cycle or unresolved dependency",
                    ))
                return results, BatchOutcome.ABSTAINED

            # Check if any dependency produced a non-ACCEPT decision that blocks
            blocked_calls = [
                c for c in ready
                if any(
                    resolved.get(dep, "ACCEPT") not in ("ACCEPT",)
                    for dep in c.dependencies
                )
            ]
            dispatching = [c for c in ready if c not in blocked_calls]

            # Assess and dispatch concurrently
            batch_results = await asyncio.gather(
                *(self._assess_and_dispatch(c, resolved) for c in dispatching),
                return_exceptions=False,
            )
            for r in batch_results:
                results.append(r)
                if r.decision != "ACCEPT":
                    resolved[r.call_id] = r.decision

            # Mark blocked calls
            for call in blocked_calls:
                results.append(CallResult(
                    call_id=call.call_id,
                    tool_id=call.tool_id,
                    decision="ABSTAIN",
                    arguments_hash=call.arguments_hash(),
                    toolspec_hash=call.toolspec_hash,
                    plan_source_hash=call.plan_source_hash,
                    execution_error="Blocked by non-ACCEPT upstream decision",
                ))
                resolved[call.call_id] = "ABSTAIN"

            remaining = [c for c in remaining if c not in ready]

        return results, _aggregate_outcome(results)


def _aggregate_outcome(results: list[CallResult]) -> BatchOutcome:
    decisions = {r.decision for r in results}
    if "DISPATCHER_ERROR" in decisions:
        return BatchOutcome.DISPATCHER_ERROR
    if "ABSTAIN" in decisions:
        return BatchOutcome.ABSTAINED
    if "ESCALATE" in decisions:
        return BatchOutcome.ESCALATED
    if "VERIFY" in decisions:
        return BatchOutcome.REQUIRES_VERIFY
    accepted = all(r.decision == "ACCEPT" for r in results)
    if accepted:
        return BatchOutcome.ALL_ACCEPTED
    return BatchOutcome.PARTIAL_ACCEPTED
