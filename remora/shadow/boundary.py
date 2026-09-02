# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Boundary report: what-if analysis over a whole shadow-mode action log.

Shadow mode (``remora.shadow.replay``) says what REMORA would have decided
for each historical action. This module asks the follow-up question for the
whole log at once: of the actions that would have been blocked, how many
could a model's confidence have lifted, how many could the agent have lifted
by changing its own proposal, and how many need a fact only the deployment
can declare? The per-record engine is :func:`remora.policy.whatif.what_if`;
this module only maps records to observations, runs it, and aggregates.

The aggregate is the number a pilot partner reads first. If any blocked
action in their log is liftable by model signals alone, that is a finding
about the policy configuration, not a statistic to average away, so the
report lists those records individually. The most common first lever across
minimal paths says which deployment declaration would unblock the most
legitimate work.

Bounds per record are the same as for a single call and are recorded in the
report. Analysing a large log at full depth is slow (tens of thousands of
engine calls per record); ``max_depth=2`` is the default here because the
questions above are answered by the sub-space searches, which are cheap, and
the minimal paths are secondary.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from remora.policy import PolicyObservation, RemoraDecisionEngine
from remora.policy.report import DecisionAction
from remora.policy.whatif import LeverKind, WhatIfReport, what_if
from remora.shadow.replay import _load_jsonl, _record_to_observation


@dataclass(frozen=True)
class RecordBoundary:
    """One log record's verdict and the what-if answer for it."""

    index: int
    question: str
    action: DecisionAction
    report: WhatIfReport

    @property
    def blocked(self) -> bool:
        return self.action is not DecisionAction.ACCEPT

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "question": self.question,
            "action": self.action.value,
            "what_if": self.report.to_dict(),
        }


@dataclass(frozen=True)
class BoundaryReport:
    """Aggregate of :class:`RecordBoundary` over one action log."""

    target: DecisionAction
    records: tuple[RecordBoundary, ...]
    max_depth: int
    max_evaluations: int

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def blocked(self) -> tuple[RecordBoundary, ...]:
        return tuple(r for r in self.records if not r.report.already_at_target)

    @property
    def liftable_by_model_signals(self) -> tuple[RecordBoundary, ...]:
        return tuple(r for r in self.blocked if r.report.model_signals_alone is not None)

    @property
    def liftable_by_agent_alone(self) -> tuple[RecordBoundary, ...]:
        return tuple(r for r in self.blocked if r.report.without_deployment is not None)

    @property
    def needing_deployment_facts(self) -> tuple[RecordBoundary, ...]:
        return tuple(r for r in self.blocked if r.report.deployment_facts_required)

    @property
    def unreachable_within_bound(self) -> tuple[RecordBoundary, ...]:
        return tuple(r for r in self.blocked if not r.report.reachable)

    @property
    def hard_guarded(self) -> tuple[RecordBoundary, ...]:
        return tuple(r for r in self.blocked if r.report.hard_guard)

    def lever_frequency(self) -> dict[str, int]:
        """How often each lever appears in a minimal path, over blocked records.

        A record with several minimal paths contributes once per lever, so a
        lever that appears in every alternative for a record counts once for
        that record.
        """
        counter: Counter[str] = Counter()
        for r in self.blocked:
            levers = {name for p in r.report.minimal_paths for name in p.levers}
            counter.update(levers)
        return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))

    def kind_frequency(self) -> dict[str, int]:
        """How many blocked records have at least one minimal path needing each kind."""
        counter: Counter[str] = Counter()
        for r in self.blocked:
            kinds = {k.value for p in r.report.minimal_paths for k in p.kinds}
            counter.update(kinds)
        return {k.value: counter.get(k.value, 0) for k in LeverKind}

    def verdict_counts(self) -> dict[str, int]:
        counter = Counter(r.action.value for r in self.records)
        return {a.value: counter.get(a.value, 0) for a in DecisionAction}

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.value,
            "total": self.total,
            "verdicts": self.verdict_counts(),
            "blocked": len(self.blocked),
            "liftable_by_model_signals": [r.index for r in self.liftable_by_model_signals],
            "liftable_by_agent_alone": [r.index for r in self.liftable_by_agent_alone],
            "needing_deployment_facts": [r.index for r in self.needing_deployment_facts],
            "unreachable_within_bound": [r.index for r in self.unreachable_within_bound],
            "hard_guarded": {r.index: r.report.hard_guard for r in self.hard_guarded},
            "lever_frequency": self.lever_frequency(),
            "kind_frequency": self.kind_frequency(),
            "search": {"max_depth": self.max_depth, "max_evaluations": self.max_evaluations},
            "records": [r.to_dict() for r in self.records],
        }

    def summary(self) -> str:
        t = self.target.value.upper()
        v = self.verdict_counts()
        lines = [
            f"{self.total} actions: " + ", ".join(f"{k} {n}" for k, n in v.items()),
            f"blocked (not {t}): {len(self.blocked)}",
            f"  liftable by model signals alone: {len(self.liftable_by_model_signals)}"
            + (" <- policy finding" if self.liftable_by_model_signals else ""),
            f"  liftable by the agent alone (proposal + model signals): "
            f"{len(self.liftable_by_agent_alone)}",
            f"  needing a deployment-declared fact: {len(self.needing_deployment_facts)}",
            f"  unreachable within {self.max_depth} changes: "
            f"{len(self.unreachable_within_bound)}",
            f"  stopped by a hard guard: {len(self.hard_guarded)}",
        ]
        freq = self.lever_frequency()
        if freq:
            top = list(freq.items())[:5]
            lines.append("most frequent levers in minimal paths: "
                         + ", ".join(f"{k} ({n})" for k, n in top))
        for r in self.liftable_by_model_signals:
            assert r.report.model_signals_alone is not None
            lines.append(
                f"  #{r.index} {r.question[:60]!r}: {r.action.value.upper()} -> {t} via "
                + " + ".join(r.report.model_signals_alone.levers))
        return "\n".join(lines)


def boundary_of_observations(
    observations: list[PolicyObservation],
    engine: RemoraDecisionEngine | None = None,
    *,
    target: DecisionAction = DecisionAction.ACCEPT,
    max_depth: int = 2,
    max_evaluations: int = 5_000,
) -> BoundaryReport:
    """Run :func:`what_if` over *observations* and aggregate."""
    engine = engine or RemoraDecisionEngine()
    records = []
    for i, obs in enumerate(observations):
        report = what_if(obs, engine, target=target, max_depth=max_depth,
                         max_evaluations=max_evaluations)
        records.append(RecordBoundary(index=i, question=obs.question,
                                      action=report.current_action, report=report))
    return BoundaryReport(target=target, records=tuple(records),
                          max_depth=max_depth, max_evaluations=max_evaluations)


def boundary_of_action_log(
    path: str,
    engine: RemoraDecisionEngine | None = None,
    *,
    target: DecisionAction = DecisionAction.ACCEPT,
    max_depth: int = 2,
    max_evaluations: int = 5_000,
) -> BoundaryReport:
    """Boundary report for a shadow-mode action-log JSONL file.

    Records are mapped to observations exactly as ``replay_action_log`` maps
    them, so the verdicts here are the shadow-replay verdicts.
    """
    observations = [_record_to_observation(rec) for rec in _load_jsonl(path)]
    return boundary_of_observations(observations, engine, target=target,
                                    max_depth=max_depth, max_evaluations=max_evaluations)


__all__ = [
    "BoundaryReport",
    "RecordBoundary",
    "boundary_of_action_log",
    "boundary_of_observations",
]
