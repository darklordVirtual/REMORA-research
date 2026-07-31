# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for semantic call compatibility (REM-UR-011).

§21 showed the router is a near-constant predictor: identity,
missing_arg_obtainable, missing_arg_unobtainable and wrong_arg_value all receive
the same prediction because nothing in the observation distinguishes them.

This module adds the two compatibility facts that can be established
**deterministically from authoritative state**, without a model:

    argument_roles_valid       every required parameter is present
    argument_values_supported  every identifier value exists in the system of record

The three remaining facts in the proposed contract — tool_matches_goal,
preconditions_met, expected_effect_matches — are left ``None``. They need task
semantics that no authoritative source in this benchmark provides, and a field
that is guessed is worse than a field that is absent.

A trap this deliberately avoids: the mutation generator creates
``wrong_arg_value`` by appending a suffix, so a detector that looked for that
suffix would score perfectly and measure nothing. The check here asks whether
the value exists in tau2's own database — a capability an integrator genuinely
has — and is blind to how the wrong value was produced.
"""
from __future__ import annotations

import pytest

from remora.toolcall.routing.compatibility import (
    CallCompatibility,
    StateIndex,
    compute_compatibility,
)
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry(
        {
            "get_reservation_details": ToolSignature(
                "get_reservation_details", ("reservation_id",), ()
            ),
            "book_reservation": ToolSignature(
                "book_reservation", ("user_id", "flight_number"), ()
            ),
        }
    )


@pytest.fixture
def state() -> StateIndex:
    return StateIndex.from_values({"EHGLP3", "4WQ150", "emma_kim_9957", "HAT001"})


# ---------------------------------------------------------------------------
# argument_roles_valid
# ---------------------------------------------------------------------------

def test_all_required_parameters_present(registry, state) -> None:
    c = compute_compatibility(
        tool="get_reservation_details",
        args={"reservation_id": "EHGLP3"},
        registry=registry,
        state=state,
    )
    assert c.argument_roles_valid is True


def test_missing_required_parameter_is_detected(registry, state) -> None:
    c = compute_compatibility(
        tool="get_reservation_details", args={}, registry=registry, state=state
    )
    assert c.argument_roles_valid is False


def test_unregistered_tool_leaves_roles_unknown(registry, state) -> None:
    """Unknown must never read as a negative."""
    c = compute_compatibility(
        tool="not_in_registry", args={"x": 1}, registry=registry, state=state
    )
    assert c.argument_roles_valid is None


# ---------------------------------------------------------------------------
# argument_values_supported — the signal §21 says is missing
# ---------------------------------------------------------------------------

def test_identifier_present_in_authoritative_state_is_supported(registry, state) -> None:
    c = compute_compatibility(
        tool="get_reservation_details",
        args={"reservation_id": "EHGLP3"},
        registry=registry,
        state=state,
    )
    assert c.argument_values_supported is True


def test_identifier_absent_from_authoritative_state_is_unsupported(registry, state) -> None:
    """This is the wrong_arg_value case, detected without seeing the mutation."""
    c = compute_compatibility(
        tool="get_reservation_details",
        args={"reservation_id": "EHGLP3_XX"},
        registry=registry,
        state=state,
    )
    assert c.argument_values_supported is False


def test_detection_is_blind_to_how_the_wrong_value_was_made(registry, state) -> None:
    """Any absent identifier fails, not just the generator's suffix.

    If this only caught the generator's own corruption pattern, the signal
    would score perfectly on the benchmark and mean nothing in deployment.
    """
    for bogus in ("ZZZZZ9", "EHGLP4", "reservation-99", "EHGLP3_XX"):
        c = compute_compatibility(
            tool="get_reservation_details",
            args={"reservation_id": bogus},
            registry=registry,
            state=state,
        )
        assert c.argument_values_supported is False, bogus


def test_non_identifier_shaped_value_is_unknown_not_unsupported(registry, state) -> None:
    """A value that is not identifier-shaped cannot be confirmed either way.

    The shape rule requires a digit or underscore, which fits tau2's ids
    (EHGLP3, 4WQ150, emma_kim_9957, HAT001) but also means an all-letter token
    is out of scope. Reporting None there is honest; reporting False would
    invent a negative about a value the rule was never meant to judge. This is
    a real limitation of the deterministic check, recorded rather than hidden.
    """
    c = compute_compatibility(
        tool="get_reservation_details",
        args={"reservation_id": "ZZZZZZ"},
        registry=registry,
        state=state,
    )
    assert c.argument_values_supported is None


def test_empty_state_index_leaves_values_unknown(registry) -> None:
    """With no system of record, nothing can be confirmed unsupported."""
    c = compute_compatibility(
        tool="get_reservation_details",
        args={"reservation_id": "anything"},
        registry=registry,
        state=StateIndex.from_values(set()),
    )
    assert c.argument_values_supported is None


def test_non_identifier_values_are_not_checked(registry, state) -> None:
    """Free text and small numbers are not identifiers and must not fail.

    Checking them against a state index would reject every legitimate call
    carrying a date, a count or a message body.
    """
    c = compute_compatibility(
        tool="book_reservation",
        args={"user_id": "emma_kim_9957", "flight_number": "HAT001",
              "note": "window seat please", "passengers": 2},
        registry=registry,
        state=state,
    )
    assert c.argument_values_supported is True


# ---------------------------------------------------------------------------
# The fields that are deliberately not implemented
# ---------------------------------------------------------------------------

def test_semantic_fields_are_none_not_guessed(registry, state) -> None:
    """tool_matches_goal and friends need task semantics we do not have.

    Returning a guess would put an unfounded value into the policy contract,
    where None correctly says "no authoritative source establishes this".
    """
    c = compute_compatibility(
        tool="get_reservation_details",
        args={"reservation_id": "EHGLP3"},
        registry=registry,
        state=state,
    )
    assert c.tool_matches_goal is None
    assert c.preconditions_met is None
    assert c.expected_effect_matches is None


def test_compatibility_is_frozen() -> None:
    c = CallCompatibility()
    with pytest.raises(Exception):
        c.tool_matches_goal = True  # type: ignore[misc]
