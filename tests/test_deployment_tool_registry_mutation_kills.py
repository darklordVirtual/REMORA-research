# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests added for the mutants that survived the 2026-11-04 mutmut sweep.

29 of 176 mutants of remora/toolcall/deployment_registry.py survived
(docs/assurance/ws1_utility_test_plan_v1.md, item 1). They sat in the
optional ``target_environment`` and flag fields, the cache's refresh rule,
the digest's canonical form and the vocabulary union. Each test here pins
one of those behaviours.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from remora.toolcall import deployment_registry as dr
from remora.toolcall.deployment_registry import (
    ENV_VAR,
    DeploymentRegistryError,
    deployment_registry_digest,
    load_deployment_tool_metadata,
    reset_deployment_tool_metadata,
    resolve_tool_metadata,
)


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    reset_deployment_tool_metadata()
    yield
    reset_deployment_tool_metadata()


def _write(tmp_path, name, tools) -> str:
    path = tmp_path / name
    path.write_text(json.dumps({"version": 1, "tools": tools}), encoding="utf-8")
    return str(path)


BASE = {"risk_tier": "low", "domain": "plant", "action_type": "read"}


def test_the_resolved_entry_is_exactly_the_three_required_fields_normalised(tmp_path):
    path = _write(tmp_path, "t.json", {"read_sensor": {"risk_tier": " LOW ", "domain": " plant ",
                                                        "action_type": " Read "}})
    assert load_deployment_tool_metadata(path) == {
        "read_sensor": {"risk_tier": "low", "domain": "plant", "action_type": "read"}}


def test_target_environment_is_normalised_and_carried():
    assert dr._validate_entry("t", {**BASE, "target_environment": " Prod "}) == {
        **BASE, "target_environment": "prod"}


def test_an_empty_target_environment_is_refused():
    with pytest.raises(DeploymentRegistryError, match="empty target_environment"):
        dr._validate_entry("t", {**BASE, "target_environment": "  "})


@pytest.mark.parametrize("flag", ["schema_valid", "rollback_available"])
@pytest.mark.parametrize("value", [True, False])
def test_each_downgrade_flag_is_carried_with_its_value(flag, value):
    assert dr._validate_entry("t", {**BASE, flag: value}) == {**BASE, flag: value}


@pytest.mark.parametrize("flag", ["schema_valid", "rollback_available"])
def test_a_non_boolean_flag_names_the_tool_the_flag_and_the_type(flag):
    with pytest.raises(DeploymentRegistryError) as exc:
        dr._validate_entry("my_tool", {**BASE, flag: "yes"})
    assert "'my_tool'" in str(exc.value) and flag in str(exc.value) and "got str" in str(exc.value)


def test_refusals_name_the_tool(tmp_path):
    path = _write(tmp_path, "t.json", {"odd_tool": {**BASE, "risk_tier": "sky-high"}})
    with pytest.raises(DeploymentRegistryError, match="tool 'odd_tool'"):
        load_deployment_tool_metadata(path)


def test_an_action_type_known_only_to_the_engine_read_only_set_is_accepted():
    # "inspect" is in the engine's _READ_ONLY_TYPES and in no other set.
    from remora.policy.decision_engine import (
        _MUTATING_TYPES,
        _NON_ACTUATING_TYPES,
        _READ_ONLY_ACTION_TYPES,
        _READ_ONLY_TYPES,
    )
    only_here = _READ_ONLY_TYPES - _READ_ONLY_ACTION_TYPES - _MUTATING_TYPES - _NON_ACTUATING_TYPES
    assert only_here, "the engine's sets changed; pick another distinguishing action type"
    action = sorted(only_here)[0]
    assert dr._validate_entry("t", {**BASE, "action_type": action})["action_type"] == action


def test_the_cache_refreshes_when_the_declared_file_changes(tmp_path, monkeypatch):
    first = _write(tmp_path, "first.json", {"tool_a": BASE})
    second = _write(tmp_path, "second.json", {"tool_b": BASE})
    monkeypatch.setenv(ENV_VAR, first)
    assert resolve_tool_metadata("tool_a")[1] is True
    assert resolve_tool_metadata("tool_b")[1] is False
    monkeypatch.setenv(ENV_VAR, second)
    assert resolve_tool_metadata("tool_b")[1] is True
    assert resolve_tool_metadata("tool_a")[1] is False


def test_the_cache_is_not_reloaded_while_the_declaration_is_unchanged(tmp_path, monkeypatch):
    path = _write(tmp_path, "t.json", {"tool_a": BASE})
    monkeypatch.setenv(ENV_VAR, path)
    assert resolve_tool_metadata("tool_a")[1] is True
    loads: list[str] = []
    monkeypatch.setattr(dr, "load_deployment_tool_metadata", lambda *a, **k: loads.append("x") or {})
    assert resolve_tool_metadata("tool_a")[1] is True
    assert loads == []


def test_after_a_reset_with_no_declaration_resolution_falls_to_the_floor():
    reset_deployment_tool_metadata()
    metadata, declared = resolve_tool_metadata("never_declared")
    assert declared is False
    assert metadata == {"risk_tier": "critical", "domain": "unknown", "action_type": "unknown"}
    assert dr._cached() == {}


def test_the_digest_is_sha256_over_the_compact_sorted_json_of_the_resolved_declaration(
        tmp_path, monkeypatch):
    path = _write(tmp_path, "t.json", {"tool_a": {"domain": "plant", "risk_tier": "low",
                                                  "action_type": "read", "schema_valid": True}})
    monkeypatch.setenv(ENV_VAR, path)
    canonical = '{"tool_a":{"action_type":"read","domain":"plant","risk_tier":"low","schema_valid":true}}'
    assert deployment_registry_digest() == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_an_unreadable_file_names_the_path_and_the_os_error(tmp_path, monkeypatch):
    missing = str(tmp_path / "absent.json")
    monkeypatch.setenv(ENV_VAR, missing)
    with pytest.raises(DeploymentRegistryError) as exc:
        load_deployment_tool_metadata()
    assert missing in str(exc.value) and "No such file" in str(exc.value)
