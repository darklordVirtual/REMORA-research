# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Runtime-surface evidence must not overstate what a registry proves."""
from __future__ import annotations

from remora.toolcall.runtime_surface import (
    RuntimeTool,
    RuntimeToolSurface,
    SurfaceVerdict,
    evaluate_surface,
    observe_dispatcher_registry,
)


def _tool(name: str, digest: str = "hash-a") -> RuntimeTool:
    return RuntimeTool(name, "mcp", True, True, digest)


def _surface(*tools: RuntimeTool, complete: bool = True,
             runtime: str = "agent-process") -> RuntimeToolSurface:
    return RuntimeToolSurface(runtime, "agent-runtime", complete, tuple(tools))


def test_extra_callable_tool_is_mismatch_even_when_governed_call_matches() -> None:
    report = evaluate_surface(
        _surface(_tool("update_ticket"), _tool("shell", "hash-shell")),
        {"update_ticket": "hash-a"}, expected_runtime_identity="agent-process",
    )
    assert report.verdict is SurfaceVerdict.MISMATCH
    assert report.unexpected_tools == ("shell",)


def test_metadata_or_registry_only_cannot_establish_complete_agent_surface() -> None:
    surface = RuntimeToolSurface("agent-process", "gateway-metadata", True,
                                 (_tool("update_ticket"),))
    report = evaluate_surface(surface, {"update_ticket": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert "observer_not_agent_runtime" in report.reasons


def test_same_names_from_wrong_process_cannot_establish_surface() -> None:
    report = evaluate_surface(_surface(_tool("update_ticket"), runtime="cli"),
                              {"update_ticket": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert "runtime_identity_mismatch" in report.reasons


def test_extra_name_from_wrong_process_is_not_a_runtime_mismatch() -> None:
    report = evaluate_surface(_surface(_tool("shell"), runtime="cli"),
                              {}, expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert report.unexpected_tools == ()


def test_unknown_offered_state_cannot_be_treated_as_false_or_complete() -> None:
    tool = RuntimeTool("update_ticket", "dispatcher", None, None, "hash-a")
    report = evaluate_surface(_surface(tool), {"update_ticket": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert "tool_visibility_unknown" in report.reasons


def test_matching_complete_snapshot_has_only_observation_level_verdict() -> None:
    report = evaluate_surface(_surface(_tool("a")), {"a": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.MATCHED_OBSERVATION


def test_callable_without_toolspec_identity_is_not_established() -> None:
    report = evaluate_surface(_surface(_tool("a", digest=None)),
                              {"a": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert "toolspec_identity_unknown" in report.reasons


def test_complete_agent_observation_detects_missing_and_changed_spec() -> None:
    report = evaluate_surface(_surface(_tool("a", "wrong")),
                              {"a": "right", "b": "hash-b"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.MISMATCH
    assert report.missing_tools == ("b",)
    assert report.identity_mismatches == ("a",)


def test_dispatcher_adapter_reports_only_registration_and_abstains() -> None:
    class Dispatcher:
        def registered_tool_names(self):
            return ("a",)

    surface = observe_dispatcher_registry(Dispatcher(), runtime_identity="executor")
    assert surface.tools[0].registered is True
    assert surface.tools[0].offered_to_agent is None
    assert surface.complete is False
    report = evaluate_surface(surface, {"a": "hash-a"},
                              expected_runtime_identity="executor")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED


def test_configured_and_discovered_do_not_imply_agent_visibility() -> None:
    tool = RuntimeTool("a", "mcp", None, None, "hash-a",
                       configured=True, discovered=True, registered=None)
    assert tool.configured is True
    assert tool.discovered is True
    report = evaluate_surface(_surface(tool), {"a": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED


def test_duplicate_tool_ids_are_refused() -> None:
    import pytest

    with pytest.raises(ValueError, match="duplicate"):
        _surface(_tool("a"), _tool("a"))


def test_committed_negative_cases_are_reproducible() -> None:
    import json
    from pathlib import Path

    cases = json.loads((Path(__file__).resolve().parents[1] /
                        "artifacts/runtime_surface/negative_cases_v1.json")
                       .read_text(encoding="utf-8"))
    for case in cases["cases"]:
        surface = RuntimeToolSurface(
            case["runtime_identity"], case["observation_source"],
            case["complete"],
            tuple(RuntimeTool(**tool) for tool in case["tools"]),
        )
        report = evaluate_surface(
            surface, case["governed_tools"],
            expected_runtime_identity=case["expected_runtime_identity"],
        )
        assert report.verdict.value == case["expected_verdict"], case["id"]
        assert list(report.unexpected_tools) == case["unexpected_tools"], case["id"]


def test_incomplete_agent_snapshot_never_reports_absence_as_missing() -> None:
    report = evaluate_surface(_surface(complete=False), {"update_ticket": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert "surface_incomplete" in report.reasons
    assert report.missing_tools == ()


def test_incomplete_agent_snapshot_still_reports_an_observed_extra_tool() -> None:
    report = evaluate_surface(
        _surface(_tool("update_ticket"), _tool("shell", "hash-shell"), complete=False),
        {"update_ticket": "hash-a"}, expected_runtime_identity="agent-process",
    )
    assert report.verdict is SurfaceVerdict.MISMATCH
    assert report.unexpected_tools == ("shell",)
    assert report.missing_tools == ()
    assert "surface_incomplete" in report.reasons


def test_incomplete_agent_snapshot_cannot_match_even_when_every_tool_agrees() -> None:
    report = evaluate_surface(_surface(_tool("update_ticket"), complete=False),
                              {"update_ticket": "hash-a"},
                              expected_runtime_identity="agent-process")
    assert report.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert report.reasons == ("surface_incomplete",)
