# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A real ToolSpec hash flows from assessment into the lease.

The loader (PR 2a) and the lease binding (PR 2b) both exist; until they
are joined, the lease binds an empty hash and the chain is a chain of one.
This wires them: when a signed bundle is configured, `/v1/execution`
resolves the spec at assess, records its identity, and dispatch verifies
that the very same spec is still the one in force.

Configuration is deliberately opt-in. Without `REMORA_TOOLSPEC_BUNDLE`
the legacy registry path runs exactly as before and the response says so
— PR 1 chose "strict when a bundle is configured", never trust-on-first-
use and never a silent upgrade that breaks running deployments.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.toolcall.toolspec import sign_bundle  # noqa: E402

KEY = "wiring-toolspec-key"
IDENTITY = "wiring-signer-v1"

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "wired-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


def _spec(**overrides) -> dict:
    spec = {
        "tool_id": "store_artifact",
        "version": 1,
        "callable_digest": "sha256:" + "a" * 64,
        "implementation_identity": "research-profile@test",
        "description": "Persist an artifact under the sandboxed directory.",
        "argument_schema": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "content": {"type": "object"},
            },
            "required": ["artifact_id"],
            "additionalProperties": False,
        },
        "risk_tier": "medium",
        "action_type": "write",
        "domain": "general",
        "capabilities": ["artifact_management"],
        "semantic_contract": {
            "capability": "artifact_management", "effect": "create",
            "resource_type": "artifact", "mutation": True,
            "argument_roles": {"artifact_id": "target_resource"},
        },
        "credential_scope": ["artifacts:write"],
        "allowed_targets": ["staging", "prod"],
        "idempotency_contract": {"safe_to_retry": True,
                                 "key_derivation": "canonical_args"},
        "postcondition_reader": None,
        "compensation_tool": None,
        "timeout_policy": {"dispatch_timeout_seconds": 10},
        "network_policy": {"egress": "none"},
        "signing_identity": IDENTITY,
    }
    spec.update(overrides)
    return spec


def _bundle_file(tmp_path, specs=None, name="bundle.json"):
    bundle = sign_bundle(
        {"schema_version": 1, "tool_specs": specs or [_spec()]},
        key=KEY, signing_identity=IDENTITY, signed_at="2026-08-05T00:00:00Z",
    )
    path = tmp_path / name
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _client(monkeypatch, tmp_path, *, bundle_path=None):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "wiring-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "wiring-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    if bundle_path is not None:
        monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(bundle_path))
        monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
        monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)
    else:
        for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY",
                    "REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
            monkeypatch.delenv(var, raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path, bundle_path=_bundle_file(tmp_path))


@pytest.fixture()
def legacy_client(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path, bundle_path=None)


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


# ── With a bundle: the identity flows and is recorded ──────────────────────

def test_assess_records_the_toolspec_identity(client) -> None:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["toolspec"]["tool_id"] == "store_artifact"
    assert body["toolspec"]["version"] == 1
    assert len(body["toolspec"]["hash"]) == 64
    record = _mod()._CHAIN.entries("acme")[-1].payload
    assert record["toolspec_hash"] == body["toolspec"]["hash"]


def test_execute_binds_the_same_spec_into_the_lease(client) -> None:
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    item_id = assessed["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "execute"
    assert body["execution_grant"]  # the lease/grant was issued
    assert body["toolspec"]["hash"] == assessed["toolspec"]["hash"]


def test_arguments_failing_the_spec_schema_are_refused_at_assess(client) -> None:
    """PR 1 decided this is a hard refusal, not a trust downgrade."""
    r = client.post("/v1/execution/assess", json=dict(
        CALL, arguments={"artifact_id": "a-1", "unexpected_field": 1},
    ))
    assert r.status_code == 409, r.text
    assert r.json()["detail"].startswith("toolspec_arguments_schema_invalid")


def test_target_outside_the_spec_allowlist_is_refused(client) -> None:
    r = client.post("/v1/execution/assess", json=dict(
        CALL, target_environment="development",
    ))
    assert r.status_code == 409, r.text
    assert "toolspec_target_not_allowed" in r.json()["detail"]


def test_unknown_tool_is_refused_in_strict_mode(client) -> None:
    """No spec means no authority to act, even for a registered callable."""
    r = client.post("/v1/execution/assess", json={
        "tool_name": "read_telemetry", "arguments": {},
    })
    assert r.status_code == 409, r.text
    assert "toolspec_unknown_tool" in r.json()["detail"]


def test_a_redeployed_spec_refuses_a_prior_approval(client, monkeypatch,
                                                    tmp_path) -> None:
    """The whole point of the binding chain: an approval granted under one
    spec must not execute under another."""
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    item_id = assessed["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200

    # The deployment ships a new spec while the review was pending.
    monkeypatch.setenv(
        "REMORA_TOOLSPEC_BUNDLE",
        str(_bundle_file(tmp_path, [_spec(version=2)], name="bundle2.json")),
    )
    _mod()._reset_toolspec_bundle()

    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 409, r.text
    assert "toolspec_changed_between_assess_and_dispatch" in r.json()["detail"]


# ── Without a bundle: the legacy path is unchanged and says so ─────────────

def test_without_a_bundle_the_legacy_path_still_works(legacy_client) -> None:
    r = legacy_client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    assert r.json()["review_item_id"]


def test_without_a_bundle_the_response_records_the_degradation(
    legacy_client,
) -> None:
    """Not silently equivalent: a deployment running without signed specs
    must be able to see that from the response."""
    body = legacy_client.post("/v1/execution/assess", json=CALL).json()
    assert body["toolspec"] is not None
    assert body["toolspec"]["enforced"] is False
    assert body["toolspec"]["hash"] == ""
