# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Shared action-type semantics — leaf module, no remora imports.

Single source of truth for which ``action_type`` values are treated as
irreversible. External review 2026-07-28 (F2): ``remora/engine.py`` and
``remora/credal.py`` each maintained their own diverging set (5 vs 10
entries), so the engine's rollback heuristic and the credal worst-case-loss
multiplier could disagree about the same action. This module is the union of
both — strictly more conservative in both consumers (engine:
``rollback_available=False`` for more actions; credal: full 1.0
irreversibility multiplier for more actions).

Kept import-free so it can be used from both sides of the
``policy.decision_engine → credal`` import chain without cycles.
"""
from __future__ import annotations

from enum import Enum

IRREVERSIBLE_ACTION_TYPES: frozenset[str] = frozenset({
    "bulk_delete",
    "config_overwrite",
    "delete",
    "destructive_write",
    "disable_security",
    "emergency_write",
    "execute_transfer",
    "financial_write",
    "irreversible_delete",
    "production_write",
    "wipe",
})


#: Actions declared to change no state, and therefore safe to weigh cheaply.
#: Deliberately short. Every entry must be non-mutating by its own semantics,
#: not merely usually harmless: the discount this set carries is the only way
#: an action escapes the irreversible weight.
REVERSIBLE_ACTION_TYPES: frozenset[str] = frozenset({
    "analyze",
    "describe",
    "get",
    "list",
    "lookup",
    "query",
    "read",
    "search",
    "summarize",
    "view",
})


class Reversibility(Enum):
    """Three-valued, because absent is not the same as reversible."""

    IRREVERSIBLE = "irreversible"
    REVERSIBLE = "reversible"
    UNKNOWN = "unknown"


#: Worst-case-loss weight for an action whose reversibility is not declared.
#: Equal to the irreversible weight, by design: an action the risk model has
#: never seen must not be scored as recoverable. Before 2026-09-22 unknown
#: action types took the reversible weight, which made the escalation depend
#: on whether a spelling happened to be in a list of eleven strings --
#: ``config_overwrite`` escalated where ``configuration_change`` did not.
IRREVERSIBLE_WEIGHT: float = 1.0
REVERSIBLE_WEIGHT: float = 0.30


def _normalise(action_type: str | None) -> str:
    return (action_type or "").strip().lower()


def is_irreversible_action(action_type: str | None) -> bool:
    """Return True when action_type (case/space-normalised) is irreversible.

    Retained for callers that need the declared set specifically. For risk
    weighting use :func:`irreversibility_weight`, which does not treat an
    undeclared action as reversible.
    """
    return _normalise(action_type) in IRREVERSIBLE_ACTION_TYPES


def classify_reversibility(action_type: str | None) -> Reversibility:
    """Total classification: every input lands in exactly one class."""
    normalised = _normalise(action_type)
    if normalised in IRREVERSIBLE_ACTION_TYPES:
        return Reversibility.IRREVERSIBLE
    if normalised in REVERSIBLE_ACTION_TYPES:
        return Reversibility.REVERSIBLE
    return Reversibility.UNKNOWN


def irreversibility_weight(action_type: str | None) -> float:
    """The worst-case-loss weight, fail closed on anything undeclared."""
    if classify_reversibility(action_type) is Reversibility.REVERSIBLE:
        return REVERSIBLE_WEIGHT
    return IRREVERSIBLE_WEIGHT
