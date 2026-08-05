# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A deployment can classify its own tools, and cannot use that to grant itself
anything.

Before this existed, every tool a deployment registered fell to
``critical``/``unknown``, so ACCEPT was unreachable for any name REMORA had not
hardcoded. These tests cover the fix and — more importantly — the four
constraints that keep the fix from becoming a privilege-escalation channel:
additive-only, closed vocabulary, hashed into the policy identity, and
fail-closed when the declaration cannot be loaded.
"""
from __future__ import annotations

import json

import pytest

from remora.toolcall.deployment_registry import (
    DeploymentRegistryError,
    deployment_registry_digest,
    load_deployment_tool_metadata,
    reset_deployment_tool_metadata,
    resolve_tool_metadata,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_deployment_tool_metadata()
    yield
    reset_deployment_tool_metadata()


def _write(tmp_path, document) -> str:
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


VALID = {
    "version": 1,
    "tools": {
        "read_work_order": {
            "risk_tier": "low", "domain": "maintenance", "action_type": "read",
        },
        "close_work_order": {
            "risk_tier": "high", "domain": "maintenance",
            "action_type": "production_write", "rollback_available": False,
        },
    },
}


# ── The gap this closes ────────────────────────────────────────────────────

def test_an_undeclared_tool_still_falls_to_the_critical_floor() -> None:
    """The pre-existing fail-closed behaviour must not have moved."""
    metadata, declared = resolve_tool_metadata("calibrate_flux_capacitor")
    assert declared is False
    assert metadata == {
        "risk_tier": "critical", "domain": "unknown", "action_type": "unknown",
    }


def test_a_declared_tool_is_classified_as_the_deployment_declared_it(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", _write(tmp_path, VALID))
    reset_deployment_tool_metadata()

    metadata, declared = resolve_tool_metadata("read_work_order")
    assert declared is True
    assert metadata["risk_tier"] == "low"
    assert metadata["action_type"] == "read"
    assert metadata["domain"] == "maintenance"


def test_declaring_nothing_changes_nothing(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_TOOL_METADATA_FILE", raising=False)
    reset_deployment_tool_metadata()
    assert load_deployment_tool_metadata() == {}
    assert resolve_tool_metadata("read_work_order")[1] is False


# ── Constraint 1: additive only ────────────────────────────────────────────

def test_a_deployment_cannot_reclassify_a_tool_remora_already_classified(
    tmp_path, monkeypatch
) -> None:
    """The privilege-escalation case this feature would otherwise open."""
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", _write(tmp_path, {
        "version": 1,
        "tools": {"delete_production_database": {
            "risk_tier": "low", "domain": "maintenance", "action_type": "read",
        }},
    }))
    reset_deployment_tool_metadata()

    with pytest.raises(DeploymentRegistryError, match="may not be redeclared"):
        load_deployment_tool_metadata()


def test_remora_classification_wins_even_if_the_cache_were_bypassed() -> None:
    """Resolution order is core-first, independent of what was loaded."""
    metadata, declared = resolve_tool_metadata("delete_production_database")
    assert declared is True
    assert metadata["risk_tier"] == "critical"


# ── Constraint 2: closed vocabulary ────────────────────────────────────────

@pytest.mark.parametrize("bad_tier", ["LOW-ISH", "trivial", "", "none", "0"])
def test_an_unrecognized_risk_tier_is_refused(tmp_path, bad_tier) -> None:
    path = _write(tmp_path, {"version": 1, "tools": {"t": {
        "risk_tier": bad_tier, "domain": "d", "action_type": "read"}}})
    with pytest.raises(DeploymentRegistryError, match="risk_tier"):
        load_deployment_tool_metadata(path)


@pytest.mark.parametrize("bad_action", ["writey", "EXECUTE", "", "destroy"])
def test_an_unrecognized_action_type_is_refused(tmp_path, bad_action) -> None:
    """An unrecognized action type is floored to VERIFY by the engine.

    Accepting it here would turn a typo into a permanent VERIFY that reads as
    a policy decision. The operator must find out at startup instead.
    """
    path = _write(tmp_path, {"version": 1, "tools": {"t": {
        "risk_tier": "low", "domain": "d", "action_type": bad_action}}})
    with pytest.raises(DeploymentRegistryError, match="action_type"):
        load_deployment_tool_metadata(path)


def test_every_accepted_action_type_is_one_the_engine_recognizes() -> None:
    """Guards against the vocabulary being restated and drifting.

    If the engine drops a type, this fails rather than leaving the loader
    accepting a value that now routes as unknown.
    """
    from remora.policy.decision_engine import (
        _MUTATING_TYPES,
        _NON_ACTUATING_TYPES,
        _READ_ONLY_ACTION_TYPES,
        _READ_ONLY_TYPES,
    )
    from remora.toolcall.deployment_registry import KNOWN_ACTION_TYPES

    engine_vocabulary = (
        _READ_ONLY_TYPES | _READ_ONLY_ACTION_TYPES
        | _MUTATING_TYPES | _NON_ACTUATING_TYPES
    )
    assert KNOWN_ACTION_TYPES == engine_vocabulary


def test_unknown_fields_are_refused_rather_than_ignored(tmp_path) -> None:
    """A misspelled field name must not silently do nothing.

    ``rollback_availabe`` accepted-and-ignored would leave the operator
    believing they had declared a downgrade they had not.
    """
    path = _write(tmp_path, {"version": 1, "tools": {"t": {
        "risk_tier": "low", "domain": "d", "action_type": "read",
        "rollback_availabe": False}}})
    with pytest.raises(DeploymentRegistryError, match="unknown field"):
        load_deployment_tool_metadata(path)


def test_downgrade_flags_must_be_booleans(tmp_path) -> None:
    path = _write(tmp_path, {"version": 1, "tools": {"t": {
        "risk_tier": "low", "domain": "d", "action_type": "read",
        "rollback_available": "false"}}})
    with pytest.raises(DeploymentRegistryError, match="must be a boolean"):
        load_deployment_tool_metadata(path)


@pytest.mark.parametrize("missing", ["risk_tier", "domain", "action_type"])
def test_a_partial_declaration_is_refused(tmp_path, missing) -> None:
    entry = {"risk_tier": "low", "domain": "d", "action_type": "read"}
    del entry[missing]
    path = _write(tmp_path, {"version": 1, "tools": {"t": entry}})
    with pytest.raises(DeploymentRegistryError, match="missing required"):
        load_deployment_tool_metadata(path)


# ── Constraint 3: hashed into the policy identity ──────────────────────────

def test_editing_the_declaration_moves_the_policy_bundle_hash(
    tmp_path, monkeypatch
) -> None:
    """A relabelled tool must not keep executing under an older lease.

    ``GovernedToolDispatcher.dispatch`` refuses when the lease's
    ``policy_bundle_hash`` no longer matches the recomputed composite, so
    moving this hash is what invalidates authorizations issued before the
    relabel.
    """
    from servers import api as api_mod

    path = _write(tmp_path, VALID)
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", path)
    reset_deployment_tool_metadata()
    before = api_mod._tool_registry_component_hash()

    relabelled = json.loads(json.dumps(VALID))
    relabelled["tools"]["close_work_order"]["risk_tier"] = "low"
    (tmp_path / "tools.json").write_text(json.dumps(relabelled), encoding="utf-8")
    reset_deployment_tool_metadata()
    after = api_mod._tool_registry_component_hash()

    assert before != after, (
        "reclassifying a tool left the policy identity unchanged; leases "
        "issued under the old classification would keep verifying"
    )


def test_the_hash_is_insensitive_to_formatting_only_changes(
    tmp_path, monkeypatch
) -> None:
    """Whitespace and key order describe the same policy.

    Hashing raw bytes would invalidate every outstanding lease on a
    reformat, which trains operators to ignore the signal.
    """
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", str(tmp_path / "tools.json"))
    (tmp_path / "tools.json").write_text(
        json.dumps(VALID, indent=2, sort_keys=True), encoding="utf-8")
    reset_deployment_tool_metadata()
    pretty = deployment_registry_digest()

    (tmp_path / "tools.json").write_text(
        json.dumps(VALID, separators=(",", ":")), encoding="utf-8")
    reset_deployment_tool_metadata()
    compact = deployment_registry_digest()

    assert pretty == compact


def test_no_declaration_and_an_unloadable_one_hash_differently(
    tmp_path, monkeypatch
) -> None:
    """A broken file must move the hash, never vanish from it."""
    monkeypatch.delenv("REMORA_TOOL_METADATA_FILE", raising=False)
    reset_deployment_tool_metadata()
    absent = deployment_registry_digest()

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", str(broken))
    reset_deployment_tool_metadata()
    unloadable = deployment_registry_digest()

    assert absent == "none"
    assert unloadable == "unloadable"
    assert absent != unloadable


# ── Constraint 4: fail closed on an unusable declaration ───────────────────

def test_a_missing_file_is_an_error_not_an_empty_registry(monkeypatch) -> None:
    """Silently treating it as "no tools declared" would drop every tool to
    the critical floor while the operator believed they were classified."""
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", "/nonexistent/tools.json")
    reset_deployment_tool_metadata()
    with pytest.raises(DeploymentRegistryError, match="cannot read"):
        load_deployment_tool_metadata()


def test_malformed_json_is_an_error(tmp_path) -> None:
    path = tmp_path / "tools.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DeploymentRegistryError, match="not valid JSON"):
        load_deployment_tool_metadata(str(path))


def test_an_unsupported_version_is_refused(tmp_path) -> None:
    """A future format must not be parsed by an older build guessing."""
    path = _write(tmp_path, {"version": 2, "tools": {}})
    with pytest.raises(DeploymentRegistryError, match="unsupported version"):
        load_deployment_tool_metadata(path)


def test_startup_refuses_a_configured_but_broken_declaration(
    tmp_path, monkeypatch
) -> None:
    from servers import api as api_mod

    broken = tmp_path / "broken.json"
    broken.write_text('{"version": 1, "tools": {"t": {"risk_tier": "nope"}}}',
                      encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", str(broken))
    reset_deployment_tool_metadata()

    with pytest.raises(DeploymentRegistryError):
        api_mod._validate_deployment_tool_metadata()
