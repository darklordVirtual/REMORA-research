# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Procedure and completion are checked, not asserted (quality program Q7.7).

REMORA judges each call. A procedure is a property of the *sequence*: take a
backup before deleting, never write after the change window closed, file the
report once the work order is closed. No per-call gate can see those, and
"the task is complete" was whatever the caller said.

Three lines of work shape this module. Singh, Kumar, Agarwal et al. (2026),
*ContractEval* (arXiv:2609.09458, SHELF-035), match procedural obligations
against execution traces. Xiao and Nuzzo (2026), *Symbolic Temporal
Supervision of LLM Agents Using Contracts* (arXiv:2609.18128, SHELF-036),
supervise tool-call traces with temporal contracts. Smyth, Mantilla-Ramos,
Tikeng Notsawo et al. (2026), *Quantifying Overclaiming Propensity in
Frontier LLM Agents* (arXiv:2609.20812, SHELF-037), measure agents claiming
completion they did not reach. REMORA takes a deliberately small part: four
obligation shapes, each a finite automaton, not general temporal logic.

precedence(first, then)
    ``then`` may not happen unless ``first`` happened earlier. Safety:
    violated at the offending step.
absence(forbidden, after)
    ``forbidden`` may not happen (after ``after``, when given). Safety.
response(trigger, then)
    every ``trigger`` must eventually be followed by ``then``. Liveness:
    pending until met, and unmet at the end of a trace.
existence(required)
    ``required`` must happen at least once. Liveness.

One monitor serves both uses. Online, :meth:`ProcedureMonitor.admits` says
whether a proposed step would violate a safety obligation, before it runs,
and :meth:`ProcedureMonitor.step` records what did run. In replay,
:func:`replay` feeds a recorded trace through the same monitor, so the two
cannot disagree about what the contract means.

Completion is derived: :func:`derive_completion` returns ESTABLISHED only
when every obligation is satisfied and none was violated, VIOLATED when one
was, and NOT_ESTABLISHED otherwise. A caller's claim of completion is
compared with it, and a claim the trace does not establish is flagged as an
overclaim rather than recorded as fact.

Scope: steps are matched on tool name and exact argument fields; REMORA does
not interpret what a tool did beyond that. A contract is only as complete as
the obligations its author wrote.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

__all__ = [
    "CompletionStatus",
    "CompletionVerdict",
    "Obligation",
    "ProcedureContract",
    "ProcedureMonitor",
    "Step",
    "StepPattern",
    "absence",
    "derive_completion",
    "existence",
    "precedence",
    "replay",
    "response",
]


@dataclass(frozen=True)
class Step:
    """One executed tool call in a trace."""

    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class StepPattern:
    """Matches a step by tool name and, optionally, exact argument values."""

    tool_name: str
    where: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def matches(self, step: Step) -> bool:
        return step.tool_name == self.tool_name and all(
            step.arguments.get(k) == v for k, v in self.where.items())

    def __str__(self) -> str:
        if not self.where:
            return self.tool_name
        return self.tool_name + "(" + ",".join(
            f"{k}={v}" for k, v in sorted(self.where.items())) + ")"


def _pattern(value: str | StepPattern) -> StepPattern:
    return value if isinstance(value, StepPattern) else StepPattern(value)


@dataclass(frozen=True)
class Obligation:
    kind: str
    a: StepPattern
    b: StepPattern | None = None

    @property
    def name(self) -> str:
        return f"{self.kind}({self.a}" + (f", {self.b})" if self.b is not None else ")")


def precedence(first: str | StepPattern, then: str | StepPattern) -> Obligation:
    return Obligation("precedence", _pattern(first), _pattern(then))


def absence(forbidden: str | StepPattern, after: str | StepPattern | None = None) -> Obligation:
    return Obligation("absence", _pattern(forbidden), _pattern(after) if after else None)


def response(trigger: str | StepPattern, then: str | StepPattern) -> Obligation:
    return Obligation("response", _pattern(trigger), _pattern(then))


def existence(required: str | StepPattern) -> Obligation:
    return Obligation("existence", _pattern(required))


@dataclass(frozen=True)
class ProcedureContract:
    contract_id: str
    obligations: tuple[Obligation, ...]


class _State(str, Enum):
    """Per-obligation automaton state."""

    SATISFIED = "satisfied"
    PENDING = "pending"
    VIOLATED = "violated"


def _initial(ob: Obligation) -> _State:
    return _State.PENDING if ob.kind == "existence" else _State.SATISFIED


def _advance(ob: Obligation, state: _State, seen_a: bool, step: Step) -> tuple[_State, bool]:
    """One transition. ``seen_a`` is the automaton's single bit of memory."""
    if state is _State.VIOLATED:
        return state, seen_a
    if ob.kind in ("precedence", "response") and ob.b is None:
        raise ValueError(f"{ob.kind} needs a second step pattern")
    if ob.kind == "precedence" and ob.b is not None:
        if ob.b.matches(step) and not seen_a:
            return _State.VIOLATED, seen_a
        return state, seen_a or ob.a.matches(step)
    if ob.kind == "absence":
        active = seen_a or ob.b is None
        if active and ob.a.matches(step):
            return _State.VIOLATED, seen_a
        return state, seen_a or (ob.b is not None and ob.b.matches(step))
    if ob.kind == "response" and ob.b is not None:
        # A step matching both discharges nothing it has just raised.
        if ob.b.matches(step) and not ob.a.matches(step):
            return _State.SATISFIED, seen_a
        if ob.a.matches(step):
            return _State.PENDING, seen_a
        return state, seen_a
    if ob.kind == "existence":
        return (_State.SATISFIED if ob.a.matches(step) else state), seen_a
    raise ValueError(f"unknown obligation kind {ob.kind!r}")


class ProcedureMonitor:
    """The contract's automata, stepped over a trace one call at a time."""

    def __init__(self, contract: ProcedureContract) -> None:
        self.contract = contract
        self._states = [_initial(ob) for ob in contract.obligations]
        self._seen = [False] * len(contract.obligations)
        self._violations: list[tuple[int, str]] = []
        self._steps = 0

    def admits(self, step: Step) -> tuple[str, ...]:
        """The safety obligations ``step`` would violate if it ran now.

        Empty means it may run. Liveness obligations never block a step: a
        pending response is not violated until the trace ends.
        """
        refused = []
        for ob, state, seen in zip(self.contract.obligations, self._states, self._seen,
                                   strict=True):
            if ob.kind in ("precedence", "absence") and state is not _State.VIOLATED:
                if _advance(ob, state, seen, step)[0] is _State.VIOLATED:
                    refused.append(ob.name)
        return tuple(refused)

    def step(self, step: Step) -> tuple[str, ...]:
        """Record an executed step; returns the obligations it violated."""
        newly: list[str] = []
        for i, ob in enumerate(self.contract.obligations):
            before = self._states[i]
            self._states[i], self._seen[i] = _advance(ob, before, self._seen[i], step)
            if self._states[i] is _State.VIOLATED and before is not _State.VIOLATED:
                newly.append(ob.name)
                self._violations.append((self._steps, ob.name))
        self._steps += 1
        return tuple(newly)

    @property
    def violations(self) -> tuple[tuple[int, str], ...]:
        """``(step index, obligation)`` for every violation, in order."""
        return tuple(self._violations)

    def pending(self) -> tuple[str, ...]:
        return tuple(ob.name for ob, s in zip(self.contract.obligations, self._states,
                                              strict=True) if s is _State.PENDING)

    def satisfied(self) -> tuple[str, ...]:
        return tuple(ob.name for ob, s in zip(self.contract.obligations, self._states,
                                              strict=True) if s is _State.SATISFIED)


def replay(contract: ProcedureContract, trace: Sequence[Step]) -> ProcedureMonitor:
    """The monitor after ``trace``: the same automata the online path uses."""
    monitor = ProcedureMonitor(contract)
    for step in trace:
        monitor.step(step)
    return monitor


class CompletionStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    VIOLATED = "VIOLATED"


@dataclass(frozen=True)
class CompletionVerdict:
    contract_id: str
    status: CompletionStatus
    satisfied: tuple[str, ...]
    pending: tuple[str, ...]
    violations: tuple[tuple[int, str], ...]
    #: True when the caller claimed completion and the trace does not
    #: establish it. None when no claim was made.
    overclaim: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {"contract_id": self.contract_id, "status": self.status.value,
                "satisfied": list(self.satisfied), "pending": list(self.pending),
                "violations": [list(v) for v in self.violations],
                "overclaim": self.overclaim}


def derive_completion(contract: ProcedureContract, trace: Sequence[Step], *,
                      claimed_complete: bool | None = None) -> CompletionVerdict:
    """Completion as the trace establishes it, never as the caller states it."""
    monitor = replay(contract, trace)
    if monitor.violations:
        status = CompletionStatus.VIOLATED
    elif monitor.pending():
        status = CompletionStatus.NOT_ESTABLISHED
    else:
        status = CompletionStatus.ESTABLISHED
    overclaim = None if claimed_complete is None else (
        claimed_complete and status is not CompletionStatus.ESTABLISHED)
    return CompletionVerdict(contract.contract_id, status, monitor.satisfied(),
                             monitor.pending(), monitor.violations, overclaim)
