# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation probes for the async authorization -> dispatch seam.

A 202 response records durable authorization and defers the actual side effect.
Anything load-bearing that can change before the worker honours that row must
either be bound into the row or freshly re-gated by the worker.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.toolcall.toolspec import sign_bundle  # noqa: E402

KEY = "prefed-async-toolspec-key"
IDENTITY = "prefed-async-signer-v1"

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "prefed-async-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


def _spec(version: int) -> dict:
    return {
        "tool_id": "store_artifact",
        "version": version,
        "callable_digest": "sha256:" + ("a" if version == 1 else "b") * 64,
        "implementation_identity": f"prefed-runtime-v{version}",
        "description": "Persist an artifact.",
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
            "capability": "artifact_management",
            "effect": "create",
            "resource_type": "artifact",
            "mutation": True,
            "argument_roles": {"artifact_id": "target_resource"},
        },
        "credential_scope": ["artifacts:write"],
        "allowed_targets": ["prod"],
        "idempotency_contract": {
            "safe_to_retry": True,
            "key_derivation": "canonical_args",
        },
        "postcondition_reader": None,
        "compensation_tool": None,
        "timeout_policy": {"dispatch_timeout_seconds": 10},
        "network_policy": {"egress": "none"},
        "signing_identity": IDENTITY,
    }


def _bundle(tmp_path, version: int, name: str):
    raw = sign_bundle(
        {"schema_version": 1, "tool_specs": [_spec(version)]},
        key=KEY,
        signing_identity=IDENTITY,
        signed_at="2026-10-06T00:00:00Z",
    )
    path = tmp_path / name
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "prefed-async-pdp")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "prefed-async-lease")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE",
                       str(_bundle(tmp_path, 1, "bundle-v1.json")))
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
    monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate",
                        lambda request: ("acme", "reviewer"))
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


def _pending(client):
    assessed = client.post("/v1/execution/assess", json=CALL)
    assert assessed.status_code == 200, assessed.text
    body = assessed.json()
    item = body["review_item_id"]
    assert client.post(
        "/v1/execution/approve", json={"item_id": item}).status_code == 200
    pending = client.post(
        "/v1/execution/execute", json={"item_id": item, "tool_call": CALL})
    assert pending.status_code == 202, pending.text
    return body, pending.json()


def test_async_worker_refuses_toolspec_drift_after_durable_authorization(
        client, monkeypatch, tmp_path):
    """Spec A was checked before the 202. Spec B must not become the authority
    merely because it is current when the worker wakes up.
    """
    assessed, pending = _pending(client)
    assert assessed["toolspec"]["version"] == 1

    import servers.execution_api as exec_mod

    monkeypatch.setenv(
        "REMORA_TOOLSPEC_BUNDLE",
        str(_bundle(tmp_path, 2, "bundle-v2.json")),
    )
    exec_mod._reset_toolspec_bundle()
    exec_mod._reset_tool_dispatcher()

    results = exec_mod.dispatch_pending_intents("acme", worker_id="w-1")
    assert len(results) == 1
    te = results[0]["tool_execution"]
    assert te["executed"] is False, (
        "worker executed under a ToolSpec different from the one checked "
        "before durable authorization"
    )
    assert te["refusal_reason"] in {
        "toolspec_changed_between_authorization_and_dispatch",
        "authorization_context_changed",
        "toolspec_hash_mismatch",
    }
    assert results[0]["proposal_id"] == pending["proposal_id"]


def test_async_worker_rechecks_fresh_hard_guards_before_dispatch(
        client, monkeypatch):
    """A fresh observation is already built in the worker. A newly-triggered
    hard guard must be decided, not merely hashed and wrapped in a new ACCEPT.
    """
    _pending(client)
    import servers.execution_api as exec_mod

    real_builder = exec_mod._observation_with_context

    def now_adversarial(tool_call, tenant):
        obs, semantic = real_builder(tool_call, tenant)
        return dataclasses.replace(obs, adversarial_detected=True), semantic

    monkeypatch.setattr(exec_mod, "_observation_with_context", now_adversarial)

    results = exec_mod.dispatch_pending_intents("acme", worker_id="w-2")
    assert len(results) == 1
    te = results[0]["tool_execution"]
    assert te["executed"] is False, (
        "worker ignored a fresh hard-guard signal and minted/consumed ACCEPT "
        "without re-running the execution policy decision"
    )
