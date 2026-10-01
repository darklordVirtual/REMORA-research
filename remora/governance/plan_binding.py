# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A plan cannot outlive the state it was built on (quality program Q7.5).

An agent reads state, builds a plan, and acts on it later. REMORA re-checks
the *call* immediately before dispatch: tool, arguments, tenant, target,
spec, task and resolved effect. It did not re-check the *premises*. A write
planned against revision 7 of a work order executed just as readily when the
work order was at revision 9, because nothing recorded that the plan had
read revision 7.

Chen, Wang and Brinton (2026), *Fresh Memory, Stale Plans: Derivation
Currency for Distributed LLM-Agent Memory* (arXiv:2609.03340, SHELF-032;
v1 was titled "Dependency-Scoped Validation ..."), make the case for validating a plan against
the specific state it depends on rather than against everything, so that a
change elsewhere does not invalidate it. This module takes that rule:

* a :class:`PlanBinding` records the revision of each piece of state the plan
  read, and which of those reads the write *depends on*;
* its digest is signed into the execution lease (``plan_binding_hash``);
* at dispatch the plan is presented again, checked against the signed
  digest, and every dependency is re-read. One that moved refuses as
  ``stale_plan``. A read the write does not depend on may move freely.

Fail closed throughout: a dependency whose revision cannot be read refuses as
``plan_state_unverifiable``, and a lease that names a plan refuses when no
plan, or a different one, is presented.

Scope: revisions come from a provider the deployment supplies; REMORA
compares them and never interprets them. Which reads a write depends on is
declared by whoever builds the plan, and an under-declared dependency is not
detected.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

__all__ = ["PlanBinding", "PlanCheck", "RevisionReader", "revalidate"]

#: ``resource -> current revision``. Raises when it cannot answer.
RevisionReader = Callable[[str], str]


@dataclass(frozen=True)
class PlanBinding:
    """The state a plan read, and the part of it this write depends on."""

    plan_id: str
    reads: tuple[tuple[str, str], ...]
    depends_on: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("a plan binding needs a plan_id")
        resources = [resource for resource, _ in self.reads]
        if len(set(resources)) != len(resources):
            raise ValueError("a plan binding records each resource once")
        unread = set(self.depends_on) - set(resources)
        if unread:
            # A dependency with no recorded revision could never be checked.
            raise ValueError(f"depends_on names resources the plan did not read: {sorted(unread)}")

    @classmethod
    def capture(cls, plan_id: str, resources: list[str], depends_on: list[str],
                read_revision: RevisionReader) -> "PlanBinding":
        """Record the current revision of each resource the plan read."""
        return cls(plan_id=plan_id,
                   reads=tuple(sorted((r, read_revision(r)) for r in set(resources))),
                   depends_on=tuple(sorted(set(depends_on))))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PlanBinding":
        reads = data.get("reads")
        if not isinstance(reads, Mapping):
            raise ValueError("plan.reads must map resource to revision")
        depends = data.get("depends_on", [])
        if not isinstance(depends, list):
            raise ValueError("plan.depends_on must be a list")
        return cls(plan_id=str(data.get("plan_id") or ""),
                   reads=tuple(sorted((str(k), str(v)) for k, v in reads.items())),
                   depends_on=tuple(sorted(str(d) for d in depends)))

    def digest(self) -> str:
        """SHA-256 over the canonical form. Signed into the lease."""
        canonical = json.dumps(
            {"depends_on": list(self.depends_on), "plan_id": self.plan_id,
             "reads": [[r, v] for r, v in self.reads]},
            sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class PlanCheck:
    """``refusal`` is None when the write may proceed."""

    refusal: str | None
    moved_dependencies: tuple[str, ...] = ()
    moved_other_reads: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()


def revalidate(plan: PlanBinding, read_revision: RevisionReader) -> PlanCheck:
    """Re-read every dependency and compare it with the recorded revision.

    Reads the write does not depend on are re-read too, so the result can
    say they moved, but they never cause a refusal.
    """
    moved_dependencies: list[str] = []
    moved_other: list[str] = []
    unreadable: list[str] = []
    for resource, revision in plan.reads:
        try:
            current = read_revision(resource)
        except Exception:  # noqa: BLE001 - unknown is not unchanged
            if resource in plan.depends_on:
                unreadable.append(resource)
            continue
        if current != revision:
            (moved_dependencies if resource in plan.depends_on else moved_other).append(resource)
    if unreadable:
        refusal: str | None = "plan_state_unverifiable"
    elif moved_dependencies:
        refusal = "stale_plan"
    else:
        refusal = None
    return PlanCheck(refusal, tuple(moved_dependencies), tuple(moved_other), tuple(unreadable))
