# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REM-047 wiring: the transactional audit path as the API actually uses it.

`tests/test_audit_outbox_atomicity.py` covers the mechanism. These cover the
binding: that an append inside a state transaction joins that transaction, that
an append outside one still reaches the chain directly, and that the recovery
drain runs on the same lazy sweep as the stale-dispatch reconciler rather than
waiting for a daemon nobody deployed.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def exec_mod(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))

    import servers.execution_api as module
    from remora.governance.tenant_chain import TenantAuditChain

    module._CHAIN = TenantAuditChain()
    module._QUEUES.clear()
    module._ITEM_TENANT.clear()
    return module


def chain_payloads(module, tenant="acme"):
    return [entry.payload for entry in module._CHAIN.entries(tenant)]


def test_outside_a_transaction_the_event_goes_straight_to_the_chain(exec_mod):
    """There is nothing to be atomic with, so there is nothing to defer."""

    entry = exec_mod.chain_append_transactional(
        "acme", {"event": "standalone"}, key="acme|standalone"
    )
    assert entry is not None
    assert [p["event"] for p in chain_payloads(exec_mod)] == ["standalone"]


def test_inside_a_transaction_the_event_is_deferred_then_projected(exec_mod, tmp_path):
    """The window REM-047 is about, exercised through the module's own helper."""

    conn = sqlite3.connect(tmp_path / "chain.db")
    token = exec_mod._ACTIVE_TX_CONNECTION.set(conn)
    try:
        deferred = exec_mod.chain_append_transactional(
            "acme", {"event": "review_approved", "item_id": "i-1"}, key="acme|i-1|APPROVED"
        )
        conn.commit()
    finally:
        exec_mod._ACTIVE_TX_CONNECTION.reset(token)
        conn.close()

    # Nothing has reached the chain yet: the event is durable, not yet projected.
    assert deferred is None
    assert chain_payloads(exec_mod) == []

    assert exec_mod.drain_audit_outbox("acme") == 1
    assert [p["item_id"] for p in chain_payloads(exec_mod)] == ["i-1"]


def test_the_drain_is_idempotent(exec_mod, tmp_path):
    conn = sqlite3.connect(tmp_path / "chain.db")
    token = exec_mod._ACTIVE_TX_CONNECTION.set(conn)
    try:
        exec_mod.chain_append_transactional("acme", {"event": "e"}, key="acme|e")
        conn.commit()
    finally:
        exec_mod._ACTIVE_TX_CONNECTION.reset(token)
        conn.close()

    assert exec_mod.drain_audit_outbox("acme") == 1
    assert exec_mod.drain_audit_outbox("acme") == 0
    assert len(chain_payloads(exec_mod)) == 1


def test_the_stale_dispatch_sweep_also_recovers_audit_events(exec_mod, tmp_path):
    """Recovery happens on the next interaction, because no daemon is deployed."""

    conn = sqlite3.connect(tmp_path / "chain.db")
    token = exec_mod._ACTIVE_TX_CONNECTION.set(conn)
    try:
        exec_mod.chain_append_transactional("acme", {"event": "swept"}, key="acme|swept")
        conn.commit()
    finally:
        exec_mod._ACTIVE_TX_CONNECTION.reset(token)
        conn.close()

    assert chain_payloads(exec_mod) == []
    exec_mod.reconcile_stale_dispatches("acme")
    assert [p["event"] for p in chain_payloads(exec_mod)] == ["swept"]


def test_with_no_durable_backend_there_is_nothing_to_drain(exec_mod, monkeypatch):
    """Library and research configuration: no state store, so no outbox."""

    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    assert exec_mod.drain_audit_outbox("acme") == 0


def test_a_drain_that_cannot_reach_the_store_does_not_fail_the_request(
    exec_mod, monkeypatch
):
    """A recoverable gap must not become a failed request; the row waits."""

    monkeypatch.setenv("REMORA_CHAIN_DB", "/definitely/not/a/writable/path/chain.db")
    assert exec_mod.drain_audit_outbox("acme") == 0


def test_the_postgres_branch_is_selected_when_a_dsn_is_configured(exec_mod, monkeypatch):
    """The branch selection, without a live server: psycopg is asked, not sqlite."""

    monkeypatch.setenv("REMORA_PG_DSN", "postgresql://nobody@127.0.0.1:1/none")
    calls: list[str] = []

    class FakePsycopg:
        @staticmethod
        def connect(dsn):
            calls.append(dsn)
            raise OSError("no server here, which is the point")

    monkeypatch.setitem(__import__("sys").modules, "psycopg", FakePsycopg)
    # Unreachable is not unused: the drain returns 0 and the row waits.
    assert exec_mod.drain_audit_outbox("acme") == 0
    assert calls == ["postgresql://nobody@127.0.0.1:1/none"]


# ── The routes, not just the helper ───────────────────────────────────────
#
# The mechanism above existed and nothing in production called it: every
# state-transition audit event was still appended AFTER its transaction had
# committed (audit 2026-09-02). These bind the routes to the transactional
# path, so a regression that moves an append back outside the transaction
# fails here rather than in a post-mortem.

from fastapi.testclient import TestClient  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "wiring-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def durable_client(monkeypatch, tmp_path):
    """A client with a real state store, which is what makes the outbox live."""

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "wiring-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "reviewer-1")
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
    return TestClient(api_mod.app), exec_mod


def _pending_item(client):
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert item_id
    return item_id


def _events(exec_mod, tenant="acme"):
    return [e.payload.get("event") for e in exec_mod._CHAIN.entries(tenant)]


def test_approve_enqueues_its_audit_event_on_the_state_transaction(durable_client):
    client, exec_mod = durable_client
    item_id = _pending_item(client)

    r = client.post("/v1/execution/approve",
                    json={"item_id": item_id, "approval_ttl_seconds": 300})
    assert r.status_code == 200, r.text

    # Not yet in the chain: it is durable in the outbox, on the same
    # transaction as the approval itself.
    assert "approved" not in _events(exec_mod)
    audit = r.json()["audit"]
    assert audit["deferred"] is True
    assert audit["sequence_no"] is None, "no chain index exists yet; inventing one lies"
    assert audit["idempotency_key"]

    assert exec_mod.drain_audit_outbox("acme") == 1
    assert "approved" in _events(exec_mod)


def test_reject_enqueues_its_audit_event_on_the_state_transaction(durable_client):
    client, exec_mod = durable_client
    item_id = _pending_item(client)

    r = client.post("/v1/execution/reject",
                    json={"item_id": item_id, "reason": "not this one"})
    assert r.status_code == 200, r.text
    assert "rejected" not in _events(exec_mod)
    assert r.json()["audit"]["deferred"] is True

    assert exec_mod.drain_audit_outbox("acme") == 1
    assert "rejected" in _events(exec_mod)


def test_revocation_and_its_audit_event_commit_together(durable_client):
    """The clearest case: the revocation committed, the audit post did not."""

    client, exec_mod = durable_client
    r = client.post("/v1/execution/revoke-principal",
                    json={"principal": "operator-9", "reason": "left the team"})
    assert r.status_code == 200, r.text
    assert "principal_revoked" not in _events(exec_mod)

    assert exec_mod.drain_audit_outbox("acme") == 1
    assert "principal_revoked" in _events(exec_mod)


def test_the_deferred_event_is_projected_exactly_once(durable_client):
    client, exec_mod = durable_client
    item_id = _pending_item(client)
    client.post("/v1/execution/approve",
                json={"item_id": item_id, "approval_ttl_seconds": 300})

    exec_mod.drain_audit_outbox("acme")
    exec_mod.drain_audit_outbox("acme")
    assert _events(exec_mod).count("approved") == 1


def test_without_a_durable_store_the_audit_block_still_carries_an_index(
    monkeypatch, tmp_path
):
    """No state store means no transaction to join, so nothing is deferred."""

    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "wiring-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "reviewer-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_outbox()
    client = TestClient(api_mod.app)

    item_id = _pending_item(client)
    body = client.post("/v1/execution/approve",
                       json={"item_id": item_id, "approval_ttl_seconds": 300}).json()
    assert body["audit"]["deferred"] is False
    assert isinstance(body["audit"]["sequence_no"], int)
