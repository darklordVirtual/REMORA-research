# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The PEP consumed-grant ledger and the lease nonce store, against a real Postgres.

Production runs both on Postgres (REMORA_PG_DSN), yet until 2026-10-13 no test
executed either one against a server: the mutation baseline carried every
mutant in their Postgres branches as "unreachable without REMORA_PG_DSN". This
module is that missing evidence. It skips without a DSN, like the other
DSN-gated contracts, and the CI postgres-contract job and the scheduled
mutation sweep both run it against a service container, where a skip fails
the job.

Each test process works in its own schema (``search_path`` in the DSN), and
every test drops the tables it touches, so neither test order nor the
mutation sweep's parallel workers sharing one server can interfere. The sweep
sets REMORA_ENFORCEMENT_PG_DSN rather than REMORA_PG_DSN, so the other
DSN-gated modules in its selection keep skipping instead of racing on shared
tables.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

psycopg = pytest.importorskip("psycopg")
conninfo = pytest.importorskip("psycopg.conninfo")

from remora.enforcement.gate import EnforcementGate, EnforcementResult  # noqa: E402
from remora.enforcement.nonce_store import (  # noqa: E402
    DurableNonceStore,
    NonceStoreUnavailable,
)
from remora.enforcement.token import PolicyDecisionToken  # noqa: E402

BASE_DSN = (os.environ.get("REMORA_ENFORCEMENT_PG_DSN")
            or os.environ.get("REMORA_PG_DSN", ""))
pytestmark = pytest.mark.skipif(not BASE_DSN, reason="REMORA_PG_DSN not set")
# Random, not the pid: pids repeat across containers sharing one server.
SCHEMA = f"enforcement_ledgers_{uuid.uuid4().hex[:12]}"
DSN = (conninfo.make_conninfo(BASE_DSN, options=f"-c search_path={SCHEMA}")
       if BASE_DSN else "")

KEY = "postgres-ledger-contract-key"
OBS = "p" * 64
TABLES = ("pep_consumed", "pep_ledger_watermark", "lease_nonce_consumed")


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", KEY)
    for name in ("REMORA_RUNTIME_PROFILE", "REMORA_SIGNATURE_FORMAT",
                 "REMORA_PDP_ISSUER", "REMORA_PDP_SIGNING_KID",
                 "REMORA_PDP_PREVIOUS_KEYS", "REMORA_PDP_REVOKED_KIDS"):
        monkeypatch.delenv(name, raising=False)
    with psycopg.connect(BASE_DSN) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        conn.commit()
    with psycopg.connect(DSN) as conn:
        for table in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()


def _sql(query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(DSN) as conn:
        return conn.execute(query, params).fetchall()


def _columns(table: str) -> dict[str, str]:
    return dict(_sql(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s", (SCHEMA, table)))


def _grant(jti_tag: str, action: str = "accept") -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(
        action=action, observation_hash=OBS, request_id=f"req-{jti_tag}",
        issued_at=datetime.now(UTC).isoformat())


def _result(r: Any) -> tuple[bool, str, bool, bool]:
    return (r.allowed, r.reason, r.token_verified, r.strict_mode)


# ── the gate's consumed-grant ledger ─────────────────────────────────────────


def test_postgres_gate_creates_its_ledger_schema() -> None:
    EnforcementGate(dsn=DSN)
    assert _columns("pep_consumed") == {
        "jti": "text", "consumed_at": "timestamp with time zone"}
    assert _columns("pep_ledger_watermark") == {
        "id": "integer", "issued_count": "bigint",
        "last_reset_at": "timestamp with time zone", "last_reset_reason": "text"}
    # A second gate on the same database finds the schema and keeps its rows.
    gate = EnforcementGate(dsn=DSN)
    assert gate.check(_grant("schema"), OBS, consume=True).allowed
    EnforcementGate(dsn=DSN)
    assert _sql("SELECT COUNT(*) FROM pep_consumed") == [(1,)]


def test_postgres_gate_spends_a_grant_exactly_once() -> None:
    gate = EnforcementGate(dsn=DSN)
    grant = _grant("once")
    assert _result(gate.check(grant, OBS, consume=True)) == (True, "accept", True, True)
    assert _sql("SELECT jti FROM pep_consumed") == [(grant.jti,)]
    spent = gate.check(grant, OBS, consume=True)
    assert _result(spent) == (False, "token_already_consumed", True, True)
    assert spent.action == "accept"  # the refusal still names the decision it refused
    # A second gate process shares the ledger: the spend is not per-instance.
    assert _result(EnforcementGate(dsn=DSN).check(grant, OBS, consume=True)) == (
        False, "token_already_consumed", True, True)


def test_postgres_peek_never_spends_and_reports_a_spent_grant() -> None:
    gate = EnforcementGate(dsn=DSN)
    grant = _grant("peek")
    assert _result(gate.check(grant, OBS)) == (True, "accept", True, True)
    assert _sql("SELECT COUNT(*) FROM pep_consumed") == [(0,)]
    refused = _grant("refused", action="reject")
    assert not gate.check(refused, OBS, consume=True).allowed
    assert _sql("SELECT COUNT(*) FROM pep_consumed") == [(0,)]
    assert gate.check(grant, OBS, consume=True).allowed
    assert _result(gate.check(grant, OBS)) == (
        False, "token_already_consumed", True, True)


def test_postgres_watermark_counts_every_spend_and_exposes_a_deletion() -> None:
    gate = EnforcementGate(dsn=DSN)
    fresh = gate.verify_ledger()
    assert fresh == {"durable": True, "intact": True, "consumed_rows": 0,
                     "high_water_mark": 0, "last_reset_reason": None, "problems": []}
    grants = [_grant(f"w{i}") for i in range(3)]
    for g in grants:
        assert gate.check(g, OBS, consume=True).allowed
    assert _sql("SELECT id, issued_count, last_reset_reason FROM pep_ledger_watermark") == [
        (1, 3, None)]
    intact = gate.verify_ledger()
    assert (intact["intact"], intact["consumed_rows"], intact["high_water_mark"]) == (
        True, 3, 3)

    _sql_exec("DELETE FROM pep_consumed WHERE jti = %s", (grants[0].jti,))
    broken = gate.verify_ledger()
    assert (broken["durable"], broken["intact"], broken["consumed_rows"],
            broken["high_water_mark"]) == (True, False, 2, 3)
    assert broken["problems"][0].startswith(
        "ledger holds 2 consumed grants but 3 were consumed: 1 missing.")
    # The deleted grant is replayable: exactly what the watermark exists to show.
    assert gate.check(grants[0], OBS, consume=True).allowed


def test_postgres_watermark_reset_rebaselines_with_its_reason() -> None:
    gate = EnforcementGate(dsn=DSN)
    grants = [_grant(f"r{i}") for i in range(3)]
    for g in grants:
        gate.check(g, OBS, consume=True)
    _sql_exec("DELETE FROM pep_consumed WHERE jti = %s", (grants[0].jti,))
    gate.reset_ledger_watermark(reason="authorized prune, ticket 1")
    row = _sql("SELECT id, issued_count, last_reset_reason, last_reset_at IS NOT NULL "
               "FROM pep_ledger_watermark")
    assert row == [(1, 2, "authorized prune, ticket 1", True)]
    after = gate.verify_ledger()
    assert (after["intact"], after["consumed_rows"], after["high_water_mark"],
            after["last_reset_reason"]) == (True, 2, 2, "authorized prune, ticket 1")
    # A second reset overwrites the first instead of adding a row.
    gate.reset_ledger_watermark(reason="second")
    assert _sql("SELECT issued_count, last_reset_reason FROM pep_ledger_watermark") == [
        (2, "second")]
    # Spends after a reset count up from the new mark.
    assert gate.check(_grant("r-after"), OBS, consume=True).allowed
    assert gate.verify_ledger()["high_water_mark"] == 3


def test_a_postgres_ledger_outage_is_the_named_refusal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    gate = EnforcementGate(dsn=DSN)

    def down(*_a: Any, **_k: Any) -> Any:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(psycopg, "connect", down)
    grant = _grant("outage")
    with caplog.at_level(logging.INFO, logger="remora.governance"):
        result = gate.check(grant, OBS, consume=True)
    assert result == EnforcementResult(
        allowed=False, action="accept", token_verified=True,
        reason="consumed_ledger_unavailable", strict_mode=True)
    (rec,) = [r for r in caplog.records if r.name == "remora.governance"
              and r.getMessage().startswith("grant.ledger_unavailable ")]
    assert rec.levelno == logging.WARNING
    assert rec.remora == {  # type: ignore[attr-defined]
        "backend": "postgres", "error_class": "OperationalError",
        "token_jti": grant.jti}


def _sql_exec(query: str, params: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(query, params)
        conn.commit()


# ── the lease nonce store ────────────────────────────────────────────────────


def test_postgres_nonce_store_creates_its_schema() -> None:
    store = DurableNonceStore(dsn=DSN)
    assert store.consumed_count(tenant_id="t") == 0
    assert _columns("lease_nonce_consumed").keys() >= {"tenant_id", "nonce"}


def test_postgres_nonce_is_consumed_once_per_tenant() -> None:
    store = DurableNonceStore(dsn=DSN)
    assert store.try_consume("n-1", tenant_id="a") is True
    assert store.try_consume("n-1", tenant_id="a") is False
    # Another tenant's identical nonce is its own namespace.
    assert store.try_consume("n-1", tenant_id="b") is True
    # A second store instance (another worker) sees the same ledger.
    assert DurableNonceStore(dsn=DSN).try_consume("n-1", tenant_id="a") is False
    assert _sql("SELECT tenant_id, nonce FROM lease_nonce_consumed "
                "ORDER BY tenant_id") == [("a", "n-1"), ("b", "n-1")]


def test_postgres_a_replay_leaves_the_store_usable() -> None:
    """The duplicate INSERT aborts psycopg's transaction. The store must roll
    it back so the connection's clean exit does not fail, and the replay must
    still read as a duplicate rather than as an outage."""
    store = DurableNonceStore(dsn=DSN)
    assert store.try_consume("n-r", tenant_id="t") is True
    for _ in range(2):
        assert store.try_consume("n-r", tenant_id="t") is False
    assert store.try_consume("n-r2", tenant_id="t") is True
    assert store.consumed_count(tenant_id="t") == 2


def test_postgres_nonce_reads_never_consume() -> None:
    store = DurableNonceStore(dsn=DSN)
    assert store.consumed("n-q", tenant_id="t") is False
    assert store.consumed_count(tenant_id="t") == 0
    assert store.try_consume("n-q", tenant_id="t") is True
    assert store.consumed("n-q", tenant_id="t") is True
    assert store.consumed("n-q", tenant_id="other") is False
    assert store.consumed_count(tenant_id="t") == 1
    assert store.consumed_count(tenant_id="other") == 0


def test_a_postgres_nonce_store_outage_is_unknown_not_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DurableNonceStore(dsn=DSN)

    def down(*_a: Any, **_k: Any) -> Any:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(psycopg, "connect", down)
    with pytest.raises(NonceStoreUnavailable):
        store.try_consume("n-o", tenant_id="t")
    monkeypatch.undo()
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", KEY)
    assert store.try_consume("n-o", tenant_id="t") is True


def test_postgres_gate_spends_inside_the_callers_transaction() -> None:
    """Atomic admission hands the gate its open connection. The spend lands in a
    savepoint, so a duplicate leaves the caller's transaction usable, and the
    placeholder is psycopg's, so the SQL runs at all (the 2026-11-04 sweep
    found the Postgres branch of _spend_enlisted unreached)."""
    gate = EnforcementGate(dsn=DSN)
    grant = _grant("enlisted")
    with psycopg.connect(DSN) as conn:
        with conn.transaction():
            r = gate.check(grant, OBS, consume=True, connection=conn)
            assert (r.allowed, r.action, r.token_verified, r.reason, r.strict_mode) == (
                True, "accept", True, "accept", True)
            assert conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone() == (1,)
            r = gate.check(grant, OBS, consume=True, connection=conn)
            assert (r.allowed, r.action, r.token_verified, r.reason, r.strict_mode) == (
                False, "accept", True, "token_already_consumed", True)
            # The failed INSERT was confined to its savepoint.
            assert conn.execute("SELECT 1").fetchone() == (1,)
            r = gate.check(grant, OBS, consume=False, connection=conn)
            assert (r.allowed, r.reason) == (False, "token_already_consumed")
    assert _sql("SELECT jti FROM pep_consumed") == [(grant.jti,)]
    assert _sql("SELECT issued_count FROM pep_ledger_watermark") == [(1,)]
    assert _result(gate.check(grant, OBS, consume=True)) == (
        False, "token_already_consumed", True, True)


class _Abort(Exception):
    """The caller's intent could not be recorded; its transaction rolls back."""


def _abort() -> None:
    raise _Abort


def test_postgres_gate_spend_rolls_back_with_the_callers_transaction() -> None:
    gate = EnforcementGate(dsn=DSN)
    grant = _grant("rolled-back")
    with psycopg.connect(DSN) as conn, pytest.raises(_Abort):
        with conn.transaction():
            assert gate.check(grant, OBS, consume=True, connection=conn).allowed
            assert conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone() == (1,)
            _abort()
    assert _sql("SELECT COUNT(*) FROM pep_consumed") == [(0,)]
    assert _result(gate.check(grant, OBS, consume=True)) == (True, "accept", True, True)


def test_postgres_gate_on_a_broken_callers_connection_names_its_backend(
        caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        def transaction(self) -> Any:
            raise psycopg.OperationalError("connection is closed")

        def execute(self, *a: Any, **k: Any) -> Any:
            raise psycopg.OperationalError("connection is closed")

    gate = EnforcementGate(dsn=DSN)
    with caplog.at_level(logging.WARNING, logger="remora.governance"):
        r = gate.check(_grant("broken"), OBS, consume=True, connection=Broken())
    assert (r.allowed, r.reason) == (False, "consumed_ledger_unavailable")
    [record] = [r for r in caplog.records if r.name == "remora.governance"
                and r.getMessage().startswith("grant.ledger_unavailable ")]
    payload = record.remora  # type: ignore[attr-defined]
    assert (payload["backend"], payload["error_class"]) == ("postgres", "OperationalError")
    assert _sql("SELECT COUNT(*) FROM pep_consumed") == [(0,)]
