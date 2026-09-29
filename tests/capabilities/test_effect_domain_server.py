# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The effect domain on the execution API (NTA-2 phase 3).

A process with REMORA_EXECUTION_DOMAIN_ROLE=effect serves /effects and
/effects/close and nothing else; no other role serves them. Whether a lease
was dispatched is read from the durable nonce store it shares with the
executor, and the ceiling comes from its own signed ToolSpec bundle.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.capabilities import CapabilityPolicy, CapabilityResolver  # noqa: E402
from remora.enforcement.lease import ExecutionLease  # noqa: E402
from remora.enforcement.nonce_store import DurableNonceStore  # noqa: E402
from remora.toolcall.toolspec import sign_bundle  # noqa: E402
from tests.capabilities import mediated_registry  # noqa: E402
from tests.capabilities.test_capability_server_path import POLICY  # noqa: E402
from tests.test_toolspec_runtime import IDENTITY, KEY, _spec  # noqa: E402

DECLARATION = [{"capability": "database.read", "resources": ["database://telemetry-eu/*"],
                "purpose": "read_readings"}]


@pytest.fixture()
def effect(monkeypatch, tmp_path):
    bundle = sign_bundle({"schema_version": 2, "tool_specs": [_spec(
        tool_id="read_telemetry", allowed_targets=["staging"],
        downstream_capabilities=DECLARATION)]},
        key=KEY, signing_identity=IDENTITY, signed_at="2026-09-29T00:00:00+00:00")
    (tmp_path / "specs.json").write_text(json.dumps(bundle))
    db = tmp_path / "state.db"
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(tmp_path / "specs.json"))
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
    monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)
    monkeypatch.setenv("REMORA_CHAIN_DB", str(db))
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "effect-server-key")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.capabilities.mediated_registry")
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "effect")
    for name in ("REMORA_RUNTIME_PROFILE", "REMORA_EFFECT_ENDPOINT",
                 "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"):
        monkeypatch.delenv(name, raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from remora.execution.authorization import reset_toolspec_bundle_cache

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    reset_toolspec_bundle_cache()
    exec_mod._reset_tool_dispatcher()
    mediated_registry.EFFECT_CALLS.clear()
    yield TestClient(api_mod.app), DurableNonceStore(db_path=str(db))
    exec_mod._reset_tool_dispatcher()
    reset_toolspec_bundle_cache()


def _lease_and_set():
    capability_set = CapabilityResolver(CapabilityPolicy.from_dict(POLICY)).resolve(
        principal_id="agent-1", tenant_id="acme", environment="staging",
        task_type="monitoring", now=datetime.now(UTC))
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1",
        tool_name="read_telemetry", arguments={"asset": "P-1"},
        target_environment="staging", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat(), capability_set=capability_set)
    return lease, capability_set


def _body(lease, capability_set, resource="database://telemetry-eu/P-1"):
    return {"lease": lease.to_dict(), "capability_set": capability_set.to_dict(),
            "capability": "database.read", "resource": resource, "arguments": {}}


def test_a_dispatched_lease_gets_its_declared_effect(effect):
    client, store = effect
    lease, cs = _lease_and_set()
    store.try_consume(lease.nonce, tenant_id="acme")  # what the executor did
    answer = client.post("/v1/execution/effects", json=_body(lease, cs))
    assert answer.status_code == 200, answer.text
    assert answer.json()["state"] == "EXECUTED" and answer.json()["result"] == [42]
    assert mediated_registry.EFFECT_CALLS == [("database.read", "database://telemetry-eu/P-1")]


def test_a_lease_never_dispatched_gets_nothing(effect):
    client, _ = effect
    lease, cs = _lease_and_set()
    answer = client.post("/v1/execution/effects", json=_body(lease, cs)).json()
    assert answer["refusal"] == "execution_not_started"
    assert mediated_registry.EFFECT_CALLS == []


def test_the_ceiling_is_the_effect_domains_own(effect):
    client, store = effect
    lease, cs = _lease_and_set()
    store.try_consume(lease.nonce, tenant_id="acme")
    answer = client.post("/v1/execution/effects",
                         json=_body(lease, cs, "database://billing-us/x")).json()
    assert answer["refusal"] == "capability_resource_not_authorized"


def test_close_ends_the_execution(effect):
    client, store = effect
    lease, cs = _lease_and_set()
    store.try_consume(lease.nonce, tenant_id="acme")
    assert client.post("/v1/execution/effects/close",
                       json={"lease": lease.to_dict()}).json()["closed"] is True
    answer = client.post("/v1/execution/effects", json=_body(lease, cs)).json()
    assert answer["refusal"] == "capability_context_missing"


def test_another_tenants_lease_is_refused(effect, monkeypatch):
    import servers.api as api_mod

    client, _ = effect
    lease, cs = _lease_and_set()
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("other", "operator"))
    assert client.post("/v1/execution/effects", json=_body(lease, cs)).status_code == 409


@pytest.mark.parametrize("role, path, served", [
    ("effect", "/v1/execution/assess", False),
    ("effect", "/v1/execution/dispatch-leased", False),
    ("executor", "/v1/execution/effects", False),
    ("authority", "/v1/execution/effects", False),
    ("authority", "/v1/execution/effects/close", False),
])
def test_only_the_effect_domain_serves_effects(effect, monkeypatch, role, path, served):
    client, _ = effect
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", role)
    response = client.post(path, json={})
    assert (response.status_code != 404) is served
