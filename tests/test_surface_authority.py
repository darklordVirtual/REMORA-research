# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from dataclasses import replace

from remora.toolcall.runtime_surface import RuntimeTool, RuntimeToolSurface, SurfaceVerdict
from remora.toolcall.surface_authority import analyze_authority


def known(name="update"):
    return RuntimeTool(name, "native", True, True, "a" * 64,
                       credential_scope=("ticket:write",), allowed_targets=("tickets",),
                       network_scope=("api.example.test",), operations=("update",),
                       effect_classes=("ticket_mutation",), authority_provenance="fixture-observer")


def analyze(*tools, complete=True):
    return analyze_authority(RuntimeToolSurface("p", "agent-runtime", True, tools),
                             {"update": known()}, inventory_complete=complete)


def test_http_or_shell_path_to_same_effect_is_reported():
    result = analyze(known(), known("shell"))
    assert result.verdict is SurfaceVerdict.MISMATCH
    assert result.alternate_paths == (("shell", "update"),)
    assert "alternate_effect_path_detected" in result.reasons


def test_broader_credential_or_network_scope_is_a_mismatch():
    for change in ({"credential_scope": ("*",)}, {"network_scope": ("*",)},
                   {"allowed_targets": ("tickets", "customers")}):
        result = analyze(replace(known(), **change))
        assert result.verdict is SurfaceVerdict.MISMATCH
        assert result.scope_mismatches == ("update",)


def test_no_observed_bypass_does_not_prove_inventory_complete():
    assert analyze(known(), complete=False).verdict is SurfaceVerdict.NOT_ESTABLISHED


def test_unknown_authority_and_wildcards_are_explicitly_unresolved():
    result = analyze(known(), replace(known("http"), allowed_targets=None))
    assert result.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert result.unresolved_tools == ("http",)
    assert "alternate_effect_path_not_ruled_out" in result.reasons


def test_complete_bounded_inventory_can_only_match_observation():
    result = analyze(known())
    assert result.verdict is SurfaceVerdict.MATCHED_OBSERVATION
    assert result.edges


def test_missing_governed_tool_is_not_complete():
    assert analyze().verdict is SurfaceVerdict.NOT_ESTABLISHED


def test_incomplete_surface_is_not_ruled_out_even_with_inventory_assertion():
    surface = RuntimeToolSurface("p", "agent-runtime", False, (known(),))
    result = analyze_authority(surface, {"update": known()}, inventory_complete=True)
    assert result.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert result.reasons == ("alternate_effect_path_not_ruled_out",)


def test_registry_only_source_cannot_match_authority():
    surface = RuntimeToolSurface("p", "dispatcher-registry", True, (known(),))
    result = analyze_authority(surface, {"update": known()}, inventory_complete=True)
    assert result.verdict is SurfaceVerdict.NOT_ESTABLISHED
    assert "runtime_registry_unattested" in result.reasons
