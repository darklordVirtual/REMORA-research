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


def is_irreversible_action(action_type: str | None) -> bool:
    """Return True when action_type (case/space-normalised) is irreversible."""
    return (action_type or "").strip().lower() in IRREVERSIBLE_ACTION_TYPES
