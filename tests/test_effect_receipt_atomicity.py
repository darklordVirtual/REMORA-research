# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Receipt uniqueness and its audit evidence are one atomic write."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from remora.governance.tenant_chain import (
    POSTGRES_DDL,
    SQLiteTenantChain,
    TenantAuditChain,
)


def _payload() -> dict[str, str]:
    return {
        "event": "effect_verified",
        "dispatch_id": "dispatch-1",
        "status": "EFFECT_VERIFIED",
    }


def test_in_memory_append_once_has_one_winner_under_concurrency() -> None:
    chain = TenantAuditChain()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(
            lambda _n: chain.append_once(
                "acme", "effect-receipt:dispatch-1", _payload()),
            range(32),
        ))

    assert sum(entry is not None for entry in results) == 1
    assert len(chain.entries("acme")) == 1
    assert chain.verify("acme") == (True, [])


def test_sqlite_append_once_has_one_winner_across_connections(tmp_path) -> None:
    db_path = str(tmp_path / "chain.db")
    SQLiteTenantChain(db_path)  # install the schema before threads race

    def attempt(_n: int):
        return SQLiteTenantChain(db_path).append_once(
            "acme", "effect-receipt:dispatch-1", _payload())

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(32)))

    reopened = SQLiteTenantChain(db_path)
    assert sum(entry is not None for entry in results) == 1
    assert len(reopened.entries("acme")) == 1
    assert reopened.verify("acme") == (True, [])


def test_sqlite_failed_audit_append_rolls_back_the_receipt_claim(tmp_path) -> None:
    """Regression: a separate pre-append ledger created phantom settlements."""
    chain = SQLiteTenantChain(str(tmp_path / "chain.db"))
    conn = chain._conn()
    conn.execute(
        "CREATE TRIGGER fail_effect_append BEFORE INSERT ON tenant_chain_entry "
        "BEGIN SELECT RAISE(ABORT, 'injected append failure'); END"
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected append failure"):
        chain.append_once(
            "acme", "effect-receipt:dispatch-1", _payload())

    assert conn.execute(
        "SELECT count(*) FROM tenant_chain_idempotency"
    ).fetchone() == (0,), "a failed append must not leave a phantom claim"
    assert chain.entries("acme") == ()

    conn.execute("DROP TRIGGER fail_effect_append")
    assert chain.append_once(
        "acme", "effect-receipt:dispatch-1", _payload()) is not None
    assert len(chain.entries("acme")) == 1


def test_postgres_contract_places_idempotency_in_the_chain_schema() -> None:
    assert "CREATE TABLE IF NOT EXISTS tenant_chain_idempotency" in POSTGRES_DDL
    assert "PRIMARY KEY (tenant_id, idempotency_key)" in POSTGRES_DDL
