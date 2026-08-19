# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Durable assess-idempotency store (review finding: process-local LRU forked
proposal identity on retry after restart)."""
from __future__ import annotations

from pathlib import Path

from remora.persistence.idempotency import (
    IdempotencyStore,
    SQLiteIdempotencyStore,
    build_idempotency_store,
)


def test_builder_follows_the_shared_durability_switches(tmp_path: Path) -> None:
    assert build_idempotency_store({}).durable is False
    store = build_idempotency_store({"REMORA_CHAIN_DB": str(tmp_path / "s.db")})
    assert isinstance(store, SQLiteIdempotencyStore) and store.durable is True


def test_sqlite_store_survives_a_new_instance(tmp_path: Path) -> None:
    """The restart scenario: a second store over the same file (a new
    process) must observe the original response — the retry can no longer
    fork the proposal identity."""
    db = str(tmp_path / "idem.db")
    SQLiteIdempotencyStore(db).put("t1", "key-1", {"proposal_id": "p-original"})
    fresh = SQLiteIdempotencyStore(db)
    assert fresh.get("t1", "key-1") == {"proposal_id": "p-original"}


def test_first_write_wins_on_concurrent_retry(tmp_path: Path) -> None:
    db = str(tmp_path / "idem.db")
    store = SQLiteIdempotencyStore(db)
    store.put("t1", "key-1", {"proposal_id": "p-first"})
    store.put("t1", "key-1", {"proposal_id": "p-second"})
    assert store.get("t1", "key-1") == {"proposal_id": "p-first"}


def test_tenant_scoping(tmp_path: Path) -> None:
    db = str(tmp_path / "idem.db")
    store = SQLiteIdempotencyStore(db)
    store.put("t1", "shared-key", {"proposal_id": "p-t1"})
    assert store.get("t2", "shared-key") is None


def test_assess_replays_identically_across_store_instances(tmp_path: Path,
                                                           monkeypatch) -> None:
    """End-to-end through the API: with a durable store, replaying the same
    idempotency key after a simulated restart returns the SAME proposal_id
    instead of minting a new one."""
    import importlib

    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    import servers.execution_api as exec_mod
    importlib.reload(exec_mod)
    try:
        from fastapi.testclient import TestClient

        import servers.api as api_mod
        importlib.reload(api_mod)
        client = TestClient(api_mod.app)
        payload = {"tool_name": "read_telemetry",
                   "arguments": {"sensor": "PT-9"},
                   "target_environment": "staging",
                   "idempotency_key": "retry-me"}
        first = client.post("/v1/execution/assess", json=payload,
                            headers={"Authorization": "Bearer ot-agent"})
        assert first.status_code == 200, first.text

        # Simulated restart: the process-local handle is dropped; the durable
        # table is what must answer.
        exec_mod._reset_idempotency_store()
        second = client.post("/v1/execution/assess", json=payload,
                             headers={"Authorization": "Bearer ot-agent"})
        assert second.json()["proposal_id"] == first.json()["proposal_id"]
    finally:
        monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
        importlib.reload(exec_mod)
        import servers.api as api_mod
        importlib.reload(api_mod)


def test_in_process_store_is_explicitly_not_durable() -> None:
    assert IdempotencyStore().durable is False
