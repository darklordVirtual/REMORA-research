# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AACP-X-01: the SQLite tenant chain must detect tail truncation.

Before the fix ``SQLiteTenantChain`` kept no head record, so deleting its
newest entries left a prefix that verified. It now keeps ``tenant_chain_head``
like ``PostgresTenantChain``, written in the same ``BEGIN IMMEDIATE``
transaction as the entry, and ``verify`` compares it with the last entry.

Limit (asserted below, not hidden): an attacker who rewrites both the entries
and the head row in the same file defeats a local head. Only an
``expected_head`` held elsewhere detects that; ``verify_report`` says which
of the two was checked.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from remora.governance.tenant_chain import (
    HEAD_ORIGIN_APPEND,
    HEAD_ORIGIN_LEGACY,
    INTEGRITY_SCOPE_ANCHORED,
    INTEGRITY_SCOPE_LOCAL,
    ChainHeadInconsistent,
    SQLiteTenantChain,
)

T = "acme"


@pytest.fixture(autouse=True)
def _no_signing_key(monkeypatch):
    monkeypatch.delenv("REMORA_AUDIT_SIGNING_KEY", raising=False)


def _chain(tmp_path, n=3, tenant=T):
    db = str(tmp_path / "chain.db")
    chain = SQLiteTenantChain(db)
    for i in range(n):
        chain.append(tenant, {"event": "aacp", "n": i})
    return chain, db


def _sql(db, statement, params=()):
    with sqlite3.connect(db) as conn:
        conn.execute(statement, params)


def _delete_newest(db, k=1, tenant=T):
    for _ in range(k):
        _sql(db, "DELETE FROM tenant_chain_entry WHERE tenant_id = ? AND sequence_no = "
                 "(SELECT MAX(sequence_no) FROM tenant_chain_entry WHERE tenant_id = ?)",
             (tenant, tenant))


def test_intact_chain_verifies_and_head_matches_last_entry(tmp_path):
    chain, _ = _chain(tmp_path)
    ok, problems = chain.verify(T)
    assert ok and problems == []
    last = chain.entries(T)[-1]
    assert chain.stored_head(T) == (last.sequence_no, last.entry_hash)


def test_deleting_the_newest_entry_is_detected(tmp_path):
    chain, db = _chain(tmp_path)
    _delete_newest(db)
    ok, problems = chain.verify(T)
    assert not ok
    assert any(p.startswith("stored_head_mismatch:stored_seq=2:actual_seq=1") for p in problems)


def test_deleting_several_newest_entries_is_detected(tmp_path):
    chain, db = _chain(tmp_path, n=5)
    _delete_newest(db, k=3)
    ok, problems = chain.verify(T)
    assert not ok
    assert any(p.startswith("stored_head_mismatch:stored_seq=4:actual_seq=1") for p in problems)


def test_deleting_every_entry_is_detected(tmp_path):
    chain, db = _chain(tmp_path)
    _sql(db, "DELETE FROM tenant_chain_entry WHERE tenant_id = ?", (T,))
    ok, problems = chain.verify(T)
    assert not ok
    assert any(p.startswith("stored_head_mismatch:stored_seq=2:actual_seq=-1") for p in problems)


def test_head_persists_across_restart(tmp_path):
    chain, db = _chain(tmp_path)
    head = chain.stored_head(T)
    reopened = SQLiteTenantChain(db)
    assert reopened.stored_head(T) == head
    assert reopened.verify(T) == (True, [])
    reopened.append(T, {"n": 3})
    assert SQLiteTenantChain(db).verify(T) == (True, [])
    _delete_newest(db)
    assert not SQLiteTenantChain(db).verify(T)[0]


def test_tenants_have_independent_heads(tmp_path):
    chain, db = _chain(tmp_path)
    chain.append("other", {"n": 0})
    _delete_newest(db, tenant="other")
    assert chain.verify(T) == (True, [])
    assert not chain.verify("other")[0]


def test_append_after_truncation_keeps_the_evidence(tmp_path):
    # The next append must not move the head over the cut: it links to the
    # stored head, so the gap stays visible instead of being papered over.
    chain, db = _chain(tmp_path)
    _delete_newest(db)
    chain.append(T, {"n": "after"})
    ok, problems = chain.verify(T)
    assert not ok
    assert "sequence_gap_at:2" in problems
    assert "chain_break_at:2" in problems


def test_missing_head_row_fails_safely(tmp_path):
    chain, db = _chain(tmp_path)
    _sql(db, "DELETE FROM tenant_chain_head WHERE tenant_id = ?", (T,))
    ok, problems = chain.verify(T)
    assert not ok
    assert "stored_head_missing" in problems
    with pytest.raises(ChainHeadInconsistent):
        chain.append(T, {"n": 9})
    assert len(chain.entries(T)) == 3


@pytest.mark.parametrize("seq,hash_", [("two", "a" * 64), (2, "not-a-hash"), (2, None), (None, "a" * 64)])
def test_malformed_head_row_fails_safely(tmp_path, seq, hash_):
    chain, db = _chain(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("DROP TABLE tenant_chain_head")
        conn.execute("CREATE TABLE tenant_chain_head (tenant_id TEXT PRIMARY KEY, head_hash, "
                     "head_sequence, head_origin TEXT, baseline_sequence)")
        conn.execute("INSERT INTO tenant_chain_head VALUES (?,?,?,?,?)",
                     (T, hash_, seq, HEAD_ORIGIN_APPEND, -1))
    ok, problems = chain.verify(T)
    assert not ok
    assert "stored_head_malformed" in problems
    with pytest.raises(ChainHeadInconsistent):
        chain.append(T, {"n": 9})


def test_outdated_head_fails_verification(tmp_path):
    chain, db = _chain(tmp_path)
    first = chain.entries(T)[0]
    _sql(db, "UPDATE tenant_chain_head SET head_sequence = ?, head_hash = ? WHERE tenant_id = ?",
         (first.sequence_no, first.entry_hash, T))
    ok, problems = chain.verify(T)
    assert not ok
    assert any(p.startswith("stored_head_mismatch:stored_seq=0:actual_seq=2") for p in problems)


def test_head_ahead_of_entries_with_wrong_hash_fails(tmp_path):
    chain, db = _chain(tmp_path)
    _sql(db, "UPDATE tenant_chain_head SET head_hash = ? WHERE tenant_id = ?", ("f" * 64, T))
    assert not chain.verify(T)[0]


class _FailingHeadWrite:
    """A connection that fails on the head write, after the entry insert."""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *args):
        if "tenant_chain_head" in sql and sql.lstrip().upper().startswith(("INSERT", "UPDATE")):
            raise sqlite3.OperationalError("simulated crash between entry and head")
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_interrupted_append_leaves_neither_entry_nor_head(tmp_path):
    chain, db = _chain(tmp_path)
    head = chain.stored_head(T)
    real = chain._conn()
    chain._local.conn = _FailingHeadWrite(real)
    with pytest.raises(sqlite3.OperationalError):
        chain.append(T, {"n": "lost"})
    chain._local.conn = real
    assert len(chain.entries(T)) == 3
    assert chain.stored_head(T) == head
    assert chain.verify(T) == (True, [])


def test_interrupted_append_once_releases_the_key(tmp_path):
    chain, _ = _chain(tmp_path)
    real = chain._conn()
    chain._local.conn = _FailingHeadWrite(real)
    with pytest.raises(sqlite3.OperationalError):
        chain.append_once(T, "k1", {"n": "lost"})
    chain._local.conn = real
    assert chain.append_once(T, "k1", {"n": "kept"}) is not None
    assert chain.verify(T) == (True, [])


def test_concurrent_appends_keep_one_head(tmp_path):
    db = str(tmp_path / "chain.db")
    SQLiteTenantChain(db)
    errors: list[BaseException] = []

    def worker(w):
        chain = SQLiteTenantChain(db)
        try:
            for i in range(15):
                chain.append(T, {"w": w, "i": i})
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    chain = SQLiteTenantChain(db)
    entries = chain.entries(T)
    assert len(entries) == 90
    assert chain.stored_head(T) == (89, entries[-1].entry_hash)
    assert chain.verify(T) == (True, [])


def test_head_and_entries_rewritten_together_needs_an_external_anchor(tmp_path):
    # The documented limit: with write access to the whole file, an attacker
    # who truncates and also rewinds the head leaves a locally consistent
    # store. Only an anchor kept outside the database sees it.
    chain, db = _chain(tmp_path)
    anchor = chain.stored_head(T)
    _delete_newest(db)
    prev = chain.entries(T)[-1]
    _sql(db, "UPDATE tenant_chain_head SET head_sequence = ?, head_hash = ? WHERE tenant_id = ?",
         (prev.sequence_no, prev.entry_hash, T))
    assert chain.verify(T) == (True, [])
    report = chain.verify_report(T)
    assert report["ok"] and report["integrity_scope"] == INTEGRITY_SCOPE_LOCAL
    ok, problems = chain.verify(T, expected_head=anchor)
    assert not ok and any(p.startswith("head_mismatch:") for p in problems)
    anchored = chain.verify_report(T, expected_head=anchor)
    assert not anchored["ok"] and anchored["integrity_scope"] == INTEGRITY_SCOPE_ANCHORED


def test_verify_report_names_what_was_checked(tmp_path):
    chain, _ = _chain(tmp_path)
    report = chain.verify_report(T)
    assert report == {
        "ok": True,
        "problems": [],
        "integrity_scope": INTEGRITY_SCOPE_LOCAL,
        "head_origin": HEAD_ORIGIN_APPEND,
        "baseline_sequence": -1,
    }
    assert chain.verify_report(T, expected_head=chain.stored_head(T))["integrity_scope"] == \
        INTEGRITY_SCOPE_ANCHORED


# ------------------------------------------------------------- migration

_LEGACY_DDL = """
CREATE TABLE tenant_chain_entry (
    tenant_id TEXT NOT NULL, sequence_no INTEGER NOT NULL, timestamp TEXT NOT NULL,
    payload TEXT NOT NULL, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL,
    signature TEXT NOT NULL DEFAULT '', PRIMARY KEY (tenant_id, sequence_no));
CREATE TABLE tenant_chain_idempotency (
    tenant_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    PRIMARY KEY (tenant_id, idempotency_key));
"""


def _legacy_db(tmp_path, n=3):
    """A database as the pre-fix adapter left it: entries, no head table."""
    from remora.governance.tenant_chain import TenantAuditChain

    db = str(tmp_path / "legacy.db")
    ref = TenantAuditChain()
    for i in range(n):
        ref.append(T, {"n": i})
    with sqlite3.connect(db) as conn:
        conn.executescript(_LEGACY_DDL)
        import json
        for e in ref.entries(T):
            conn.execute("INSERT INTO tenant_chain_entry VALUES (?,?,?,?,?,?,?)",
                         (e.tenant_id, e.sequence_no, e.timestamp,
                          json.dumps(e.payload, sort_keys=True, separators=(",", ":")),
                          e.previous_hash, e.entry_hash, e.signature))
    return db, ref.entries(T)


def test_migration_baselines_legacy_history_as_unanchored(tmp_path):
    db, entries = _legacy_db(tmp_path)
    chain = SQLiteTenantChain(db)
    assert chain.stored_head(T) == (2, entries[-1].entry_hash)
    report = chain.verify_report(T)
    assert report["ok"]
    # Never presented as tracked from the start, let alone independently verified.
    assert report["head_origin"] == HEAD_ORIGIN_LEGACY
    assert report["baseline_sequence"] == 2
    assert report["integrity_scope"] == INTEGRITY_SCOPE_LOCAL


def test_migration_does_not_rewrite_history(tmp_path):
    db, entries = _legacy_db(tmp_path)
    SQLiteTenantChain(db)
    assert SQLiteTenantChain(db).entries(T) == entries


def test_after_migration_truncation_is_detected(tmp_path):
    db, _ = _legacy_db(tmp_path)
    chain = SQLiteTenantChain(db)
    chain.append(T, {"n": 3})
    report = chain.verify_report(T)
    assert report["ok"] and report["head_origin"] == HEAD_ORIGIN_LEGACY
    assert report["baseline_sequence"] == 2
    _delete_newest(db)
    assert not chain.verify(T)[0]


def test_truncation_before_migration_is_not_claimed_detectable(tmp_path):
    # History cut before the upgrade is baselined as found. The report says
    # the head is a legacy baseline; detecting that cut needs an anchor.
    db, entries = _legacy_db(tmp_path)
    _delete_newest(db)
    chain = SQLiteTenantChain(db)
    report = chain.verify_report(T)
    assert report["ok"] and report["head_origin"] == HEAD_ORIGIN_LEGACY
    assert not chain.verify(T, expected_head=(2, entries[-1].entry_hash))[0]


def test_migration_runs_once(tmp_path):
    db, _ = _legacy_db(tmp_path)
    SQLiteTenantChain(db)
    _sql(db, "DELETE FROM tenant_chain_head WHERE tenant_id = ?", (T,))
    # Reopening must not re-baseline a head that went missing after migration.
    chain = SQLiteTenantChain(db)
    assert chain.stored_head(T) is None
    assert "stored_head_missing" in chain.verify(T)[1]


def test_new_tenant_after_migration_is_append_tracked(tmp_path):
    db, _ = _legacy_db(tmp_path)
    chain = SQLiteTenantChain(db)
    chain.append("fresh", {"n": 0})
    assert chain.verify_report("fresh")["head_origin"] == HEAD_ORIGIN_APPEND


def test_broken_legacy_history_is_baselined_but_still_reported(tmp_path):
    db, _ = _legacy_db(tmp_path)
    _sql(db, "UPDATE tenant_chain_entry SET payload = ? WHERE tenant_id = ? AND sequence_no = 1",
         ('{"n":"edited"}', T))
    chain = SQLiteTenantChain(db)
    ok, problems = chain.verify(T)
    assert not ok and "hash_mismatch_at:1" in problems


def test_concurrent_first_open_migrates_once(tmp_path):
    db, entries = _legacy_db(tmp_path)
    errors: list[BaseException] = []

    def opener():
        try:
            SQLiteTenantChain(db)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=opener) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tenant_chain_head").fetchone()[0] == 1
    assert SQLiteTenantChain(db).stored_head(T) == (2, entries[-1].entry_hash)
