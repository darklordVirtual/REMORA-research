# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the BFCL adapter (Track B-ext — external blind routing).

BFCL v3 live categories are real user-submitted tool-call tasks with full
function schemas (upstream: ShishirPatil/gorilla, Apache-2.0). The adapter
extracts native predicates only:

    tool_required   True for live_simple (a gold call is annotated),
                    False for live_irrelevance (no call is correct)
    call_in_gold_set  proposed name matches the annotated gold function

No state table exists whose completeness anyone can vouch for, so the
wrong-argument axis is *not judgeable* on this track — declared upfront, not
discovered after sealing (§29's lesson).
"""
from __future__ import annotations

from pathlib import Path

from remora.toolcall.routing.episode import Route
from remora.toolcall.routing.sources.bfcl import BfclAdapter, bfcl_registry

FIXTURES = Path(__file__).parent / "fixtures" / "routing_bench" / "bfcl"


def _adapter() -> BfclAdapter:
    return BfclAdapter(
        simple_path=FIXTURES / "live_simple.json",
        answers_path=FIXTURES / "live_simple_answers.json",
        irrelevance_path=FIXTURES / "live_irrelevance.json",
        commit="c15b2a15",
    )


def test_gold_call_episodes_route_accept() -> None:
    episodes = [e for e in _adapter().build_episodes() if e.id.endswith(":gold")]
    assert episodes
    for episode in episodes:
        assert episode.route is Route.ACCEPT
        assert episode.predicates.tool_required.value is True
        assert episode.predicates.call_in_gold_set.value is True
        assert episode.proposed_tool_name
        assert episode.proposed_tool_args


def test_gold_arguments_come_from_the_annotated_ground_truth() -> None:
    episode = next(
        e
        for e in _adapter().build_episodes()
        if e.id == "bfcl:live_simple_0-0-0:gold"
    )
    assert episode.proposed_tool_name == "get_user_info"
    assert episode.proposed_tool_args["user_id"] == 7890


def test_irrelevance_episodes_route_abstain_with_no_synthesized_call() -> None:
    """No call is correct, and the adapter must not author one (tau2
    precedent: synthesizing a call would author the test)."""
    episodes = [e for e in _adapter().build_episodes() if ":irrelevance" in e.id]
    assert episodes
    for episode in episodes:
        assert episode.route is Route.ABSTAIN
        assert episode.predicates.tool_required.value is False
        assert episode.proposed_tool_name is None


def test_substituted_negative_is_unlabelled_and_known_wrong() -> None:
    """A call from another task's gold set: knowably wrong, remedy unknown."""
    episodes = [
        e for e in _adapter().build_episodes() if e.id.endswith(":substituted")
    ]
    assert episodes
    for episode in episodes:
        assert episode.route is None
        assert episode.predicates.call_in_gold_set.value is False


def test_episode_ids_carry_the_upstream_task_id() -> None:
    for episode in _adapter().build_episodes():
        assert episode.cluster_id.startswith("bfcl:live_")


def test_registry_extracts_required_params_from_schemas() -> None:
    registry = bfcl_registry(
        [FIXTURES / "live_simple.json", FIXTURES / "live_irrelevance.json"]
    )
    assert registry.signatures["get_user_info"].required_params == ("user_id",)


def test_build_is_deterministic() -> None:
    a = [e.to_jsonl() for e in _adapter().build_episodes()]
    b = [e.to_jsonl() for e in _adapter().build_episodes()]
    assert a == b
