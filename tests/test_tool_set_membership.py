# SPDX-License-Identifier: BUSL-1.1
"""Tests for the tool-set membership guard (open risk B fix).

Verifies that proposed_tool_name not in available_tools routes to VERIFY,
while a tool in the set is not blocked by this guard alone.
"""
from __future__ import annotations

import pytest
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason


engine = RemoraDecisionEngine(low_consequence_accept=True)


def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation(question="test", **kwargs)


class TestToolNotInAvailableSet:

    def test_tool_not_in_set_routes_to_verify(self):
        obs = _obs(
            tool_not_in_available_set=True,
            proposed_tool_name="search_flights",
            action_type="read",
            risk_tier="low",
            argument_values_grounded=True,
        )
        report = engine.decide(obs)
        assert report.action == DecisionAction.VERIFY
        assert DecisionReason.TOOL_NOT_IN_AVAILABLE_SET in report.reasons

    def test_tool_in_set_not_blocked_by_this_guard(self):
        obs = _obs(
            tool_not_in_available_set=False,
            proposed_tool_name="get_weather",
            action_type="read",
            risk_tier="low",
            argument_values_grounded=True,
        )
        report = engine.decide(obs)
        assert DecisionReason.TOOL_NOT_IN_AVAILABLE_SET not in report.reasons

    def test_tool_not_in_set_none_passes_through(self):
        """None means available_tools was not supplied — must not block."""
        obs = _obs(
            tool_not_in_available_set=None,
            proposed_tool_name="get_weather",
            action_type="read",
            risk_tier="low",
            argument_values_grounded=True,
        )
        report = engine.decide(obs)
        assert DecisionReason.TOOL_NOT_IN_AVAILABLE_SET not in report.reasons

    def test_tool_not_in_set_beats_grounded_read_accept(self):
        """Grounded + read + low-consequence does not override tool-set guard."""
        obs = _obs(
            tool_not_in_available_set=True,
            proposed_tool_name="get_forecast",
            action_type="read",
            risk_tier="low",
            argument_values_grounded=True,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT

    def test_explain_decide_parity_for_tool_not_in_set(self):
        """explain() must emit the same reason as decide()."""
        obs = _obs(
            tool_not_in_available_set=True,
            proposed_tool_name="search_flights",
            action_type="read",
        )
        report = engine.decide(obs)
        trace = engine.explain(obs)
        fired = {r.rule for r in trace.rule_evaluations if r.triggered}
        assert "tool_not_in_available_set" in fired
        assert DecisionReason.TOOL_NOT_IN_AVAILABLE_SET in report.reasons

    def test_build_full_observation_populates_field(self):
        """build_full_observation must set tool_not_in_available_set correctly."""
        import json, sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from remora.toolcall.routing.compatibility import StateIndex
        from remora.toolcall.routing.episode import RoutingEpisode
        from remora.toolcall.routing.evaluate import build_full_observation
        from remora.toolcall.routing.tool_registry import ToolRegistry

        # Tool NOT in available_tools
        raw = {
            "id": "test:0", "source_dataset": "test", "source_commit": "test",
            "cluster_id": "c0", "user_task": "Check if flight LH-400 is delayed.",
            "available_tools": ["get_flight_status"],
            "untrusted_context": None, "proposed_tool_name": "search_flights",
            "proposed_tool_args": {"flight_number": "LH-400"},
            "domain": "travel", "args_statically_unavailable": False,
        }
        ep = RoutingEpisode.from_json_dict(raw)
        obs = build_full_observation(ep, ToolRegistry({}), StateIndex.from_values(set()))
        assert obs.tool_not_in_available_set is True

        # Tool IN available_tools
        raw2 = {**raw, "proposed_tool_name": "get_flight_status"}
        ep2 = RoutingEpisode.from_json_dict(raw2)
        obs2 = build_full_observation(ep2, ToolRegistry({}), StateIndex.from_values(set()))
        assert obs2.tool_not_in_available_set is False

        # No available_tools → None
        raw3 = {**raw, "available_tools": []}
        ep3 = RoutingEpisode.from_json_dict(raw3)
        obs3 = build_full_observation(ep3, ToolRegistry({}), StateIndex.from_values(set()))
        assert obs3.tool_not_in_available_set is None
