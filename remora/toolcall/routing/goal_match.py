# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Does this call serve the user's goal? — the ``tool_matches_goal`` authority.

§21 named the gap, §34 measured it blind, §35 narrowed it and left a residue:
30 of 258 foreign calls still accepted because their argument values happened to
occur in the task. Value grounding asks *where did these values come from*. It
cannot ask *is this the right tool, acting on the right thing, with the right
effect* — and those are the questions the residue turns on.

``CallCompatibility.tool_matches_goal`` has been ``None`` since it was defined,
deliberately: the module docstring there says a guessed field is worse than an
absent one, because ``None`` says "nothing establishes this" while a fabricated
boolean enters the policy contract as fact. This module supplies the authority
that slot was waiting for, under a constraint that keeps that promise.

**A model may propose a ``TaskIntent``. It may not thereby assert SUPPORTED.**

Every clause of the match is re-derived here from things that are not the
model's word for it:

* the intent's ``source_spans`` must actually occur in the task text, so an
  invented goal cannot manufacture a match;
* ``resource_type`` must agree with the declared tool contract;
* the requested effect must be reachable by the tool's declared effect;
* the call must actually fill the role the intent says is targeted.

Any clause that cannot be established yields UNKNOWN, never SUPPORTED. Only a
positive, established contradiction yields UNSUPPORTED. This is the same
tri-state discipline as ``argument_values_supported``: unknown must never behave
like a negative, and it must never behave like a positive either.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from remora.toolcall.routing.tool_contract import READ_EFFECTS, ToolContract


class GoalMatch(Enum):
    """Tri-state verdict on task-call fit."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


#: Normalisation for span checking: collapse whitespace and case so that a
#: legitimately re-cased or re-spaced quotation still verifies, while an
#: invented phrase still fails. Deliberately not fuzzy — a near-match is not a
#: quotation, and this check is the whole guard against fabricated intent.
_WS = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


@dataclass(frozen=True)
class TaskIntent:
    """What the user asked for, structured.

    May be produced by a model, a template, or a declaration. Its provenance
    does not change how much authority it carries: none on its own. It is a
    *claim* that ``match_tool_to_intent`` then tries to verify against the task
    text and the tool contract.
    """

    #: What the user wants done, in the task's own terms: retrieve, cancel, ...
    operation: str
    #: What they want it done to: ``booking``, ``work_order``, ...
    resource_type: str
    #: The effect that would satisfy them: ``read``, ``cancel``, ...
    requested_effect: str
    #: Roles the action must target, e.g. ``("target_resource",)``.
    target_entities: tuple[str, ...] = ()
    #: Verbatim spans of the task text this intent was read from. An intent
    #: whose spans are not in the task cannot support anything.
    source_spans: tuple[str, ...] = ()
    #: Free-text note on where the intent came from. Audit only; it grants
    #: nothing, by design.
    proposed_by: str = "unspecified"

    def spans_verifiable_in(self, task_text: str | None) -> bool:
        if not self.source_spans or not task_text:
            return False
        haystack = _normalise(task_text)
        return all(_normalise(span) in haystack for span in self.source_spans)


@dataclass(frozen=True)
class GoalMatchResult:
    """The verdict plus why, so the decision trace can carry the reason."""

    verdict: GoalMatch
    reason: str
    #: Whether the proposed tool changes state. Carried out so the caller can
    #: apply the write posture without re-reading the contract; SUPPORTED is
    #: never permission for a write on its own.
    mutation: bool | None = None

    @property
    def as_bool(self) -> bool | None:
        """Tri-state as the policy contract's ``bool | None``."""
        if self.verdict is GoalMatch.SUPPORTED:
            return True
        if self.verdict is GoalMatch.UNSUPPORTED:
            return False
        return None


def _effect_reachable(requested: str, contract: ToolContract) -> bool:
    """Can the tool's declared effect satisfy the requested one?

    Exact match satisfies. A read request is also satisfied by any read-family
    effect, so ``retrieve`` and ``get`` are interchangeable. Nothing else is:
    a read request is *not* satisfied by a cancel, which is precisely the
    same-resource-wrong-effect case §34's residue contains.
    """
    want = requested.strip().lower()
    have = contract.effect.strip().lower()
    if want == have:
        return True
    return want in READ_EFFECTS and have in READ_EFFECTS


def match_tool_to_intent(
    *,
    contract: ToolContract | None,
    intent: TaskIntent | None,
    proposed_args: Mapping[str, Any] | None,
    task_text: str | None,
) -> GoalMatchResult:
    """Establish, refute, or decline to judge the call's fit to the goal.

    Order matters. The clauses that can only produce UNKNOWN are evaluated
    first, so a call we cannot judge is never refuted on a technicality; the
    refutations that follow are then genuine, established contradictions.
    """
    if contract is None:
        return GoalMatchResult(
            GoalMatch.UNKNOWN,
            "no tool contract is declared for this tool, so nothing establishes "
            "what it is for",
        )
    if intent is None:
        return GoalMatchResult(
            GoalMatch.UNKNOWN,
            "no task intent was supplied, so there is no goal to match against",
            mutation=contract.mutation,
        )
    if not intent.spans_verifiable_in(task_text):
        return GoalMatchResult(
            GoalMatch.UNKNOWN,
            "the intent's source span(s) do not occur in the task text, so the "
            "intent is unverified and cannot establish a match",
            mutation=contract.mutation,
        )

    # Established contradictions. Both are the §34 residue: a well-formed call
    # whose only defect is that it does not serve the goal.
    if _normalise(intent.resource_type) != _normalise(contract.resource_type):
        return GoalMatchResult(
            GoalMatch.UNSUPPORTED,
            f"resource mismatch: the task targets {intent.resource_type!r} but "
            f"the tool acts on {contract.resource_type!r}",
            mutation=contract.mutation,
        )
    if not _effect_reachable(intent.requested_effect, contract):
        return GoalMatchResult(
            GoalMatch.UNSUPPORTED,
            f"effect mismatch: the task requests {intent.requested_effect!r} but "
            f"the tool's declared effect is {contract.effect!r}",
            mutation=contract.mutation,
        )

    # The call must actually act on what the intent says is targeted. A missing
    # role is unknown rather than refuted: the call may be incomplete for
    # reasons the argument gates already handle.
    filled = contract.roles_present(proposed_args or {})
    missing = [role for role in intent.target_entities if role not in filled]
    if missing:
        return GoalMatchResult(
            GoalMatch.UNKNOWN,
            f"the call does not fill the targeted role(s) {sorted(missing)}, so "
            f"nothing establishes that it acts on what the task named",
            mutation=contract.mutation,
        )

    return GoalMatchResult(
        GoalMatch.SUPPORTED,
        f"the tool acts on {contract.resource_type!r} with effect "
        f"{contract.effect!r}, matching a task intent quoted from the task text",
        mutation=contract.mutation,
    )
