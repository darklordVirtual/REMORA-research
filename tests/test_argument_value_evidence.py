# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Contract tests for argument-value evidence (§26 remediation).

The blind holdout failed because absence from an airline/retail state index was
read as confirmed argument invalidity on a telecom set. Every telecom
identifier scored UNSUPPORTED, both correct and corrupted calls collapsed to
non-ACCEPT, and the discrimination gap went to zero.

That is an open-world / closed-world confusion. Absence from an index may only
mean UNSUPPORTED when the index is authoritative *and complete for that domain
and that argument*. Otherwise absence means UNKNOWN.

Coverage is per entity type, not per domain — established empirically: tau2's
telecom state covers `plan_id` and `device_id` while its tasks operate on
`customer_id` and `line_id`. A domain-level coverage flag would have called
those covered and reproduced the same failure one level up.
"""
from __future__ import annotations

import pytest

from remora.toolcall.routing.compatibility import (
    ArgumentValueStatus,
    CoverageScope,
    StateIndex,
    compute_compatibility,
)
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry(
        {"get_reservation": ToolSignature("get_reservation", ("reservation_id",), ())}
    )


@pytest.fixture
def airline_index() -> StateIndex:
    return StateIndex(
        values=frozenset({"EHGLP3", "4WQ150"}),
        scopes=(
            CoverageScope(
                domain="airline",
                argument_names=frozenset({"reservation_id"}),
                closed_world=True,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# The failure this exists to prevent
# ---------------------------------------------------------------------------

def test_uncovered_domain_is_unknown_not_unsupported(airline_index) -> None:
    """The §26 failure, as a contract test.

    A telecom identifier absent from an airline-only index means the index has
    nothing to say, not that the identifier is invalid.
    """
    assert airline_index.status("telecom", "reservation_id", "C1042") is (
        ArgumentValueStatus.UNKNOWN
    )


def test_uncovered_argument_within_a_covered_domain_is_unknown(airline_index) -> None:
    """Coverage is per entity type. tau2 telecom covers plan_id, not customer_id."""
    assert airline_index.status("airline", "passenger_name", "Ada Lovelace") is (
        ArgumentValueStatus.UNKNOWN
    )


def test_covered_and_present_is_supported(airline_index) -> None:
    assert airline_index.status("airline", "reservation_id", "EHGLP3") is (
        ArgumentValueStatus.SUPPORTED
    )


def test_covered_closed_world_and_absent_is_unsupported(airline_index) -> None:
    assert airline_index.status("airline", "reservation_id", "EHGLP3_XX") is (
        ArgumentValueStatus.UNSUPPORTED
    )


def test_open_world_coverage_never_yields_unsupported() -> None:
    """Without a closed-world guarantee, absence is not evidence of absence."""
    index = StateIndex(
        values=frozenset({"EHGLP3"}),
        scopes=(
            CoverageScope("airline", frozenset({"reservation_id"}), closed_world=False),
        ),
    )
    assert index.status("airline", "reservation_id", "ANYTHING") is (
        ArgumentValueStatus.UNKNOWN
    )


def test_unrelated_index_values_do_not_change_the_verdict(airline_index) -> None:
    """Adding another domain's data must not make an uncovered lookup decidable."""
    widened = StateIndex(
        values=airline_index.values | {"P1001", "D1001"},
        scopes=airline_index.scopes,
    )
    assert widened.status("telecom", "plan_id", "P9999") is ArgumentValueStatus.UNKNOWN


def test_empty_index_is_unknown() -> None:
    assert StateIndex(frozenset(), ()).status("airline", "x", "y") is (
        ArgumentValueStatus.UNKNOWN
    )


# ---------------------------------------------------------------------------
# The engine-facing field keeps its tri-state meaning
# ---------------------------------------------------------------------------

def test_compatibility_maps_unknown_to_none(registry, airline_index) -> None:
    """UNKNOWN must reach the policy contract as None, never as False.

    False is a claim about the world. None is a claim about our evidence.
    Reporting the first when only the second holds is what §26 measured.
    """
    c = compute_compatibility(
        tool="get_reservation",
        args={"reservation_id": "C1042"},
        registry=registry,
        state=airline_index,
        domain="telecom",
    )
    assert c.argument_values_supported is None
    assert c.value_evidence is not None
    assert c.value_evidence.status is ArgumentValueStatus.UNKNOWN
    assert c.value_evidence.reason


def test_compatibility_maps_unsupported_to_false(registry, airline_index) -> None:
    c = compute_compatibility(
        tool="get_reservation",
        args={"reservation_id": "EHGLP3_XX"},
        registry=registry,
        state=airline_index,
        domain="airline",
    )
    assert c.argument_values_supported is False
    assert c.value_evidence.status is ArgumentValueStatus.UNSUPPORTED


def test_one_unknown_does_not_erase_a_confirmed_unsupported(registry, airline_index) -> None:
    """A confirmed-bad value stays decisive even when another is unjudgeable."""
    c = compute_compatibility(
        tool="get_reservation",
        args={"reservation_id": "EHGLP3_XX", "note": "seat-9A"},
        registry=registry,
        state=airline_index,
        domain="airline",
    )
    assert c.argument_values_supported is False


def test_evidence_records_what_it_was_based_on(registry, airline_index) -> None:
    """A DecisionEnvelope must be able to show why, not just what."""
    c = compute_compatibility(
        tool="get_reservation",
        args={"reservation_id": "EHGLP3"},
        registry=registry,
        state=airline_index,
        domain="airline",
    )
    ev = c.value_evidence
    assert ev.domain == "airline"
    assert ev.coverage_complete is True
    assert ev.closed_world is True


# ---------------------------------------------------------------------------
# Coverage derived from real files
# ---------------------------------------------------------------------------

def test_coverage_is_derived_from_the_indexed_keys(tmp_path) -> None:
    """The index knows what it covers because it saw those keys."""
    doc = tmp_path / "airline.json"
    doc.write_text(
        '{"reservations": {"EHGLP3": {"reservation_id": "EHGLP3", "seat": "9A"}}}',
        encoding="utf-8",
    )
    index = StateIndex.from_json_files([doc])
    assert index.status("airline", "reservation_id", "EHGLP3") is (
        ArgumentValueStatus.SUPPORTED
    )
    assert index.status("airline", "customer_id", "C1") is ArgumentValueStatus.UNKNOWN
    assert index.status("telecom", "reservation_id", "EHGLP3") is (
        ArgumentValueStatus.UNKNOWN
    )
