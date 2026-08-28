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
