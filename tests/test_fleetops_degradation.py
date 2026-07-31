# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the fleetops degradation study (§31 follow-up).

§31 confirmed the value-existence mechanism under ideal conditions and said the
next thing worth measuring is its behaviour when the precondition breaks. These
tests hold the harness to that: unit tests pin the metric definitions on
hand-built episodes, and the integration tests assert the pre-registered
directional invariants through the real engine, per condition:

* baseline            — replicates the A2 configuration (sanity, openly non-blind)
* truncated_honest    — snapshot loses 30%, declaration hash no longer matches:
                        every negative degrades to UNKNOWN, so zero
                        false-UNSUPPORTED and an ineligible admission verdict
* truncated_redeclared— a curator falsely re-vouches the truncated snapshot:
                        valid identifiers are rejected at ≈ the removal fraction
* stale_unbounded     — world grew past a byte-identical snapshot: hash binding
                        admits it and post-snapshot identifiers are rejected
* stale_bounded       — the freshness bound catches what the hash cannot
* cross_tenant        — a foreign tenant's identifiers are never accepted
"""
from __future__ import annotations

import pytest

from remora.toolcall.routing.compatibility import CoverageScope, StateIndex
from remora.toolcall.routing.degradation import (
    Expectation,
    build_conditions,
    check_expectations,
    run_condition,
    score_condition,
)
from remora.toolcall.routing.episode import Route, RoutingEpisode


def _episode(family: str, args: dict, id_suffix: str) -> RoutingEpisode:
    return RoutingEpisode(
        id=f"tau2:fleetops:t:{id_suffix}",
        source_dataset="tau2",
        source_commit="test",
        cluster_id=f"tau2:fleetops:t:{id_suffix}",
        user_task="look something up",
        available_tools=("get_vehicle",),
        untrusted_context=None,
        proposed_tool_name="get_vehicle",
        proposed_tool_args=args,
        domain="fleetops",
        notes=(f"mutation:{family}",),
    )


@pytest.fixture
def state() -> StateIndex:
    return StateIndex.from_values(
        {"V-1"},
        scopes=(
            CoverageScope("fleetops", frozenset({"vehicle_id"}), closed_world=True),
        ),
    )


LIVE = {"vehicle_id": frozenset({"V-1", "V-2"})}


# ---------------------------------------------------------------------------
# score_condition — metric definitions on hand-built results
# ---------------------------------------------------------------------------

def test_family_accept_rates_are_computed_per_family(state) -> None:
    results = [
        (_episode("identity", {"vehicle_id": "V-1"}, "a"), Route.ACCEPT),
        (_episode("identity", {"vehicle_id": "V-2"}, "b"), Route.ABSTAIN),
        (_episode("wrong_arg_value", {"vehicle_id": "V-9_XX"}, "c"), Route.ABSTAIN),
    ]
    metrics = score_condition(results, state, LIVE)
    assert metrics["identity_accept"] == {"n": 1, "d": 2, "rate": 0.5}
    assert metrics["wrong_arg_accept"] == {"n": 0, "d": 1, "rate": 0.0}


def test_false_unsupported_counts_only_live_valid_occurrences(state) -> None:
    """A corrupted value judged UNSUPPORTED is a correct negative, not a false
    one; only rejections of live-valid values count against the mechanism."""
    results = [
        (_episode("identity", {"vehicle_id": "V-1"}, "a"), Route.ACCEPT),
        (_episode("identity", {"vehicle_id": "V-2"}, "b"), Route.ABSTAIN),
        (_episode("wrong_arg_value", {"vehicle_id": "V-9_XX"}, "c"), Route.ABSTAIN),
    ]
    metrics = score_condition(results, state, LIVE)
    assert metrics["false_unsupported_on_valid"] == {"n": 1, "d": 2, "rate": 0.5}


def test_identity_accept_is_split_by_snapshot_membership(state) -> None:
    """The split separates 'mechanism worked' from 'snapshot was adequate'."""
    results = [
        (_episode("identity", {"vehicle_id": "V-1"}, "a"), Route.ACCEPT),
        (_episode("identity", {"vehicle_id": "V-2"}, "b"), Route.ABSTAIN),
    ]
    metrics = score_condition(results, state, LIVE)
    assert metrics["identity_accept_snapshot_present"] == {"n": 1, "d": 1, "rate": 1.0}
    assert metrics["identity_accept_snapshot_absent"] == {"n": 0, "d": 1, "rate": 0.0}


def test_identity_accept_is_split_by_action_type(state) -> None:
    """Autonomy is claimed for reads; writes route to verification. Pooling
    them would let read autonomy mask write behaviour and vice versa."""
    write = RoutingEpisode(
        id="tau2:fleetops:t:w",
        source_dataset="tau2",
        source_commit="test",
        cluster_id="tau2:fleetops:t:w",
        user_task="assign the driver",
        available_tools=("assign_driver",),
        untrusted_context=None,
        proposed_tool_name="assign_driver",
        proposed_tool_args={"vehicle_id": "V-1"},
        domain="fleetops",
        notes=("mutation:identity",),
    )
    results = [
        (_episode("identity", {"vehicle_id": "V-1"}, "a"), Route.ACCEPT),
        (write, Route.VERIFY),
    ]
    metrics = score_condition(results, state, LIVE)
    assert metrics["identity_accept_read"] == {"n": 1, "d": 1, "rate": 1.0}
    assert metrics["identity_accept_write"] == {"n": 0, "d": 1, "rate": 0.0}


def test_route_distribution_is_reported_per_family(state) -> None:
    results = [
        (_episode("identity", {"vehicle_id": "V-1"}, "a"), Route.ACCEPT),
        (_episode("wrong_arg_value", {"vehicle_id": "V-9_XX"}, "c"), Route.ABSTAIN),
    ]
    metrics = score_condition(results, state, LIVE)
    assert metrics["predicted_by_family"]["identity"] == {"accept": 1}
    assert metrics["predicted_by_family"]["wrong_arg_value"] == {"abstain": 1}


def test_check_expectations_reports_each_verdict() -> None:
    metrics = {"identity_accept": {"n": 9, "d": 10, "rate": 0.9}}
    verdicts = check_expectations(
        metrics, (Expectation("identity_accept", ">=", 0.85),)
    )
    assert verdicts == {
        "identity_accept": {"value": 0.9, "target": ">= 0.85", "met": True}
    }


def test_check_expectations_flags_a_miss() -> None:
    metrics = {"wrong_arg_accept": {"n": 3, "d": 10, "rate": 0.3}}
    verdicts = check_expectations(
        metrics, (Expectation("wrong_arg_accept", "<=", 0.15),)
    )
    assert verdicts["wrong_arg_accept"]["met"] is False


# ---------------------------------------------------------------------------
# The pre-registered directional invariants, through the real engine
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def evaluated(tmp_path_factory) -> dict[str, dict]:
    conditions = build_conditions(tmp_path_factory.mktemp("degradation"))
    return {c.name: run_condition(c) for c in conditions}


def test_the_seven_conditions_are_built(evaluated) -> None:
    assert set(evaluated) == {
        "baseline",
        "truncated_honest",
        "truncated_redeclared",
        "stale_unbounded",
        "stale_immutable_lie",
        "stale_bounded",
        "cross_tenant",
    }


def test_baseline_meets_the_production_posture(evaluated) -> None:
    """Autonomy on verified reads, verification on writes.

    A2 reported pooled identity ACCEPT because assign/close misclassified as
    reads; with writes classified correctly the claimable posture is
    per-action-type, so the baseline invariant is too.
    """
    metrics = evaluated["baseline"]
    assert metrics["admission"]["status"] == "eligible"
    assert metrics["identity_accept_read"]["rate"] >= 0.85
    assert metrics["wrong_arg_accept"]["rate"] <= 0.15
    assert metrics["false_unsupported_on_valid"]["rate"] <= 0.02
    # Writes are not auto-accepted even when every argument is confirmed.
    assert metrics["identity_accept_write"]["rate"] <= 0.15


def test_honest_truncation_degrades_to_unknown_not_to_rejection(evaluated) -> None:
    """When the declaration no longer matches the bytes, the mechanism must
    lose its negative claims, not turn them against valid identifiers."""
    metrics = evaluated["truncated_honest"]
    assert metrics["false_unsupported_on_valid"]["rate"] == 0.0
    assert metrics["admission"]["status"] == "ineligible"


def test_false_redeclaration_rejects_valid_identifiers(evaluated) -> None:
    """The cost of a curator vouching for an incomplete export: valid
    identifiers are confidently rejected at about the removal fraction."""
    metrics = evaluated["truncated_redeclared"]
    assert metrics["false_unsupported_on_valid"]["rate"] >= 0.15
    assert metrics["admission"]["status"] == "eligible"


def test_redeclared_truncation_still_rejects_corrupted_values(evaluated) -> None:
    assert evaluated["truncated_redeclared"]["wrong_arg_accept"]["rate"] <= 0.15


def test_a_mutable_declaration_without_a_bound_is_refused_outright(evaluated) -> None:
    """Freshness is mandatory for mutable state: the unbounded-stale regime is
    no longer reachable by omission — only by a false immutability claim."""
    metrics = evaluated["stale_unbounded"]
    assert metrics["false_unsupported_on_valid"]["rate"] == 0.0
    assert metrics["admission"]["status"] == "ineligible"


def test_a_false_immutability_claim_rejects_post_snapshot_identifiers(
    evaluated,
) -> None:
    """Hash binding cannot catch a world that moved on; with freshness
    mandatory, reproducing that failure requires a curator to falsely declare
    mutable state immutable — the staleness twin of truncated_redeclared."""
    metrics = evaluated["stale_immutable_lie"]
    assert metrics["false_unsupported_on_valid"]["rate"] >= 0.15


def test_freshness_bound_catches_what_the_hash_cannot(evaluated) -> None:
    metrics = evaluated["stale_bounded"]
    assert metrics["false_unsupported_on_valid"]["rate"] == 0.0
    assert metrics["admission"]["status"] == "ineligible"


def test_no_foreign_tenant_identifier_is_accepted(evaluated) -> None:
    assert evaluated["cross_tenant"]["identity_accept"]["rate"] == 0.0


def test_every_condition_records_its_expectation_verdicts(evaluated) -> None:
    """The runner publishes misses as measured; the verdict block must exist
    for every condition so a miss cannot be silently dropped."""
    for name, metrics in evaluated.items():
        assert metrics["expectations"], name
        for verdict in metrics["expectations"].values():
            assert set(verdict) == {"value", "target", "met"}
