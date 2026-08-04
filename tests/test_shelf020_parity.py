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

Gate 1 acceptance criterion: all assertions below pass (Parity 1-3).
SHELF-020 closure criterion: /v1/execution/assess calls build_full_observation
with a registered contract bundle — Parity 4 below tests that path: with
REMORA_SEMANTIC_BUNDLE_MODULE configured, every semantic field of the
execution-path observation is byte-identical to what build_full_observation
produces for the equivalent episode, so the system under test is the system
enforced.
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


# ---------------------------------------------------------------------------
# Parity 4 (SHELF-020 closure): the execution path IS build_full_observation
#
# With a registered semantic bundle, /v1/execution builds its observation
# through build_full_observation. This test drives the server-side builder
# (_observation_with_context) and an independently-constructed equivalent
# episode through the same declarations, and requires every semantic field to
# be identical. A hand-assembled field in the execution path — the exact
# defect SHELF-020 records — diverges here.
# ---------------------------------------------------------------------------

#: The fields build_full_observation is authoritative for. The execution path
#: may overlay executive metadata (risk tier, target environment, session
#: binding) but never these.
_SEMANTIC_FIELDS = (
    "argument_tainted",
    "untrusted_controlled_arguments",
    "arguments_satisfiable",
    "argument_values_supported",
    "argument_values_grounded",
    "missing_required_arguments",
    "argument_resolver_tools",
    "proposed_tool_name",
    "unvalidated_required_arguments",
    "tool_not_in_available_set",
    "tool_matches_goal",
    "expected_effect_matches",
)

_INTENT_TASK = "Read the telemetry for asset P-1."


@pytest.fixture()
def execution_semantic_path(monkeypatch, tmp_path):
    import json

    intent_file = tmp_path / "workflow_intents.json"
    intent_file.write_text(json.dumps({
        "wo-1": {
            "task_text": _INTENT_TASK,
            "operation": "read",
            "resource_type": "telemetry",
            "requested_effect": "read",
            "target_entities": [],
            "source_spans": ["telemetry"],
            "action_spans": ["read the telemetry"],
        },
    }), encoding="utf-8")
    monkeypatch.setenv(
        "REMORA_SEMANTIC_BUNDLE_MODULE", "servers.semantic_bundle_research"
    )
    monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", str(intent_file))
    import servers.execution_api as exec_mod

    exec_mod._reset_semantic_bundle()
    yield exec_mod
    exec_mod._reset_semantic_bundle()


@pytest.mark.parametrize("tool,args,intent_ref", [
    ("read_telemetry", {}, "wo-1"),
    ("read_telemetry", {}, None),
    ("store_artifact", {"artifact_id": "a-1", "content": {"x": 1}}, "wo-1"),
])
def test_execution_path_semantic_fields_come_from_build_full_observation(
    execution_semantic_path, tool, args, intent_ref
) -> None:
    exec_mod = execution_semantic_path
    from servers.semantic_bundle_research import build_semantic_bundle, resolve_intent

    req = exec_mod.ToolCallRequest(
        tool_name=tool, arguments=args, intent_ref=intent_ref
    )
    obs, context = exec_mod._observation_with_context(req, "acme")

    bundle = build_semantic_bundle()
    resolved = resolve_intent(intent_ref) if intent_ref else None
    registry_entry = exec_mod.TOOL_REGISTRY[tool]
    episode = RoutingEpisode(
        id=f"exec:acme:{tool}",
        source_dataset="execution_api",
        source_commit="",
        cluster_id="exec:acme",
        user_task=resolved.task_text if resolved else "",
        available_tools=tuple(sorted(bundle.registry.signatures)),
        untrusted_context=None,
        proposed_tool_name=tool,
        proposed_tool_args=dict(args),
        domain=str(registry_entry["domain"]),
    )
    full = build_full_observation(
        episode,
        bundle.registry,
        bundle.state,
        validators=None,
        contracts=bundle.contracts,
        intent=resolved.intent if resolved else None,
    )

    for field in _SEMANTIC_FIELDS:
        assert getattr(obs, field) == getattr(full, field), (
            f"field {field!r} diverged from build_full_observation: "
            f"execution={getattr(obs, field)!r}, builder={getattr(full, field)!r}"
        )
    assert context["tool_matches_goal"] == full.tool_matches_goal
    assert context["tool_contract_bundle_hash"] == bundle.bundle_hash


def test_execution_path_goal_match_is_established_only_by_the_builder(
    execution_semantic_path,
) -> None:
    """The matched read call reaches True through the builder's own clauses —
    and the same call without an intent reference stays None. Nothing in the
    request body can move this field (the wiring tests prove request extras
    are ignored; this proves the builder is the only True source)."""
    exec_mod = execution_semantic_path
    with_intent = exec_mod.ToolCallRequest(
        tool_name="read_telemetry", arguments={}, intent_ref="wo-1"
    )
    without_intent = exec_mod.ToolCallRequest(tool_name="read_telemetry", arguments={})

    obs_with, ctx_with = exec_mod._observation_with_context(with_intent, "acme")
    obs_without, ctx_without = exec_mod._observation_with_context(without_intent, "acme")

    assert obs_with.tool_matches_goal is True
    assert ctx_with["intent_authority_hash"] != ""
    assert obs_without.tool_matches_goal is None
    assert ctx_without["intent_authority_hash"] == ""
