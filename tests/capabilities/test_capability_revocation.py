# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Capability sets can be revoked between issuance and dispatch (quality program Q8.6)."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from remora.capabilities import (  # noqa: E402
    CapabilityEpochs,
    CapabilityPolicy,
    CapabilityRefusal,
    CapabilityResolver,
    StaticEpochSource,
    revocation_refusal,
)
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher  # noqa: E402

POLICY = CapabilityPolicy.from_dict({
    "policy_version": "p1", "registry_version": "r1", "registry": {"invoice.read": ["prod"]},
    "principals": {"agent-42": ["invoice.read"]}, "tasks": {"reconcile": ["invoice.read"]},
    "tenants": {"acme": ["invoice.read"]}, "environments": {"prod": ["invoice.read"]}})
ISSUED_AT = CapabilityEpochs(principal=5, tenant=2, policy=7, toolspec=3)


def _set():
    return CapabilityResolver(POLICY).resolve(
        principal_id="agent-42", tenant_id="acme", environment="prod", task_type="reconcile",
        now=datetime.now(UTC), epochs=ISSUED_AT)


def _source(**over):
    base = dict(policy=7, toolspec=3, tenants={"acme": 2}, principals={"agent-42": 5})
    base.update(over)
    return StaticEpochSource(**base)


class TestEpochs:
    def test_a_set_at_the_current_epochs_is_current(self):
        assert revocation_refusal(_set(), _source()) is None

    @pytest.mark.parametrize("over", [
        {"policy": 8}, {"toolspec": 4}, {"tenants": {"acme": 3}}, {"principals": {"agent-42": 6}},
    ], ids=["policy", "toolspec", "tenant", "principal"])
    def test_any_scope_moving_past_the_set_makes_it_stale(self, over):
        assert revocation_refusal(_set(), _source(**over)) is CapabilityRefusal.STALE

    def test_another_principal_moving_does_not_touch_this_set(self):
        assert revocation_refusal(_set(), _source(principals={"agent-42": 5, "agent-7": 99})) is None

    def test_an_explicitly_revoked_set_is_revoked(self):
        s = _set()
        assert revocation_refusal(s, _source(revoked_sets=frozenset({s.capability_set_id}))) is (
            CapabilityRefusal.REVOKED)

    def test_a_source_that_cannot_answer_refuses(self):
        class Down:
            def current(self, tenant_id, principal_id):
                raise ConnectionError("down")

            def revoked(self, capability_set_id):
                raise ConnectionError("down")

        assert revocation_refusal(_set(), Down()) is CapabilityRefusal.EPOCH_UNVERIFIABLE

    def test_no_source_means_no_epoch_check(self):
        assert revocation_refusal(_set(), None) is None

    def test_the_epochs_are_in_the_digest(self):
        import dataclasses

        s = _set()
        assert dataclasses.replace(s, epochs=CapabilityEpochs(policy=8)).digest != s.digest


class TestTheDispatcher:
    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "revocation-key")
        for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                     "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
            monkeypatch.delenv(name, raising=False)

    def _dispatch(self, source, s=None, dispatcher=None):
        s = s or _set()
        lease = ExecutionLease.issue(
            decision="accept", tenant_id="acme", actor_identity="agent-42", tool_name="invoice.read",
            arguments={"id": 1}, target_environment="prod", policy_bundle_hash="b1",
            issued_at=datetime.now(UTC).isoformat(), capability_set=s)
        calls: list = []
        dispatcher = dispatcher or GovernedToolDispatcher("b1")
        dispatcher.register("invoice.read", lambda args: calls.append(args) or "ok")
        dispatcher.bind_capability_epochs(source)
        result = dispatcher.dispatch(lease, "invoice.read", {"id": 1}, tenant_id="acme",
                                     target_environment="prod", actor_identity="agent-42",
                                     capability_set=s)
        return result, calls, lease, s

    def test_a_current_set_runs(self):
        assert self._dispatch(_source())[0].executed

    def test_a_policy_change_after_issuance_refuses_and_nothing_runs(self):
        result, calls, _, _ = self._dispatch(_source(policy=8))
        assert (result.executed, result.refusal_reason) == (False, "capability_stale")
        assert calls == []

    def test_a_stale_refusal_leaves_the_nonce_unspent(self):
        dispatcher = GovernedToolDispatcher("b1")
        result, _, lease, s = self._dispatch(_source(policy=8), dispatcher=dispatcher)
        assert not result.executed
        dispatcher.bind_capability_epochs(_source())
        assert dispatcher.dispatch(lease, "invoice.read", {"id": 1}, tenant_id="acme",
                                   target_environment="prod", actor_identity="agent-42",
                                   capability_set=s).executed


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from tests import capability_epoch_fixture as epochs  # noqa: E402

LEASED = {"tool_name": "update_work_order",
          "arguments": {"work_order_id": "WO-1", "status": "closed"},
          "target_environment": "staging", "task_type": "maintenance"}
API_POLICY = {
    "policy_version": "cap-1", "registry_version": "reg-1",
    "registry": {"update_work_order": ["staging"], "read_telemetry": ["staging"]},
    "principals": {"employee-1": ["update_work_order", "read_telemetry"]},
    "tasks": {"maintenance": ["update_work_order"], "monitoring": ["read_telemetry"]},
    "tenants": {"acme": ["update_work_order", "read_telemetry"]},
    "environments": {"staging": ["update_work_order", "read_telemetry"]},
}


@pytest.fixture()
def executor(monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _security_extra import require_security_extra

    require_security_extra()
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from remora.enforcement import lease_signing as signing

    policy = tmp_path / "capabilities.json"
    policy.write_text(json.dumps(API_POLICY))
    key = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv("REMORA_CAPABILITY_POLICY_FILE", str(policy))
    monkeypatch.setenv("REMORA_CAPABILITY_EPOCH_MODULE", "tests.capability_epoch_fixture")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    monkeypatch.delenv(signing.ENV_HMAC, raising=False)
    monkeypatch.delenv(signing.ENV_HMAC_FALLBACK, raising=False)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, key.public_key().public_bytes_raw().hex())
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, key.private_bytes_raw().hex())
    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from tests import dispatcher_registry_fixture as registry

    registry.CALLS.clear()
    epochs.reset()
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_tool_dispatcher()
    yield SimpleNamespace(client=TestClient(api_mod.app), registry=registry,
                          bundle=exec_mod._current_policy_bundle_hash(),
                          monkeypatch=monkeypatch, signing=signing, exec_mod=exec_mod)
    epochs.reset()
    exec_mod._reset_tool_dispatcher()


def _mint_and_present(executor, between=lambda s: None):
    """Authority mints a lease under the current epochs; something changes;
    the executor receives it."""
    from remora.capabilities import CapabilityPolicy, CapabilityResolver
    from remora.execution.dispatch import issue_execution_lease

    s = CapabilityResolver(CapabilityPolicy.from_dict(API_POLICY)).resolve(
        principal_id="employee-1", tenant_id="acme", environment="staging",
        task_type="maintenance", now=datetime.now(UTC),
        epochs=epochs.current("acme", "employee-1"))
    lease = issue_execution_lease(
        tenant="acme", principal="employee-1", tool_call=SimpleNamespace(**LEASED),
        semantic={"tool_contract_bundle_hash": "", "intent_authority_hash": ""},
        now=datetime.now(UTC), policy_bundle_hash=executor.bundle, capability_set=s)
    between(s)
    executor.monkeypatch.delenv(executor.signing.ENV_ED25519_PRIVATE, raising=False)
    return executor.client.post("/v1/execution/dispatch-leased", json={
        "lease": lease.to_dict(), "tool_call": LEASED, "tenant_id": "acme",
        "capability_set": s.to_dict()}).json()["tool_execution"]


class TestTheExecutorReadsEpochsAtDispatch:
    def test_an_unchanged_world_executes(self, executor):
        assert _mint_and_present(executor)["executed"] is True

    def test_a_policy_change_between_mint_and_dispatch_refuses(self, executor):
        result = _mint_and_present(executor, lambda s: epochs.EPOCHS.update(policy=2))
        assert result["refusal_reason"] == "capability_stale"
        assert executor.registry.CALLS == []

    def test_a_suspended_principal_is_refused(self, executor):
        result = _mint_and_present(executor, lambda s: epochs.EPOCHS.update(principal=2))
        assert result["refusal_reason"] == "capability_stale"

    def test_an_explicitly_revoked_set_is_refused(self, executor):
        result = _mint_and_present(executor, lambda s: epochs.REVOKED.add(s.capability_set_id))
        assert result["refusal_reason"] == "capability_revoked"

    def test_an_unreachable_epoch_store_refuses(self, executor):
        result = _mint_and_present(executor, lambda s: epochs.DOWN.update(down=True))
        assert result["refusal_reason"] == "capability_epoch_unverifiable"

    def test_assess_refuses_when_the_epoch_store_is_down(self, executor):
        epochs.DOWN["down"] = True
        body = executor.client.post("/v1/execution/assess", json={
            "tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
            "target_environment": "staging", "task_type": "monitoring"}).json()
        assert body["decision"] == "abstain"
        assert body["capability"]["refusal"] == "capability_epoch_unverifiable"
