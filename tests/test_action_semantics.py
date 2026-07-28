# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""F2 (external review 2026-07-28): one authority for irreversible actions.

The engine's rollback heuristic and the credal worst-case-loss multiplier
must never diverge on which action types are irreversible.
"""
from remora.action_semantics import IRREVERSIBLE_ACTION_TYPES, is_irreversible_action


def test_engine_and_credal_share_the_same_set():
    from remora.credal import _IRREVERSIBLE_ACTIONS
    from remora.engine import Remora

    assert Remora._IRREVERSIBLE_ACTION_TYPES is IRREVERSIBLE_ACTION_TYPES
    assert _IRREVERSIBLE_ACTIONS is IRREVERSIBLE_ACTION_TYPES


def test_union_covers_both_historical_sets():
    # The pre-unification sets (engine 5, credal 10). Removing any of these
    # from the shared set would silently relax a safety heuristic.
    engine_legacy = {
        "destructive_write", "delete", "irreversible_delete",
        "emergency_write", "financial_write",
    }
    credal_legacy = {
        "delete", "destructive_write", "emergency_write", "financial_write",
        "production_write", "execute_transfer", "disable_security",
        "config_overwrite", "bulk_delete", "wipe",
    }
    assert engine_legacy <= IRREVERSIBLE_ACTION_TYPES
    assert credal_legacy <= IRREVERSIBLE_ACTION_TYPES


def test_is_irreversible_action_normalises():
    assert is_irreversible_action("delete")
    assert is_irreversible_action("  DELETE ")
    assert is_irreversible_action("Production_Write")
    assert not is_irreversible_action("read")
    assert not is_irreversible_action(None)
    assert not is_irreversible_action("")
