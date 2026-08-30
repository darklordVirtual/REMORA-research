# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The task an authorization was granted under.

REMORA binds an authorization to the exact call it was granted for: tool
name, full arguments, tenant and target, recomputed immediately before
dispatch. It did not bind it to the *task* the call was made under. An
approval granted for task A therefore authorised the identical call under
task B, with every binding REMORA checks still holding, and nothing in the
chain recording that the approver had been answering a different question.

Three independent lines arrived at this within two days.

The AGNTCY Identity working group's 2026-08-25 analysis states that Identity
plus TBAC grants *standing* authority today, and that cryptographic binding
to taskId, action and resource scope, lifetime and delegation constraints is
still open work on a task-authorization profile.

A row-by-row crosswalk of that work against implemented REMORA returned GAP
on exactly two rows: A2A taskId and A2A contextId.

And the human-subject evidence. Yan (2026), *Do User-Authored Permission
Policies Improve Protection Against AI Agent Overreach?* (arXiv:2608.27443),
found across 113 non-technical participants that a reusable-policy setup
blocked FEWER overreach attempts than either real-time human approval or
automated model review, because users chose "ask" and then approved actions
outside the original task. "The user approved" is measurably not the same as
"the task authorised", which is the property this module exists to carry.

The adjacent failure is Wu et al. (2026), *Safety Does Not Compose:
Non-Decaying Loop State for Autonomous LLM Agents* (arXiv:2608.27141):
trajectory-scoped monitors reset each iteration, so signals distributed
across iterations stay under threshold individually while risk accumulates.
Their LoopHarness keeps safety state across the outer loop. That state needs
a key, and the key is ``context_id`` below, which is why the two designs
share this module rather than growing a second task identity beside it.

Two identities, matching A2A's own vocabulary so that a REMORA record can be
crosswalked against that profile rather than needing a translation table:

context_id
    the longer-lived identity. One agent conversation or delegation context.
    This is also the key the non-decaying loop safety state is stored under
    (``remora/governance/loop_safety.py``), because risk that accumulates
    across iterations accumulates within exactly this scope.
task_id
    one unit of work inside a context. An authorization is bound to this.

Both are opaque to REMORA. It compares them and never parses them: a
deployment that encodes structure in its task ids must not find that
structure load-bearing here.

**The serialisation rule is load-bearing.** An absent identity is omitted
from a signable payload rather than serialised as null. Every signed
structure this feeds already has issued signatures that a verifier
recomputes, and a field appearing in the preimage would invalidate all of
them. An envelope carrying no task identity must produce byte-identical
bytes to one issued before this module existed. See
``docs/superpowers/specs/2026-08-30-task-bound-execution-authority-design.md``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from remora.errors import RemoraError

__all__ = [
    "TaskIdentity",
    "TaskIdentityMismatch",
    "merge_task_fields",
    "task_fields",
]


class TaskIdentityMismatch(RemoraError):
    """Two structures in one authorization named different tasks.

    Deliberately distinct from "no task was bound". A caller must be able to
    tell an unbound authorization from one bound to a different task: the
    first is a configuration gap, the second is an authorization being
    replayed into a context it was never granted for.
    """

    code = "task_mismatch"
    category = "enforcement"


@dataclass(frozen=True)
class TaskIdentity:
    """The task and context an authorization was granted under.

    Both halves are required together. A task id with no context is not a
    narrower binding, it is an ambiguous one: task ids are only unique
    within a context, so accepting a bare task id would let two contexts
    collide on the same authorization.
    """

    context_id: str
    task_id: str

    def __post_init__(self) -> None:
        for name in ("context_id", "task_id"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string, got {type(value).__name__}")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
            # A whitespace-padded id would compare unequal to its own trimmed
            # form, which is a mismatch that looks like a mismatch of tasks.
            if value != value.strip():
                raise ValueError(f"{name} must not carry leading or trailing space")

    @classmethod
    def from_fields(cls, data: Any) -> "TaskIdentity | None":
        """Read an identity from a mapping, or None when it carries neither.

        A mapping carrying exactly one half is an error rather than a
        partial identity: silently dropping the half that was supplied would
        turn a caller's binding attempt into no binding at all.
        """
        if not isinstance(data, dict):
            return None
        context_id = data.get("context_id")
        task_id = data.get("task_id")
        if context_id is None and task_id is None:
            return None
        if context_id is None or task_id is None:
            raise ValueError(
                "a task identity needs both context_id and task_id; "
                f"got context_id={context_id!r} task_id={task_id!r}"
            )
        return cls(context_id=context_id, task_id=task_id)

    def matches(self, other: "TaskIdentity | None") -> bool:
        """Exact equality on both halves. None never matches."""
        return other is not None and (
            self.context_id == other.context_id and self.task_id == other.task_id
        )

    def differences(self, other: "TaskIdentity | None") -> tuple[str, ...]:
        """Which halves disagree, for a refusal that says what was wrong."""
        if other is None:
            return ("task_unbound",)
        out = []
        if self.context_id != other.context_id:
            out.append("context_id")
        if self.task_id != other.task_id:
            out.append("task_id")
        return tuple(out)


def task_fields(identity: "TaskIdentity | None") -> dict[str, str]:
    """The identity as signable fields, or an empty mapping when absent.

    Empty rather than ``{"context_id": None, "task_id": None}``: the caller
    folds this into a signable payload, and a null-valued key changes the
    preimage exactly as much as a populated one would. Returning nothing is
    what keeps signatures issued before this module still verifiable.
    """
    if identity is None:
        return {}
    return {"context_id": identity.context_id, "task_id": identity.task_id}


def merge_task_fields(payload: dict[str, Any],
                      identity: "TaskIdentity | None") -> dict[str, Any]:
    """Fold an identity into a signable payload, omitting it when absent.

    Refuses to overwrite an identity already present in the payload. A
    silent overwrite here would let a later layer rebind an authorization to
    a different task, which is the exact thing this design refuses to allow
    across structures.
    """
    fields = task_fields(identity)
    for key, value in fields.items():
        existing = payload.get(key)
        if existing is not None and existing != value:
            raise TaskIdentityMismatch(
                f"payload already carries {key}={existing!r}; "
                f"refusing to rebind it to {value!r}"
            )
    return {**payload, **fields}
