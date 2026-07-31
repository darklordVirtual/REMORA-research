# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the AgentDojo adapter (routing benchmark v1).

Runs against committed fixture excerpts. AgentDojo is MIT, so excerpts may be
redistributed with attribution; see the header of each fixture file.

AgentDojo defines tasks as Python classes, so the adapter AST-parses the source
rather than importing the package, which would pull in its model-client
dependencies for no benefit.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.toolcall.routing.episode import Route
from remora.toolcall.routing.leakage import check_all
from remora.toolcall.routing.sources.agentdojo import AgentDojoAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "routing_bench" / "agentdojo"
REAL_CACHE = Path(__file__).parent.parent / ".cache" / "routing_bench" / "agentdojo"
COMMIT = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"


@pytest.fixture(scope="module")
def episodes():
    return AgentDojoAdapter(root=FIXTURES, commit=COMMIT).build_episodes()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parses_user_and_injection_tasks(episodes) -> None:
    assert len(episodes) == 4  # 2 user tasks + 2 injection tasks
    for ep in episodes:
        ep.validate()


def test_user_task_prompt_becomes_the_task_text(episodes) -> None:
    user_eps = [e for e in episodes if ":user:" in e.id]
    assert len(user_eps) == 2
    for ep in user_eps:
        assert ep.user_task
        assert ep.user_task != ep.id


def test_ground_truth_function_names_are_extracted(episodes) -> None:
    """Function names are static literals even where argument values are not."""
    ep = next(e for e in episodes if ":user:" in e.id)
    assert ep.proposed_tool_name
    assert ep.proposed_tool_name in ep.available_tools


def test_arguments_are_marked_statically_unavailable(episodes) -> None:
    """ground_truth() computes arguments at runtime; the limitation is in the data.

    AgentDojo builds args from the environment, e.g.
    FunctionCall(function="send_money", args={"subject": ... self.get_x(env)}).
    Recording this as a field keeps the caveat out of the design doc only.
    """
    for ep in episodes:
        assert ep.args_statically_unavailable is True
        assert ep.proposed_tool_args == {}


# ---------------------------------------------------------------------------
# Predicates — this source's purpose is the untrusted-origin axis
# ---------------------------------------------------------------------------

def test_injection_task_escalates_via_untrusted_origin(episodes) -> None:
    """An injected goal is untrusted content; it must never authorize a call."""
    injections = [e for e in episodes if ":injection:" in e.id]
    assert len(injections) == 2
    for ep in injections:
        assert ep.predicates.originates_from_untrusted.value is True
        assert ep.route is Route.ESCALATE
        assert ep.matched_row == 2
        assert ep.untrusted_context


def test_user_task_is_not_marked_untrusted(episodes) -> None:
    """The benign arm must be False, not None: AgentDojo does annotate this."""
    for ep in episodes:
        if ":user:" in ep.id:
            assert ep.predicates.originates_from_untrusted.value is False


def test_benign_user_task_accepts(episodes) -> None:
    user_eps = [e for e in episodes if ":user:" in e.id]
    for ep in user_eps:
        assert ep.predicates.tool_required.value is True
        assert ep.predicates.call_in_gold_set.value is True
        assert ep.route is Route.ACCEPT


def test_injection_and_user_episodes_are_separate_clusters(episodes) -> None:
    assert len({e.cluster_id for e in episodes}) == 4


# ---------------------------------------------------------------------------
# Determinism, leakage, and the real suites
# ---------------------------------------------------------------------------

def test_derivation_is_deterministic() -> None:
    a = AgentDojoAdapter(root=FIXTURES, commit=COMMIT).build_episodes()
    b = AgentDojoAdapter(root=FIXTURES, commit=COMMIT).build_episodes()
    assert [e.to_jsonl() for e in a] == [e.to_jsonl() for e in b]


def test_episodes_pass_the_leakage_gate(episodes) -> None:
    assert check_all(episodes) == len(episodes)


@pytest.mark.skipif(
    not (REAL_CACHE / "banking" / "user_tasks.py").exists(),
    reason="AgentDojo source cache absent; run scripts/build_routing_bench.py --fetch",
)
def test_parses_the_real_suites() -> None:
    """Guards against upstream refactoring silently shrinking the benchmark."""
    episodes = AgentDojoAdapter(root=REAL_CACHE, commit=COMMIT).build_episodes()
    user_eps = [e for e in episodes if ":user:" in e.id]
    injections = [e for e in episodes if ":injection:" in e.id]
    assert len(user_eps) == 86, f"expected 86 user tasks, parsed {len(user_eps)}"
    assert len(injections) == 27, f"expected 27 injection tasks, parsed {len(injections)}"
    # travel InjectionTask6 builds its target call dynamically; it is kept with
    # no proposed call rather than dropped, so the untrusted axis stays whole.
    dynamic = [e for e in injections if e.proposed_tool_name is None]
    assert len(dynamic) == 1
    assert all(e.route is Route.ESCALATE for e in dynamic)
