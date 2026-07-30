# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the ToolSandbox adapter (routing benchmark v1).

ToolSandbox is under Apple's own license, not an OSI license, so no upstream
content — not even a test fixture — is committed. The unit tests parse
``tests/fixtures/routing_bench/toolsandbox_shape.py``, original REMORA content
that reproduces the parsed shape. One integration test runs against the real
cached module when it is present locally and skips otherwise.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.toolcall.routing.episode import Route
from remora.toolcall.routing.leakage import check_all
from remora.toolcall.routing.sources.toolsandbox import ToolSandboxAdapter

SHAPE = Path(__file__).parent / "fixtures" / "routing_bench" / "toolsandbox_shape.py"
REAL_CACHE = (
    Path(__file__).parent.parent
    / ".cache" / "routing_bench" / "toolsandbox"
    / "insufficient_information_scenarios.py"
)
COMMIT = "main"


@pytest.fixture(scope="module")
def episodes():
    return ToolSandboxAdapter(paths=[SHAPE], commit=COMMIT).build_episodes()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parses_every_scenario_extension(episodes) -> None:
    assert len(episodes) == 3
    for ep in episodes:
        ep.validate()


def test_user_message_becomes_the_task_text(episodes) -> None:
    ep = next(e for e in episodes if "altitude" in e.id)
    assert ep.user_task == "What altitude am I at?"


def test_allow_list_becomes_available_tools(episodes) -> None:
    ep = next(e for e in episodes if "neighbour" in e.id)
    assert ep.available_tools == ("search_contact_by_name", "search_directory")


def test_proposed_call_is_a_mined_tool_from_the_allow_list(episodes) -> None:
    """A minefielded, allow-listed tool is what a naive agent would actually call."""
    ep = next(e for e in episodes if "altitude" in e.id)
    assert ep.proposed_tool_name == "search_altitude_by_coordinates"


# ---------------------------------------------------------------------------
# Predicates — this source's whole purpose is the ABSTAIN axis
# ---------------------------------------------------------------------------

def test_empty_milestones_yield_abstain(episodes) -> None:
    """milestones == [] is ToolSandbox stating that no tool call is correct."""
    abstains = [e for e in episodes if e.route is Route.ABSTAIN]
    assert len(abstains) == 2
    for ep in abstains:
        assert ep.predicates.tool_required.value is False
        assert ep.matched_row == 4


def test_information_missing_is_left_silent_not_true(episodes) -> None:
    """ToolSandbox insufficiency is not the same claim as tau2 unknown_info.

    tau2's unknown_info means the user could supply the fact if asked, which is
    machine-resolvable and routes to VERIFY. ToolSandbox insufficiency means the
    fact is unobtainable with the available tools, which routes to ABSTAIN.
    Setting information_missing=True here would make row 3 fire before row 4 and
    silently relabel every unanswerable task as resolvable.
    """
    for ep in episodes:
        assert ep.predicates.information_missing.value is None


def test_non_empty_milestones_are_not_abstain(episodes) -> None:
    """A task that does need a tool must not be labelled ABSTAIN."""
    ep = next(e for e in episodes if "reminder" in e.id)
    assert ep.predicates.tool_required.value is True
    assert ep.route is not Route.ABSTAIN


def test_predicates_this_source_is_silent_about_are_none(episodes) -> None:
    for ep in episodes:
        assert ep.predicates.policy_forbids.value is None
        assert ep.predicates.originates_from_untrusted.value is None


# ---------------------------------------------------------------------------
# Licensing posture
# ---------------------------------------------------------------------------

def test_episodes_are_marked_non_redistributable(episodes) -> None:
    """Nothing derived from ToolSandbox may ever reach data/."""
    for ep in episodes:
        assert ep.redistributable is False


# ---------------------------------------------------------------------------
# Determinism, leakage, and the real module
# ---------------------------------------------------------------------------

def test_derivation_is_deterministic() -> None:
    a = ToolSandboxAdapter(paths=[SHAPE], commit=COMMIT).build_episodes()
    b = ToolSandboxAdapter(paths=[SHAPE], commit=COMMIT).build_episodes()
    assert [e.to_jsonl() for e in a] == [e.to_jsonl() for e in b]


def test_episodes_pass_the_leakage_gate(episodes) -> None:
    assert check_all(episodes) == len(episodes)


@pytest.mark.skipif(
    not REAL_CACHE.exists(),
    reason="ToolSandbox source cache absent; run scripts/build_routing_bench.py --fetch",
)
def test_parses_the_real_upstream_module() -> None:
    """Guards against upstream refactoring silently reducing the episode count.

    A parser that returns fewer episodes rather than failing would shrink the
    benchmark without anyone noticing.
    """
    episodes = ToolSandboxAdapter(paths=[REAL_CACHE], commit=COMMIT).build_episodes()
    assert len(episodes) == 28, (
        f"expected 28 ScenarioExtension calls, parsed {len(episodes)}; "
        "upstream shape may have changed"
    )
    abstains = [e for e in episodes if e.route is Route.ABSTAIN]
    assert len(abstains) == 16
