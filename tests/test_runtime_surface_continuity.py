# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A content identity must change for capability changes, not observation time."""
from dataclasses import replace

import pytest

from remora.toolcall.runtime_surface import (
    RuntimeTool, RuntimeToolSurface, SurfaceVerdict, compare_surfaces,
)


def tool(name="a", **kwargs):
    return replace(RuntimeTool(name, "native", True, True, "a" * 64,
                               registered=True), **kwargs)


def surface(*tools, **kwargs):
    return RuntimeToolSurface("process-1", "agent-runtime", True, tools, **kwargs)


def test_identity_is_independent_of_enumeration_order_and_timestamp():
    first = surface(tool("a"), tool("b"), observed_at="2026-09-27T10:00:00Z")
    second = surface(tool("b"), tool("a"), observed_at="2026-09-27T11:00:00Z")
    assert first.digest() == second.digest()


@pytest.mark.parametrize("change", [
    {"argument_schema_json": '{"type":"object","required":["target"]}'},
    {"credential_scope": ("admin",)}, {"allowed_targets": ("production",)},
    {"network_scope": ("*",)}, {"source_server": "another-server"},
    {"implementation_identity": "v2"}, {"offered_to_agent": False},
])
def test_each_semantic_surface_change_changes_identity(change):
    before = surface(tool())
    after = surface(replace(before.tools[0], **change))
    assert before.digest() != after.digest()
    report = compare_surfaces(before, after)
    assert report.verdict is SurfaceVerdict.MISMATCH
    assert "surface_changed_since_assessment" in report.reasons


def test_schema_object_key_order_is_canonical_but_array_order_is_preserved():
    a = tool(argument_schema_json='{"type":"object","required":["a","b"]}')
    b = tool(argument_schema_json='{"required":["a","b"],"type":"object"}')
    c = tool(argument_schema_json='{"required":["b","a"],"type":"object"}')
    assert surface(a).digest() == surface(b).digest()
    assert surface(a).digest() != surface(c).digest()


@pytest.mark.parametrize("value", ["true", 1, [], {}])
def test_visibility_cannot_be_coerced_from_untrusted_types(value):
    with pytest.raises(ValueError):
        tool(offered_to_agent=value)


def test_surface_detaches_mutable_tool_sequence():
    tools = [tool()]
    observed = RuntimeToolSurface("p", "agent-runtime", True, tools)
    digest = observed.digest()
    tools.clear()
    assert observed.digest() == digest


def test_wrong_process_or_incomplete_snapshot_never_establishes_continuity():
    before = surface(tool())
    assert compare_surfaces(before, replace(before, runtime_identity="other")).verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert compare_surfaces(before, replace(before, complete=False)).verdict is SurfaceVerdict.NOT_ESTABLISHED
