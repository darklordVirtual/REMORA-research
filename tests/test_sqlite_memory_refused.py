# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An in-memory SQLite database is not a durable store, and is refused as one.

Every SQLite-backed durable adapter opens a connection per operation. For a
file that is correct. For ``:memory:`` each connect is a fresh empty database:
the DDL runs on one, the next operation opens another, and the ledger that
should refuse a replayed grant refuses nothing because it has no rows.

These pin the refusal at the helper, at the ledgers that flaked, and at the
production guard -- the choke point where a deployment would learn it.
"""
from __future__ import annotations

import pytest

from remora.persistence.sqlite_path import is_memory_db, refuse_memory_db


@pytest.mark.parametrize("path", [":memory:", "file::memory:?cache=shared",
                                  "file:x?mode=memory", " :MEMORY: "])
def test_every_in_memory_form_is_recognised(path: str) -> None:
    assert is_memory_db(path)


@pytest.mark.parametrize("path", ["/var/lib/remora/chain.db", "chain.db",
                                  "memory.db", "file:/tmp/x.db"])
def test_file_paths_are_not_mistaken_for_memory(path: str) -> None:
    assert not is_memory_db(path)


def test_the_refusal_names_the_ledger_and_the_consequence() -> None:
    with pytest.raises(ValueError) as caught:
        refuse_memory_db(":memory:", what="PEP consumed-jti ledger")
    msg = str(caught.value)
    assert "PEP consumed-jti ledger" in msg
    assert "empty on every read" in msg


def test_an_empty_path_is_not_refused() -> None:
    """Unset means in-process, which is a different, honestly-labelled mode."""
    refuse_memory_db("", what="anything")


def test_the_enforcement_gate_refuses_a_memory_ledger() -> None:
    from remora.enforcement.gate import EnforcementGate
    with pytest.raises(ValueError, match="consumed-jti ledger"):
        EnforcementGate(strict=True, audience="pep", db_path=":memory:")


def test_the_nonce_store_refuses_a_memory_ledger() -> None:
    from remora.enforcement.nonce_store import DurableNonceStore
    with pytest.raises(ValueError, match="lease nonce ledger"):
        DurableNonceStore(db_path=":memory:")


def test_the_idempotency_store_refuses_a_memory_ledger() -> None:
    from remora.persistence.idempotency import SQLiteIdempotencyStore
    with pytest.raises(ValueError, match="idempotency ledger"):
        SQLiteIdempotencyStore(":memory:")


def _production_env(monkeypatch, tmp_path, chain_db: str) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "t")
    monkeypatch.setenv("REMORA_API_TOKENS",
                       '{"t":{"tenant":"acme","role":"operator"}}')
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DB", str(tmp_path / "control.db"))
    monkeypatch.setenv("REMORA_CHAIN_DB", chain_db)
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.delenv("REMORA_STATE_ENDPOINT", raising=False)
    monkeypatch.setenv("REMORA_ENABLED_SURFACES", "execution")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "k")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "k")
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", "k")


def test_production_startup_refuses_a_memory_chain_db(monkeypatch, tmp_path) -> None:
    """The guard is where a deployment finds out: at startup, not at first replay."""
    from servers import api as api_mod
    _production_env(monkeypatch, tmp_path, ":memory:")
    with pytest.raises(RuntimeError, match="in-memory SQLite database"):
        api_mod._validate_production_prerequisites()


def test_production_startup_accepts_a_file_chain_db(monkeypatch, tmp_path) -> None:
    """And the same guard passes a real file, so the refusal is specific."""
    from servers import api as api_mod
    _production_env(monkeypatch, tmp_path, str(tmp_path / "chain.db"))
    api_mod._validate_production_prerequisites()
