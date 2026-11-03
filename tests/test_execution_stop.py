# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The operator's stop switch (SDD unified capability execution v1.1, P0 item 7; gate G10).

``POST /v1/execution/stop`` writes one durable flag per tenant, the
authority-epoch subject ``execution:stop`` in the store the lease nonce ledger
uses, with its audit event in the same transaction. The governed dispatcher
reads it before anything is spent: a valid lease is refused as
``execution_stopped`` with its nonce unspent, and runs after ``/resume``. The
authority refuses to mint while stopped. A store that cannot answer refuses
as ``execution_stop_unverifiable``. Without durable state there is no stop,
and the routes say so. The stop across a real process boundary and an
executor restart is in ``tests/conformance/test_execution_boundary_process_split.py``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.execution.dispatch import issue_execution_lease  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from tests.test_dispatch_leased_endpoint import CALL, SEMANTIC  # noqa: E402

OPERATOR = "operator-1"


@pytest.fixture()
def rig(monkeypatch, tmp_path):
    """One process that is authority and executor, on a SQLite state file."""
    key = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    for name in (signing.ENV_HMAC, signing.ENV_HMAC_FALLBACK, "REMORA_PG_DSN",
                 "REMORA_STATE_ENDPOINT", "REMORA_WS1_ADMISSION", "REMORA_FLOW_CONTROL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, key.public_key().public_bytes_raw().hex())
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, key.private_bytes_raw().hex())
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from tests import dispatcher_registry_fixture as registry

    registry.CALLS.clear()
    capability_calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: OPERATOR)
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: capability_calls.append((role, tenant, cap)))
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    monkeypatch.setattr(exec_mod, "_STOP_EPOCHS", None)
    exec_mod._reset_outbox()
    exec_mod._reset_tool_dispatcher()
    yield SimpleNamespace(client=TestClient(api_mod.app), registry=registry, exec_mod=exec_mod,
                          bundle=exec_mod._current_policy_bundle_hash(),
                          capability_calls=capability_calls, monkeypatch=monkeypatch)
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()


def _lease(rig, tenant: str = "acme"):
    return issue_execution_lease(
        tenant=tenant, principal="employee-1", tool_call=SimpleNamespace(**CALL),
        semantic=SEMANTIC, now=datetime.now(UTC), policy_bundle_hash=rig.bundle,
        # RMR-SEC-0001: the executor refuses a lease linked to no proposal/grant.
        proposal_id="p-1", grant_jti="g-1")


def _dispatch(rig, lease, tenant_id: str = "acme") -> dict:
    # RMR-SEC-0001: only the execution domain serves /dispatch-leased; this
    # rig drives authority routes (/stop, /resume) in the same process.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
        r = rig.client.post("/v1/execution/dispatch-leased",
                            json={"lease": lease.to_dict(), "tool_call": CALL, "tenant_id": tenant_id})
    assert r.status_code == 200, r.text
    return r.json()["tool_execution"]


def _stop(rig, reason: str | None = None) -> dict:
    r = rig.client.post("/v1/execution/stop", json={"reason": reason} if reason else {})
    assert r.status_code == 200, r.text
    return r.json()


def _resume(rig, reason: str | None = None) -> dict:
    r = rig.client.post("/v1/execution/resume", json={"reason": reason} if reason else {})
    assert r.status_code == 200, r.text
    return r.json()


def _events(rig, name: str) -> list[dict]:
    rig.exec_mod.drain_audit_outbox("acme")
    return [e.payload for e in rig.exec_mod._CHAIN.entries("acme") if e.payload.get("event") == name]


def test_a_stop_refuses_a_valid_lease_and_leaves_its_nonce_unspent(rig):
    lease = _lease(rig)
    assert _stop(rig, "incident 7") == {"stopped": True, "epoch": 1, "stopped_by": OPERATOR}
    refused = _dispatch(rig, lease)
    assert (refused["executed"], refused["refusal_reason"]) == (False, "execution_stopped")
    assert rig.registry.CALLS == []
    assert _resume(rig)["stopped"] is False
    ran = _dispatch(rig, lease)            # the same lease: the refusal spent no nonce
    assert ran["executed"] is True
    assert len(rig.registry.CALLS) == 1
    assert _dispatch(rig, lease)["refusal_reason"] == "nonce_already_consumed"


def test_the_stop_survives_a_rebuilt_dispatcher(rig):
    """The flag is durable state, not a field of the process that set it."""
    _stop(rig)
    rig.exec_mod._reset_tool_dispatcher()
    rig.monkeypatch.setattr(rig.exec_mod, "_STOP_EPOCHS", None)
    assert _dispatch(rig, _lease(rig))["refusal_reason"] == "execution_stopped"
    assert rig.registry.CALLS == []


def test_the_authority_mints_nothing_while_stopped(rig):
    from servers.execution_contracts import ToolCallRequest

    _stop(rig)
    issued: list[object] = []
    rig.monkeypatch.setattr(rig.exec_mod, "_local_dispatcher",
                            lambda lease: issued.append(lease) or None)
    result = rig.exec_mod._dispatch_under_lease(
        tenant="acme", principal="employee-1", tool_call=ToolCallRequest(**CALL),
        semantic=SEMANTIC, now=datetime.now(UTC), proposal_id="p-1")
    assert result == {"executed": False, "refusal_reason": "execution_stopped",
                      "proposal_id": "p-1"}
    assert issued == [] and rig.registry.CALLS == []


def test_the_change_is_recorded_with_the_operator_and_the_reason(rig):
    _stop(rig, "incident 7")
    _resume(rig, "cleared")
    stopped, resumed = _events(rig, "execution_stopped")[-1], _events(rig, "execution_resumed")[-1]
    assert (stopped["stopped_by"], stopped["reason"], stopped["epoch"]) == (OPERATOR, "incident 7", 1)
    assert (resumed["stopped_by"], resumed["reason"], resumed["epoch"]) == (OPERATOR, "cleared", 2)
    r = rig.client.get("/v1/execution/stop")
    assert r.status_code == 200 and r.json() == {"stopped": False, "epoch": 2}


def test_stop_and_resume_need_review_and_the_status_needs_read(rig):
    _stop(rig)
    _resume(rig)
    rig.client.get("/v1/execution/stop")
    assert rig.capability_calls[-3:] == [("reviewer", "acme", "review"),
                                         ("reviewer", "acme", "review"),
                                         ("reviewer", "acme", "read")]


def test_a_store_that_cannot_answer_refuses_rather_than_runs(rig):
    lease = _lease(rig)

    def down(tenant):
        raise RuntimeError("authority store unreachable")

    rig.monkeypatch.setattr(rig.exec_mod, "_execution_stopped", down)
    refused = _dispatch(rig, lease)
    assert refused["refusal_reason"] == "execution_stop_unverifiable"
    assert rig.registry.CALLS == []
    rig.monkeypatch.undo()


def test_a_stop_is_scoped_to_its_tenant(rig):
    import servers.api as api_mod

    _stop(rig)
    rig.monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("beta", "reviewer"))
    ran = _dispatch(rig, _lease(rig, tenant="beta"), tenant_id="beta")
    assert ran["executed"] is True
    assert len(rig.registry.CALLS) == 1


def test_without_durable_state_there_is_no_stop(rig):
    rig.monkeypatch.delenv("REMORA_CHAIN_DB")
    rig.monkeypatch.setattr(rig.exec_mod, "_STOP_EPOCHS", None)
    for method, path in (("post", "/v1/execution/stop"), ("post", "/v1/execution/resume"),
                         ("get", "/v1/execution/stop")):
        r = getattr(rig.client, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 409, (path, r.text)
