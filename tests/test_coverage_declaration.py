# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for closed-world coverage declarations (§30 follow-up).

§26 and §29 were both the same failure: a confident negative about a value that
was in fact valid. Every way a completeness claim can be wrong is a scope error,
so each is bound explicitly here and each degrades to UNKNOWN rather than to
UNSUPPORTED. Losing the ability to make a negative claim is the safe direction.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from remora.toolcall.routing.compatibility import ArgumentValueStatus
from remora.toolcall.routing.coverage_declaration import (
    CoverageDeclaration,
    DeclarationInvalid,
    admitted_scopes,
    build_state_index,
)


@pytest.fixture
def snapshot(tmp_path) -> Path:
    p = tmp_path / "banking.json"
    p.write_text('{"users": {"u1": {"user_id": "u1"}}}', encoding="utf-8")
    return p


def _declaration(snapshot: Path, **overrides) -> CoverageDeclaration:
    base = dict(
        domain="banking",
        tenant="tau2_fixture",
        entity_type="user",
        argument_role="user_id",
        source_snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        as_of=date(2026, 7, 31),
        completeness_basis="full simulator database export",
        curator="stian",
    )
    base.update(overrides)
    return CoverageDeclaration(**base)


# ---------------------------------------------------------------------------
# A declaration binds to exact bytes
# ---------------------------------------------------------------------------

def test_a_matching_snapshot_admits_the_scope(snapshot) -> None:
    admitted = admitted_scopes(
        (_declaration(snapshot),), {"banking": snapshot}, tenant="tau2_fixture"
    )
    assert admitted == {"banking": {"user_id"}}


def test_a_changed_snapshot_drops_the_scope(snapshot) -> None:
    """Complete at one instant is not complete later."""
    declaration = _declaration(snapshot)
    snapshot.write_text('{"users": {"u1": {}, "u2": {}}}', encoding="utf-8")
    assert admitted_scopes(
        (declaration,), {"banking": snapshot}, tenant="tau2_fixture"
    ) == {}


def test_a_different_tenant_drops_the_scope(snapshot) -> None:
    """Complete for one tenant says nothing about another."""
    assert admitted_scopes(
        (_declaration(snapshot),), {"banking": snapshot}, tenant="other_tenant"
    ) == {}


def test_a_missing_snapshot_drops_the_scope(snapshot) -> None:
    assert admitted_scopes(
        (_declaration(snapshot),), {}, tenant="tau2_fixture"
    ) == {}


def test_declarations_are_per_argument_role(snapshot) -> None:
    """Vouching for user_id says nothing about phone_number."""
    admitted = admitted_scopes(
        (_declaration(snapshot),), {"banking": snapshot}, tenant="tau2_fixture"
    )
    assert "phone_number" not in admitted["banking"]


# ---------------------------------------------------------------------------
# A declaration may not claim behaviour the code does not implement
# ---------------------------------------------------------------------------

def test_unimplemented_canonicalization_is_refused(snapshot) -> None:
    """Declaring a comparison the code does not perform is the §29 failure.

    A curator writing `canonicalization: case_insensitive` would be promising
    that "U1" matches "u1". The comparison is exact, so valid values would be
    reported as confirmed-invalid.
    """
    with pytest.raises(DeclarationInvalid, match="canonicalization"):
        _declaration(snapshot, canonicalization="case_insensitive")


def test_claiming_alias_support_is_refused(snapshot) -> None:
    with pytest.raises(DeclarationInvalid, match="alias"):
        _declaration(snapshot, aliases_supported=True)


def test_a_truncated_digest_is_refused(snapshot) -> None:
    with pytest.raises(DeclarationInvalid, match="SHA-256"):
        _declaration(snapshot, source_snapshot_sha256="abc123")


@pytest.mark.parametrize(
    "field", ["domain", "tenant", "entity_type", "argument_role",
              "completeness_basis", "curator"]
)
def test_every_binding_field_is_mandatory(snapshot, field: str) -> None:
    """An unattributed completeness claim is not evidence."""
    with pytest.raises(DeclarationInvalid, match=field):
        _declaration(snapshot, **{field: "  "})


def test_round_trips_through_json(snapshot) -> None:
    d = _declaration(snapshot)
    assert CoverageDeclaration.from_json_dict(d.to_json_dict()) == d


# ---------------------------------------------------------------------------
# Freshness — hash binding cannot catch a world that moved on
# ---------------------------------------------------------------------------
#
# A snapshot whose bytes never changed still goes stale: records created after
# it are valid in the live world and absent from it. Only the as_of date can
# betray that, so admission accepts an explicit freshness bound.

def test_a_declaration_within_max_age_is_admitted(snapshot) -> None:
    admitted = admitted_scopes(
        (_declaration(snapshot),),
        {"banking": snapshot},
        tenant="tau2_fixture",
        today=date(2026, 8, 5),
        max_age_days=30,
    )
    assert admitted == {"banking": {"user_id"}}


def test_a_declaration_older_than_max_age_is_dropped(snapshot) -> None:
    """Complete at one instant, consulted later — the un-hashable staleness."""
    declaration = _declaration(snapshot, as_of=date(2026, 7, 1))
    assert admitted_scopes(
        (declaration,),
        {"banking": snapshot},
        tenant="tau2_fixture",
        today=date(2026, 8, 5),
        max_age_days=30,
    ) == {}


def test_age_exactly_at_the_bound_is_admitted(snapshot) -> None:
    declaration = _declaration(snapshot, as_of=date(2026, 7, 6))
    assert admitted_scopes(
        (declaration,),
        {"banking": snapshot},
        tenant="tau2_fixture",
        today=date(2026, 8, 5),
        max_age_days=30,
    ) == {"banking": {"user_id"}}


def test_without_a_freshness_bound_age_is_not_checked(snapshot) -> None:
    """Opt-in: existing callers keep hash-and-tenant-only admission."""
    declaration = _declaration(snapshot, as_of=date(2020, 1, 1))
    assert admitted_scopes(
        (declaration,), {"banking": snapshot}, tenant="tau2_fixture"
    ) == {"banking": {"user_id"}}


def test_a_lone_freshness_parameter_is_refused(snapshot) -> None:
    """today without max_age_days (or vice versa) is an ambiguous half-bound."""
    with pytest.raises(ValueError, match="max_age_days"):
        admitted_scopes(
            (_declaration(snapshot),),
            {"banking": snapshot},
            tenant="tau2_fixture",
            today=date(2026, 8, 5),
        )
    with pytest.raises(ValueError, match="today"):
        admitted_scopes(
            (_declaration(snapshot),),
            {"banking": snapshot},
            tenant="tau2_fixture",
            max_age_days=30,
        )


# ---------------------------------------------------------------------------
# build_state_index — the one production path from declarations to an index
# ---------------------------------------------------------------------------
#
# Track A2 was evaluated through wiring assembled inline in a runner that was
# never committed. This function is that wiring, landed: declarations plus
# snapshots in, StateIndex out, with every admission rule applied on the way.

def test_admitted_declaration_yields_closed_world_verdicts(snapshot) -> None:
    index = build_state_index(
        (_declaration(snapshot),), {"banking": snapshot}, tenant="tau2_fixture"
    )
    assert index.status("banking", "user_id", "u1") is ArgumentValueStatus.SUPPORTED
    assert (
        index.status("banking", "user_id", "u999")
        is ArgumentValueStatus.UNSUPPORTED
    )


def test_undeclared_roles_stay_open_world(snapshot) -> None:
    """Vouching for user_id confers no authority over other keys in the file."""
    index = build_state_index(
        (_declaration(snapshot),), {"banking": snapshot}, tenant="tau2_fixture"
    )
    assert (
        index.status("banking", "phone_number", "absent-value")
        is ArgumentValueStatus.UNKNOWN
    )


def test_wrong_tenant_degrades_every_negative_to_unknown(snapshot) -> None:
    index = build_state_index(
        (_declaration(snapshot),), {"banking": snapshot}, tenant="other_tenant"
    )
    assert (
        index.status("banking", "user_id", "u999") is ArgumentValueStatus.UNKNOWN
    )
    # Positive confirmation is still allowed: the value is genuinely present.
    assert index.status("banking", "user_id", "u1") is ArgumentValueStatus.SUPPORTED


def test_changed_snapshot_degrades_every_negative_to_unknown(snapshot) -> None:
    declaration = _declaration(snapshot)
    snapshot.write_text('{"users": {"u1": {"user_id": "u1"}, "x": 1}}', encoding="utf-8")
    index = build_state_index(
        (declaration,), {"banking": snapshot}, tenant="tau2_fixture"
    )
    assert (
        index.status("banking", "user_id", "u999") is ArgumentValueStatus.UNKNOWN
    )


def test_a_snapshot_filename_that_contradicts_its_domain_is_refused(
    snapshot, tmp_path
) -> None:
    """The index keys coverage by file stem; a mismatch would misfile the scope.

    A declaration admitted for "banking" but indexed under the stem "foo"
    would silently apply to no episode at all — coverage lost without a trace.
    """
    misnamed = tmp_path / "foo.json"
    misnamed.write_bytes(snapshot.read_bytes())
    with pytest.raises(ValueError, match="stem"):
        build_state_index(
            (_declaration(misnamed),), {"banking": misnamed}, tenant="tau2_fixture"
        )


def test_stale_declaration_degrades_every_negative_to_unknown(snapshot) -> None:
    declaration = _declaration(snapshot, as_of=date(2026, 7, 1))
    index = build_state_index(
        (declaration,),
        {"banking": snapshot},
        tenant="tau2_fixture",
        today=date(2026, 8, 5),
        max_age_days=30,
    )
    assert (
        index.status("banking", "user_id", "u999") is ArgumentValueStatus.UNKNOWN
    )
