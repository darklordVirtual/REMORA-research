# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Does the predicted state change match what the task asked for?

``CallCompatibility.expected_effect_matches`` has been ``None`` since the
contract was defined, alongside ``preconditions_met``, for the reason
``compatibility.py`` gives: a guessed field is worse than an absent one. This
module supplies an authority for that slot, under the same constraint
``goal_match`` accepted — nothing here may reach SUPPORTED on a model's word.

Why this is not a restatement of ``goal_match``
-----------------------------------------------
``match_tool_to_intent`` compares *labels*: the intent's ``requested_effect``
against the contract's declared ``effect``. That catches a read request served
by a cancel. It cannot catch two things this does:

* A contract that declares a mutating effect but no ``state_delta`` at all.
  The label matches, so ``goal_match`` says SUPPORTED, while in fact nothing
  declares what the call would change. That is UNKNOWN here, which is a
  tightening in the safe direction: the deployment has not finished declaring
  the tool, and an undeclared write should not ride on a matching label.
* A contract whose declared post-state writes a *different resource* than the
  one the intent targets — ``close_work_order`` declaring
  ``invoice.status: void``. ``resource_type`` says "work_order" and the label
  agrees, so every earlier gate passes; the declared effect does not.

Deliberately not implemented: a learned dynamics model. Guo et al. (2025,
arXiv:2506.02918) train a model to predict post-action state and use it to
screen calls before execution. That is a real result and a plausible later
diagnostic, but a model-predicted state must never be what establishes
SUPPORTED here — it would put a generative estimate where the contract needs a
declaration. This module predicts from the deployment's declared delta only.

Also deliberately not implemented: no-op detection ("close a work order that is
already closed"). It needs field-level current state, and ``StateIndex`` is a
flat value set by design, because a schema-aware state model invites
over-fitting to one dataset's shape. Adding one is a separate decision with its
own evidence, not a side effect of this module.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from remora.toolcall.routing.goal_match import TaskIntent, _normalise
from remora.toolcall.routing.tool_contract import READ_EFFECTS, ToolContract


class EffectConsistency(Enum):
    """Tri-state verdict on predicted-effect vs requested-effect."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PredictedStateDelta:
    """What the deployment declares this call would leave behind.

    ``changes`` is the contract's declared post-state, not a simulation: each
    entry is a dotted field and the value it is declared to hold afterwards.
    An empty ``changes`` on a mutating tool means *undeclared*, which is why
    ``declared`` is carried separately from emptiness.
    """

    tool: str
    changes: Mapping[str, str]
    mutates: bool
    declared: bool

    @property
    def resources_touched(self) -> frozenset[str]:
        """Resource types named by the declared fields, e.g. ``work_order``."""
        return frozenset(
            field.split(".", 1)[0].strip().lower()
            for field in self.changes
            if field.strip()
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "changes": dict(sorted(self.changes.items())),
            "mutates": self.mutates,
            "declared": self.declared,
        }


@dataclass(frozen=True)
class EffectConsistencyResult:
    verdict: EffectConsistency
    reason: str
    predicted: PredictedStateDelta | None = None

    @property
    def as_bool(self) -> bool | None:
        """Tri-state as the policy contract's ``bool | None``."""
        if self.verdict is EffectConsistency.SUPPORTED:
            return True
        if self.verdict is EffectConsistency.CONTRADICTED:
            return False
        return None


def predict_state_delta(
    contract: ToolContract | None,
    proposed_args: Mapping[str, Any] | None = None,
) -> PredictedStateDelta | None:
    """Expand the contract's declared post-state for this call.

    Returns ``None`` when no contract is declared — there is nothing to
    predict from, and inventing a delta would be exactly the fabrication the
    tri-state discipline exists to prevent.

    ``proposed_args`` is accepted so a future templated delta
    (``work_order.{work_order_id}.status``) can bind its placeholders without
    a signature change. Today the declared delta is used verbatim; binding
    arguments into field paths is not implemented, and a delta containing a
    placeholder is therefore left as written rather than silently half-bound.
    """
    if contract is None:
        return None
    return PredictedStateDelta(
        tool=contract.tool,
        changes=dict(contract.state_delta),
        mutates=contract.mutation,
        declared=bool(contract.state_delta),
    )


def _requested_is_read(intent: TaskIntent) -> bool:
    return intent.requested_effect.strip().lower() in READ_EFFECTS


def effect_consistent(
    *,
    contract: ToolContract | None,
    intent: TaskIntent | None,
    proposed_args: Mapping[str, Any] | None = None,
    task_text: str | None = None,
) -> EffectConsistencyResult:
    """Establish, refute, or decline to judge the call's predicted effect.

    Ordering follows ``match_tool_to_intent``: everything that can only yield
    UNKNOWN is evaluated before any refutation, so a call that cannot be judged
    is never refuted on a technicality.
    """
    predicted = predict_state_delta(contract, proposed_args)
    if contract is None or predicted is None:
        return EffectConsistencyResult(
            EffectConsistency.UNKNOWN,
            "no tool contract is declared, so no state change can be predicted",
        )
    if intent is None:
        return EffectConsistencyResult(
            EffectConsistency.UNKNOWN,
            "no task intent was supplied, so there is no requested effect to "
            "compare the predicted change against",
            predicted,
        )
    if not intent.spans_verifiable_in(task_text):
        # Same guard as goal_match: an intent whose spans are not in the task
        # is the model's assertion, and an assertion must not be able to
        # establish that an effect is the one the user wanted.
        return EffectConsistencyResult(
            EffectConsistency.UNKNOWN,
            "the intent's source span(s) do not occur in the task text, so the "
            "requested effect is unverified",
            predicted,
        )

    wants_read = _requested_is_read(intent)

    # Established contradictions.
    if wants_read and predicted.mutates:
        return EffectConsistencyResult(
            EffectConsistency.CONTRADICTED,
            f"the task requests {intent.requested_effect!r}, a read, but the "
            f"tool is declared to change state",
            predicted,
        )
    if not wants_read and not predicted.mutates:
        return EffectConsistencyResult(
            EffectConsistency.CONTRADICTED,
            f"the task requests {intent.requested_effect!r}, which changes "
            f"state, but the tool is declared read-only and cannot achieve it",
            predicted,
        )
    if predicted.declared:
        target = _normalise(intent.resource_type)
        touched = predicted.resources_touched
        if touched and target not in touched:
            return EffectConsistencyResult(
                EffectConsistency.CONTRADICTED,
                f"the task targets {intent.resource_type!r} but the declared "
                f"post-state changes {sorted(touched)} instead",
                predicted,
            )

    # Nothing refuted. SUPPORTED requires a positive declaration; a mutating
    # tool that declares no post-state leaves the effect unestablished.
    if not wants_read and not predicted.declared:
        return EffectConsistencyResult(
            EffectConsistency.UNKNOWN,
            "the tool is declared to mutate but declares no state_delta, so "
            "nothing establishes what it would change",
            predicted,
        )
    if wants_read:
        return EffectConsistencyResult(
            EffectConsistency.SUPPORTED,
            "the task requests a read and the tool is declared not to change "
            "state",
            predicted,
        )
    return EffectConsistencyResult(
        EffectConsistency.SUPPORTED,
        f"the declared post-state {dict(sorted(predicted.changes.items()))!r} "
        f"acts on {intent.resource_type!r}, the resource the task named",
        predicted,
    )
