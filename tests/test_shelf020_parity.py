# SPDX-License-Identifier: BUSL-1.1
"""SHELF-020 builder parity test.

SHELF-020 records that the task\u2013tool semantics layer (ToolContract, TaskIntent,
goal_match, effect_prediction) is exercised only in the research/benchmark path
and is absent from /v1/execution.  This test is the minimum parity requirement
for Gate 1: the experiment runs through build_full_observation; this file
verifies that the fields build_full_observation inherits from build_observation
are identical to what build_observation produces on its own, and that the
execution-path observation builder (PolicyObservation.from_tool_call) agrees on
the safety-critical classifications for the same tool/metadata.

Gate 1 acceptance criterion: all assertions below pass.
SHELF-020 closure criterion (separate, later): /v1/execution/assess calls
build_full_observation with a registered contract bundle, and this file is
updated to test that path too.
"""
from __future__ import annotations

import dataclasses

import pytest

from remora.policy.observation import PolicyObservation
from remora.toolcall.routing.episode import RoutingEpisode
from remora.toolcall.routing.evaluate import build_full_observation, build_observation
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _episode(
    *,
    tool: str = "get_booking",
    task: str = "Show me booking B-104.",
    domain: str = "booking_management",
    untrusted: str = "",
    args: dict | None = None,
) -> RoutingEpisode:
    return RoutingEpisode(
        id="test-ep-001",
        source_dataset="test",
        source_commit="0000000",
        cluster_id="c-001",
        user_task=task,
        proposed_tool_name=tool,
        proposed_tool_args=args or {"booking_id": "B-104"},
        available_tools=(tool,),
        domain=domain,
        untrusted_context=untrusted or None,
    )


_REGISTRY = ToolRegistry(signatures={
    "get_booking":    ToolSignature(name="get_booking",    effect="read",  required_params=("booking_id",)),
    "cancel_booking": ToolSignature(name="cancel_booking", effect="write", required_params=("booking_id",)),
})


# ---------------------------------------------------------------------------
# Parity 1: build_full_observation inherits build_observation fields unchanged
#
# build_full_observation starts with obs = build_observation(episode, registry)
# and calls dataclasses.replace(obs, ...).  The fields set by build_observation
# must be identical in the full output — this is the contract that lets the
# experiment builder and the execution path share a common base.
# ---------------------------------------------------------------------------

_BASE_FIELDS = (
    "question",
    "domain",
    "action_type",
    "argument_tainted",
    "untrusted_controlled_arguments",
    "arguments_satisfiable",
)


@pytest.mark.parametrize("tool,expected_action_type", [
    ("get_booking", "read"),
    ("cancel_booking", "write"),
])
def test_full_observation_inherits_base_fields_from_build_observation(
    tool, expected_action_type
) -> None:
    ep = _episode(tool=tool)
    base = build_observation(ep, _REGISTRY)
    from remora.toolcall.routing.compatibility import StateIndex
    full = build_full_observation(ep, _REGISTRY, StateIndex({}))

    for field in _BASE_FIELDS:
        assert getattr(base, field) == getattr(full, field), (
            f"field {field!r} diverged: base={getattr(base, field)!r}, "
            f"full={getattr(full, field)!r}"
        )

    assert base.action_type == expected_action_type


# ---------------------------------------------------------------------------
# Parity 2: without contracts/intent, task-tool fields are None
#
# When build_full_observation is called with no contracts and no intent
# (the current experiment configuration), the task-tool fields must be None
# rather than fabricated.  None is the honest absence signal; any other value
# would inject a false signal into the policy engine.
# ---------------------------------------------------------------------------

def test_no_contracts_yields_null_task_tool_fields() -> None:
    ep = _episode()
    from remora.toolcall.routing.compatibility import StateIndex
    full = build_full_observation(ep, _REGISTRY, StateIndex({}), contracts=None, intent=None)

    assert full.tool_matches_goal is None, "tool_matches_goal must be None without contracts"
    assert full.expected_effect_matches is None, "expected_effect_matches must be None without contracts"


# ---------------------------------------------------------------------------
# Parity 3: execution-path builder agrees on safety-critical classifications
#
# The execution path (_observation in servers/execution_api.py) builds a
# PolicyObservation via PolicyObservation.from_tool_call with metadata from
# a server-side TOOL_REGISTRY dict.  For the same tool and equivalent metadata,
# the safety-critical fields (action_type, domain) must agree with what
# build_observation derives from a ToolRegistry with the same information.
#
# This is the cross-builder parity that justifies scoping experimental results
# to "builder X, parity-tested against the execution path on N observations."
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool,meta_action,expected", [
    ("get_booking",    "read",  "read"),
    ("cancel_booking", "write", "write"),
])
def test_execution_path_builder_agrees_on_action_type(
    tool, meta_action, expected
) -> None:
    ep = _episode(tool=tool)
    research_obs = build_observation(ep, _REGISTRY)

    execution_obs = PolicyObservation.from_tool_call(
        name=tool,
        arguments=ep.proposed_tool_args,
        risk_tier="low",
        domain=ep.domain,
        action_type=meta_action,   # from server-side registry, same as ToolRegistry
    )

    assert research_obs.action_type == execution_obs.action_type == expected, (
        f"action_type diverged: research={research_obs.action_type!r}, "
        f"execution={execution_obs.action_type!r}"
    )
    assert research_obs.domain == execution_obs.domain


def test_taint_propagates_consistently_across_builders() -> None:
    """Untrusted context must be flagged the same way regardless of builder."""
    ep = _episode(untrusted="injected payload")
    from remora.toolcall.routing.compatibility import StateIndex
    base = build_observation(ep, _REGISTRY)
    full = build_full_observation(ep, _REGISTRY, StateIndex({}))

    assert base.argument_tainted is True
    assert full.argument_tainted is True
    assert base.untrusted_controlled_arguments == full.untrusted_controlled_arguments
