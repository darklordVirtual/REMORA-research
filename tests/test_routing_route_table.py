# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Exhaustive tests for the frozen route table (routing benchmark v1).

The table is a *definition*, not an inference: it maps native dataset
predicates to a REMORA route. These tests pin its totality, its row
precedence, and its content hash, so an unversioned edit fails CI.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import itertools

import pytest

from remora.toolcall.routing.episode import Route
from remora.toolcall.routing.predicates import NativePredicates, PredicateValue
from remora.toolcall.routing.route_table import (
    ROUTE_TABLE_VERSION,
    assign_route,
    table_content_hash,
)

TRISTATE: tuple[bool | None, ...] = (True, False, None)
FIELDS = (
    "tool_required",
    "call_in_gold_set",
    "originates_from_untrusted",
    "information_missing",
    "policy_forbids",
)


def _preds(**kwargs: bool | None) -> NativePredicates:
    """Build predicates from raw tri-state values with dummy provenance."""
    return NativePredicates(
        **{
            name: PredicateValue(
                value=kwargs.get(name),
                source_dataset="test",
                source_field=f"fixture.{name}",
            )
            for name in FIELDS
        }
    )


def _all_combinations() -> list[NativePredicates]:
    return [
        _preds(**dict(zip(FIELDS, combo)))
        for combo in itertools.product(TRISTATE, repeat=len(FIELDS))
    ]


# ---------------------------------------------------------------------------
# Totality
# ---------------------------------------------------------------------------

def test_table_is_total_over_the_predicate_space() -> None:
    """Every one of the 3^5 predicate combinations returns a Route or None.

    Totality is what makes `route: null` a deliberate outcome rather than an
    unhandled case. If a combination raised or returned something else, an
    episode could silently acquire an undefined label.
    """
    combos = _all_combinations()
    assert len(combos) == 243
    for preds in combos:
        result = assign_route(preds)
        assert result is None or isinstance(result, Route), (
            f"{preds} produced {result!r}, expected Route or None"
        )


# ---------------------------------------------------------------------------
# One test per row, at its minimal triggering condition
# ---------------------------------------------------------------------------

def test_row1_policy_forbids_escalates() -> None:
    assert assign_route(_preds(policy_forbids=True)) is Route.ESCALATE


def test_row2_untrusted_origin_escalates() -> None:
    assert assign_route(_preds(originates_from_untrusted=True)) is Route.ESCALATE


def test_row3_missing_information_verifies() -> None:
    assert assign_route(_preds(information_missing=True)) is Route.VERIFY


def test_row4_no_tool_required_abstains() -> None:
    assert assign_route(_preds(tool_required=False)) is Route.ABSTAIN


def test_row5_required_and_in_gold_set_accepts() -> None:
    assert assign_route(_preds(tool_required=True, call_in_gold_set=True)) is Route.ACCEPT


def test_all_predicates_unknown_is_unlabelled() -> None:
    assert assign_route(_preds()) is None


# ---------------------------------------------------------------------------
# The deliberate hole: wrong call is NOT labelled
# ---------------------------------------------------------------------------

def test_wrong_call_is_deliberately_unlabelled() -> None:
    """tool_required=True with call_in_gold_set=False must return None.

    The source annotates that the proposed call is not the correct one. It does
    not say whether the right response is to stop (ABSTAIN) or to repair the
    call (VERIFY). The table must not choose what the data does not. These
    episodes are recovered by the safety-axis metric instead.
    """
    assert assign_route(_preds(tool_required=True, call_in_gold_set=False)) is None


def test_confirmed_false_differs_from_unknown_for_tool_required() -> None:
    """tool_required False and None must not collapse into one outcome.

    Same confirmed-false versus unknown separation the engine protects in
    tests/test_escalate_semantics_guard.py. "The source states no tool call is
    correct" (ABSTAIN) is a different claim from "the source is silent about
    whether a tool is needed" (unlabelled). A table that treated None as False
    would manufacture ABSTAIN labels out of missing annotation.
    """
    assert assign_route(_preds(tool_required=False)) is Route.ABSTAIN
    assert assign_route(_preds(tool_required=None)) is None


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------

def test_policy_forbids_outranks_a_correct_call() -> None:
    """A call in the gold set still escalates when policy forbids the action."""
    preds = _preds(policy_forbids=True, tool_required=True, call_in_gold_set=True)
    assert assign_route(preds) is Route.ESCALATE


def test_untrusted_origin_outranks_missing_information() -> None:
    preds = _preds(originates_from_untrusted=True, information_missing=True)
    assert assign_route(preds) is Route.ESCALATE


def test_missing_information_outranks_accept() -> None:
    """Missing information routes to VERIFY even for an otherwise-correct call."""
    preds = _preds(information_missing=True, tool_required=True, call_in_gold_set=True)
    assert assign_route(preds) is Route.VERIFY


@pytest.mark.parametrize("blocker", ["policy_forbids", "originates_from_untrusted"])
def test_no_blocking_predicate_can_yield_accept(blocker: str) -> None:
    """ACCEPT is unreachable whenever a blocking predicate is confirmed true.

    This is the safety-relevant property of the table: it must be impossible
    for a table edit to let a forbidden or untrusted-origin call score ACCEPT.
    """
    for combo in itertools.product(TRISTATE, repeat=len(FIELDS) - 1):
        others = [f for f in FIELDS if f != blocker]
        kwargs = dict(zip(others, combo))
        kwargs[blocker] = True
        assert assign_route(_preds(**kwargs)) is not Route.ACCEPT


# ---------------------------------------------------------------------------
# Version and hash pinning
# ---------------------------------------------------------------------------

def test_route_table_version_is_pinned() -> None:
    assert ROUTE_TABLE_VERSION == "1"


def test_route_table_content_hash_is_pinned() -> None:
    """An edit to the table without a version bump must fail here.

    The hash also goes into the benchmark manifest, so committed episodes can
    be tied to the exact table that produced them.
    """
    assert table_content_hash() == (
        "2b420160d0dfe0ce7e28a1eff2b3a9b85be77be1f089360d154b7c9de53b55c7"
    )


def test_outcome_distribution_over_the_full_space_is_pinned() -> None:
    """Pins how much of the predicate space each route covers.

    A structural change to the table shifts these counts even when the
    individual row tests still pass.
    """
    counts: dict[str, int] = {}
    for preds in _all_combinations():
        key = assign_route(preds).value if assign_route(preds) else "null"
        counts[key] = counts.get(key, 0) + 1
    assert sum(counts.values()) == 243
    # Verified analytically, independent of the implementation:
    #   escalate = 81 (policy_forbids) + 54 (untrusted, not already caught)
    #   verify   = 81 - 45 (info_missing minus rows 1-2 overlap)
    #   abstain  = 2*2*2*3 (tool_required=False, no blocker true, gold free)
    #   accept   = 2*2*2   (tool_required=True, gold=True, no blocker true)
    assert counts == {
        "escalate": 135,
        "verify": 36,
        "abstain": 24,
        "accept": 8,
        "null": 40,
    }
