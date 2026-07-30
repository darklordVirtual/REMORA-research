# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the tau2-bench adapter (routing benchmark v1).

Runs against committed fixture excerpts in tests/fixtures/routing_bench/tau2/,
never the network. The fixtures are real upstream tasks chosen to cover each
predicate case; see their ATTRIBUTION.md.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.toolcall.routing.episode import Route
from remora.toolcall.routing.leakage import check_all
from remora.toolcall.routing.sources.tau2 import (
    REFUSAL_PATTERN,
    REFUSAL_PATTERN_VERSION,
    Tau2Adapter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "routing_bench" / "tau2"
COMMIT = "363133ada1936491fb5bcec33cd62c3518a99f65"


@pytest.fixture(scope="module")
def episodes():
    return Tau2Adapter(root=FIXTURES, commit=COMMIT).build_episodes()


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------

def test_adapter_produces_episodes(episodes) -> None:
    assert episodes
    for ep in episodes:
        ep.validate()


def test_every_episode_records_source_provenance(episodes) -> None:
    for ep in episodes:
        assert ep.source_dataset == "tau2"
        assert ep.source_commit == COMMIT
        assert ep.cluster_id
        assert ep.domain in {"airline", "retail"}


def test_cluster_id_groups_episodes_from_one_upstream_task(episodes) -> None:
    """Several episodes derive from one task, so they are not independent draws."""
    clusters = {ep.cluster_id for ep in episodes}
    assert len(clusters) < len(episodes), (
        "expected multiple episodes per upstream task; cluster correction would "
        "be a no-op otherwise"
    )


# ---------------------------------------------------------------------------
# Predicate extraction
# ---------------------------------------------------------------------------

def test_gold_action_episode_is_accept(episodes) -> None:
    """A gold action with no blocker present must label ACCEPT via row 5."""
    accepts = [e for e in episodes if e.route is Route.ACCEPT]
    assert accepts
    for ep in accepts:
        assert ep.predicates.tool_required.value is True
        assert ep.predicates.call_in_gold_set.value is True
        assert ep.proposed_tool_name is not None
        assert ep.matched_row == 5


def test_gold_action_predicate_cites_its_source_field(episodes) -> None:
    ep = next(e for e in episodes if e.route is Route.ACCEPT)
    assert ep.predicates.tool_required.source_field == "evaluation_criteria.actions"
    assert ep.predicates.call_in_gold_set.source_field == "evaluation_criteria.actions[].name"


def test_unknown_info_produces_verify(episodes) -> None:
    """unknown_info is tau2's native statement that the user lacks information."""
    verifies = [e for e in episodes if e.route is Route.VERIFY]
    assert verifies, "fixtures must include at least one unknown_info task"
    for ep in verifies:
        assert ep.predicates.information_missing.value is True
        assert (
            ep.predicates.information_missing.source_field
            == "user_scenario.instructions.unknown_info"
        )


def test_refusal_task_escalates_with_no_proposed_call(episodes) -> None:
    """Refusal tasks carry no natively-annotated call, so none is synthesized."""
    escalates = [e for e in episodes if e.route is Route.ESCALATE]
    assert escalates, "fixtures must include at least one refusal task"
    for ep in escalates:
        assert ep.predicates.policy_forbids.value is True
        assert ep.proposed_tool_name is None
        assert ep.matched_row == 1


def test_policy_forbids_records_the_matched_assertion_verbatim(episodes) -> None:
    """Every firing of the one text-matching predicate must be auditable."""
    for ep in episodes:
        pv = ep.predicates.policy_forbids
        if pv.value is True:
            assert pv.matched_text, f"{ep.id} fired policy_forbids without evidence"
            assert REFUSAL_PATTERN.search(pv.matched_text)


def test_predicates_the_source_is_silent_about_are_none(episodes) -> None:
    """tau2 does not model untrusted origin; it must be None, never False."""
    for ep in episodes:
        assert ep.predicates.originates_from_untrusted.value is None


# ---------------------------------------------------------------------------
# Negative (wrong-call) episodes
# ---------------------------------------------------------------------------

def test_wrong_call_episodes_are_unlabelled(episodes) -> None:
    """call_in_gold_set=False falls through the table by design."""
    wrong = [
        e for e in episodes
        if e.predicates.call_in_gold_set.value is False
        and e.predicates.information_missing.value is not True
    ]
    assert wrong, "expected substituted wrong-call episodes"
    for ep in wrong:
        assert ep.route is None
        assert ep.matched_row is None


def test_substituted_call_comes_from_a_different_task(episodes) -> None:
    """A substitution that reused the task's own gold call would be no negative."""
    by_cluster: dict[str, set[str]] = {}
    for ep in episodes:
        if ep.predicates.call_in_gold_set.value is True and ep.proposed_tool_name:
            by_cluster.setdefault(ep.cluster_id, set()).add(ep.proposed_tool_name)
    for ep in episodes:
        if ep.predicates.call_in_gold_set.value is False and ep.proposed_tool_name:
            assert ep.proposed_tool_name not in by_cluster.get(ep.cluster_id, set()), (
                f"{ep.id}: substituted call is in its own task's gold set"
            )


# ---------------------------------------------------------------------------
# Determinism and leakage
# ---------------------------------------------------------------------------

def test_derivation_is_deterministic() -> None:
    """Two builds must produce byte-identical JSONL — the refresh check depends on it."""
    a = Tau2Adapter(root=FIXTURES, commit=COMMIT).build_episodes()
    b = Tau2Adapter(root=FIXTURES, commit=COMMIT).build_episodes()
    assert [e.to_jsonl() for e in a] == [e.to_jsonl() for e in b]


def test_episodes_pass_the_leakage_gate(episodes) -> None:
    assert check_all(episodes) == len(episodes)


def test_refusal_pattern_version_is_pinned() -> None:
    assert REFUSAL_PATTERN_VERSION == "1"
