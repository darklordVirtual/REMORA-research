# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""/v1/execution/dispatch-leased: the execution domain's only entry (ADR-A).

This endpoint is the whole inbound surface of the execution trust domain. It
receives a lease minted somewhere else and either dispatches exactly what that
lease binds, or refuses.

The risk it introduces, and the reason these tests exist: an endpoint that
accepts a lease over the wire could be written to trust the lease because it
arrived from an internal host. Then the split would be worthless -- anything
that can reach the internal network could execute anything. So every test here
presents a lease that is *authentic* and asks the endpoint to run something the
lease does not authorise.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _security_extra import require_security_extra  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.enforcement import lease_signing as signing  # noqa: E402

# Skips locally without the 'security' extra; fails hard in CI, where a skip
# would silently withhold this file's evidence.
require_security_extra()

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

from remora.execution.dispatch import issue_execution_lease  # noqa: E402

CALL = {"tool_name": "update_work_order",
        "arguments": {"work_order_id": "WO-1", "status": "closed"},
        "target_environment": "staging"}
SEMANTIC = {"tool_contract_bundle_hash": "", "intent_authority_hash": ""}


@pytest.fixture()
def executor(monkeypatch):
    """A process configured as the EXECUTION domain: public key, no private."""
    key = ed25519.Ed25519PrivateKey.generate()
    seed = key.private_bytes_raw().hex()
    public = key.public_key().public_bytes_raw().hex()

    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE",
                       "tests.dispatcher_registry_fixture")
    monkeypatch.delenv(signing.ENV_HMAC, raising=False)
    monkeypatch.delenv(signing.ENV_HMAC_FALLBACK, raising=False)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)   # authority, for now

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from tests import dispatcher_registry_fixture as registry

    registry.CALLS.clear()
    monkeypatch.setattr(api_mod, "_authenticate",
                        lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_tool_dispatcher()

    bundle = exec_mod._current_policy_bundle_hash()
    return SimpleNamespace(
        client=TestClient(api_mod.app), registry=registry, bundle=bundle,
        seed=seed, public=public, monkeypatch=monkeypatch)


def _lease(executor, **over):
    call = {**CALL, **over.pop("call", {})}
    return issue_execution_lease(
        tenant=over.pop("tenant", "acme"),
        principal=over.pop("principal", "employee-1"),
        tool_call=SimpleNamespace(**call),
        semantic=SEMANTIC,
        now=datetime.now(UTC),
        policy_bundle_hash=over.pop("bundle", executor.bundle),
    )


def _post(executor, lease, call=None, **body):
    """Present the lease. From here on this process holds only the public key."""
    executor.monkeypatch.delenv(signing.ENV_ED25519_PRIVATE, raising=False)
    payload = {"lease": lease.to_dict(),
               "tool_call": call or CALL,
               "tenant_id": "acme"}
    payload.update(body)
    return executor.client.post("/v1/execution/dispatch-leased", json=payload)


# ── the endpoint works, holding no signing material ────────────────────────

def test_a_lease_bound_to_this_call_executes(executor):
    """The happy path, with the private key removed before the request."""
    response = _post(executor, _lease(executor))
    assert response.status_code == 200
    body = response.json()
    assert body["tool_execution"]["executed"] is True
    assert len(executor.registry.CALLS) == 1
    assert signing.public_key_only() is True, (
        "the executor must have been holding only verification material")


# ── an authentic lease for a different act is still refused ────────────────

def test_a_lease_for_different_arguments_is_refused(executor):
    """Authentic signature, different call. This is the test that matters."""
    lease = _lease(executor)
    response = _post(executor, lease,
                     call={**CALL, "arguments": {"work_order_id": "WO-999",
                                                 "status": "closed"}})
    assert response.status_code == 200
    body = response.json()
    assert body["tool_execution"]["executed"] is False
    assert executor.registry.CALLS == []


def test_a_lease_for_a_different_tool_is_refused(executor):
    lease = _lease(executor)
    response = _post(executor, lease, call={**CALL, "tool_name": "read_telemetry"})
    assert response.json()["tool_execution"]["executed"] is False
    assert executor.registry.CALLS == []


def test_a_lease_for_a_different_target_is_refused(executor):
    lease = _lease(executor)
    response = _post(executor, lease,
                     call={**CALL, "target_environment": "prod"})
    assert response.json()["tool_execution"]["executed"] is False
    assert executor.registry.CALLS == []


def test_a_lease_for_another_tenant_is_refused(executor):
    """The authenticated tenant governs; a foreign lease cannot borrow it."""
    lease = _lease(executor, tenant="globex")
    response = _post(executor, lease)
    assert response.json()["tool_execution"]["executed"] is False
    assert executor.registry.CALLS == []


def test_a_presented_tenant_that_disagrees_is_refused_outright(executor):
    """Mismatched wire tenant is a 409, before any dispatch decision."""
    response = _post(executor, _lease(executor), tenant_id="globex")
    assert response.status_code == 409
    assert executor.registry.CALLS == []


def test_a_lease_from_a_foreign_key_is_refused(executor):
    """A second valid Ed25519 authority this executor does not trust."""
    rogue = ed25519.Ed25519PrivateKey.generate()
    executor.monkeypatch.setenv(signing.ENV_ED25519_PRIVATE,
                                rogue.private_bytes_raw().hex())
    lease = _lease(executor)

    executor.monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, executor.public)
    response = _post(executor, lease)
    assert response.json()["tool_execution"]["executed"] is False
    assert executor.registry.CALLS == []


def test_a_stale_policy_bundle_is_refused(executor):
    """A lease issued under an older bundle must not execute under a new one."""
    lease = _lease(executor, bundle="some-older-bundle-hash")
    response = _post(executor, lease)
    assert response.json()["tool_execution"]["executed"] is False
    assert executor.registry.CALLS == []


# ── malformed input, and the one-time property across the wire ─────────────

def test_a_malformed_lease_is_refused_as_a_conflict(executor):
    response = executor.client.post("/v1/execution/dispatch-leased", json={
        "lease": {"not": "a lease"}, "tool_call": CALL, "tenant_id": "acme"})
    assert response.status_code == 409
    assert "malformed execution lease" in response.json()["detail"]


def test_the_same_lease_cannot_be_replayed_over_the_endpoint(executor):
    """Single-use survives the boundary crossing."""
    lease = _lease(executor)
    assert _post(executor, lease).json()["tool_execution"]["executed"] is True

    replay = _post(executor, lease)
    assert replay.json()["tool_execution"]["executed"] is False
    assert len(executor.registry.CALLS) == 1


def test_the_actor_cannot_be_asserted_by_the_caller(executor):
    """RMR-005: the request body must not be able to name the actor.

    The endpoint preferred req.actor_identity over anything authenticated, so a
    caller holding a stolen lease and the hop credential could put the victim's
    identity in the body and satisfy the lease's own actor check -- the exact
    binding that check exists to enforce.

    The actor now comes from the lease, inside the Ed25519-signed payload. An
    extra body field is ignored rather than honoured, which is asserted here by
    sending one that would previously have been decisive.
    """
    lease = _lease(executor, principal="victim-actor")
    executor.monkeypatch.delenv(signing.ENV_ED25519_PRIVATE, raising=False)

    response = executor.client.post("/v1/execution/dispatch-leased", json={
        "lease": lease.to_dict(), "tool_call": CALL, "tenant_id": "acme",
        # The old attack: assert the victim's identity from the wire.
        "actor_identity": "victim-actor",
        # And an attacker-chosen one, to show neither is consulted.
        "principal": "authenticated-attacker"})

    assert response.status_code == 200
    # It executes under the identity the AUTHORITY signed, not one supplied.
    assert response.json()["tool_execution"]["executed"] is True
    assert lease.actor_identity == "victim-actor"


def test_the_contract_no_longer_accepts_an_actor_field(executor):
    """The field is gone from the model, not merely ignored by the handler.

    A field that is accepted and ignored invites someone to wire it back up.
    """
    from servers.execution_contracts import DispatchLeasedRequest

    assert "actor_identity" not in DispatchLeasedRequest.model_fields
    assert "now" not in DispatchLeasedRequest.model_fields
