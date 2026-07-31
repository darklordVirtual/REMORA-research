# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the coverage admission gate (§29 remediation).

§29 spent a blind set that could not test its hypothesis. The decisive test here
is that this gate refuses that exact set: a check that would not have caught the
failure it was written for is not a gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.toolcall.routing.admission import (
    MINIMUM_JUDGEABLE_FRACTION,
    assess_admission,
)
from remora.toolcall.routing.compatibility import CoverageScope, StateIndex
from remora.toolcall.routing.episode import RoutingEpisode

REPO = Path(__file__).parent.parent
BANKING = REPO / "data" / "routing_bench_holdout_a" / "banking_holdout_a.jsonl"
CACHE = REPO / ".cache" / "routing_bench"


def _episode(family: str, args: dict, ident: str) -> RoutingEpisode:
    return RoutingEpisode(
        id=f"t:{ident}",
        source_dataset="t",
        source_commit="0" * 40,
        cluster_id="c",
        user_task="task",
        available_tools=(),
        untrusted_context=None,
        proposed_tool_name="get_x",
        proposed_tool_args=args,
        domain="d",
        notes=(f"mutation:{family}",),
    )


def test_threshold_is_pre_registered_above_the_review_floor() -> None:
    assert MINIMUM_JUDGEABLE_FRACTION == 0.90


def test_an_index_with_no_coverage_is_ineligible() -> None:
    result = assess_admission(
        [_episode("identity", {"user_id": "u1"}, "a")], StateIndex(frozenset(), ())
    )
    assert result.status == "ineligible"
    assert result.observed_judgeable_fraction == 0.0


def test_a_fully_covered_set_is_eligible() -> None:
    scope = (CoverageScope("d", frozenset({"user_id"}), closed_world=True),)
    state = StateIndex(frozenset({f"u{i}" for i in range(40)}), scope)
    episodes = [
        _episode("identity" if i % 2 else "wrong_arg_value", {"user_id": f"u{i}"}, str(i))
        for i in range(40)
    ]
    result = assess_admission(episodes, state)
    assert result.status == "eligible"
    assert result.eligible_argument_roles == ("user_id",)


def test_a_rare_role_cannot_carry_the_aggregate() -> None:
    """A role with too few judgeable episodes is excluded even at 100%."""
    scope = (CoverageScope("d", frozenset({"user_id"}), closed_world=True),)
    state = StateIndex(frozenset({"u0", "u1"}), scope)
    episodes = [_episode("identity", {"user_id": f"u{i}"}, str(i)) for i in range(2)]
    result = assess_admission(episodes, state)
    assert result.status == "ineligible"
    assert "user_id" in result.excluded_argument_roles


@pytest.mark.skipif(not BANKING.exists(), reason="track A artefact absent")
def test_the_gate_would_have_refused_track_a() -> None:
    """The §29 failure, as a regression test.

    This is the whole point of the gate: it must reject the set that was
    actually sealed and spent without testing its hypothesis.
    """
    episodes = [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in BANKING.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    state = StateIndex.from_json_files(sorted((CACHE / "tau2_db").glob("*.json")))
    result = assess_admission(episodes, state)
    assert result.status == "ineligible", (
        "the gate admitted the set §29 proved untestable"
    )


def test_the_result_is_machine_readable() -> None:
    payload = json.loads(assess_admission([], StateIndex(frozenset(), ())).to_json())
    assert set(payload) >= {
        "status",
        "minimum_judgeable_fraction",
        "observed_judgeable_fraction",
        "eligible_argument_roles",
        "excluded_argument_roles",
        "per_role",
    }


def test_the_gate_reads_no_predictions() -> None:
    """Running admission must not spend the set.

    Asserted structurally rather than by convention: the module may not
    reference the engine or any evaluation entry point.
    """
    source = (REPO / "remora" / "toolcall" / "routing" / "admission.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "RemoraDecisionEngine",
        "score_routing",
        "evaluate_episodes",
        "build_full_observation",
    ):
        assert forbidden not in source, f"admission gate references {forbidden}"
