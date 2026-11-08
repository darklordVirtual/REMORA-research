# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signed external chain-head anchors (SDD-RMR-AACP-X R1 and R3).

A head in the same SQLite file is defeated by rewriting entries and head
together, and a JSONL log keeps no head at all. With a ChainAnchor on storage
the store's writer cannot rewrite, both are detected. These tests also pin
what the anchor does not do: it cannot protect against an attacker who can
also rewrite the anchor file, and it covers nothing before its first record.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime

import pytest

from remora.adapters.audit import AuditEntry
from remora.adapters.audit.jsonl import JSONLAudit
from remora.governance.chain_anchor import (
    ChainAnchor,
    ChainAnchorInvalid,
    anchor_from_env,
)
from remora.governance.tenant_chain import (
    INTEGRITY_SCOPE_ANCHORED,
    SQLiteTenantChain,
)

KEY = "k" * 32
T = "acme"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for v in ("REMORA_AUDIT_SIGNING_KEY", "REMORA_AUDIT_ANCHOR_PATH", "REMORA_AUDIT_ANCHOR_KEY"):
        monkeypatch.delenv(v, raising=False)


def _anchor(tmp_path, key=KEY):
    return ChainAnchor(str(tmp_path / "anchor" / "heads.jsonl"), key)


def _chain(tmp_path, n=3, anchor=None):
    db = str(tmp_path / "chain.db")
    anchor = anchor or _anchor(tmp_path)
    chain = SQLiteTenantChain(db, anchor=anchor)
    for i in range(n):
        chain.append(T, {"n": i})
    return chain, db, anchor


def _sql(db, statement, params=()):
    with sqlite3.connect(db) as conn:
        conn.execute(statement, params)


def _rewrite_tail_and_head(db, keep):
    """The R1 attack: delete entries past ``keep`` and rewind the head to match."""
    _sql(db, "DELETE FROM tenant_chain_entry WHERE tenant_id = ? AND sequence_no > ?", (T, keep))
    with sqlite3.connect(db) as conn:
        h = conn.execute("SELECT entry_hash FROM tenant_chain_entry WHERE tenant_id = ? AND "
                         "sequence_no = ?", (T, keep)).fetchone()[0]
        conn.execute("UPDATE tenant_chain_head SET head_sequence = ?, head_hash = ? "
                     "WHERE tenant_id = ?", (keep, h, T))


# ------------------------------------------------------------- SQLite chain

def test_every_commit_is_anchored(tmp_path):
    chain, _, anchor = _chain(tmp_path)
    last = chain.entries(T)[-1]
    assert anchor.latest("tenant_chain", T) == (last.sequence_no, last.entry_hash)
    report = chain.verify_report(T)
    assert report["ok"] and report["integrity_scope"] == INTEGRITY_SCOPE_ANCHORED
    assert report["anchored_sequence"] == 2 and report["anchor_lag"] == 0


def test_rewriting_entries_and_head_together_is_detected(tmp_path):
    chain, db, _ = _chain(tmp_path)
    _rewrite_tail_and_head(db, keep=0)
    ok, problems = chain.verify(T)
    assert not ok
    assert "anchor_truncated:anchored_seq=2:actual_seq=0" in problems


def test_rewritten_anchored_entry_is_detected(tmp_path):
    # Re-linking a consistent forged history keeps the local checks green;
    # the anchored hash at that position no longer matches.
    from remora.governance.tenant_chain import compute_entry_hash
    chain, db, _ = _chain(tmp_path)
    prev = "0" * 64
    for e in chain.entries(T):
        payload = {"n": f"forged-{e.sequence_no}"}
        h = compute_entry_hash(prev, payload, T, e.sequence_no, e.timestamp)
        _sql(db, "UPDATE tenant_chain_entry SET payload = ?, previous_hash = ?, entry_hash = ? "
                 "WHERE tenant_id = ? AND sequence_no = ?",
             (json.dumps(payload, sort_keys=True, separators=(",", ":")), prev, h, T, e.sequence_no))
        prev = h
    _sql(db, "UPDATE tenant_chain_head SET head_hash = ? WHERE tenant_id = ?", (prev, T))
    ok, problems = chain.verify(T)
    assert not ok and "anchor_mismatch_at:2" in problems
    # Without the anchor the forgery is locally consistent: the documented R1 limit.
    assert SQLiteTenantChain(db).verify(T) == (True, [])


def test_anchor_lagging_after_a_failed_write_is_not_a_failure(tmp_path, caplog):
    chain, _, anchor = _chain(tmp_path)

    def boom(*a, **k):
        raise OSError("anchor storage down")
    anchor.record = boom  # type: ignore[method-assign]
    chain.append(T, {"n": 3})  # committed even though the anchor write failed
    assert "chain anchor write failed" in caplog.text
    report = chain.verify_report(T)
    assert report["ok"] and report["anchored_sequence"] == 2 and report["anchor_lag"] == 1


def test_non_empty_chain_without_any_anchor_fails(tmp_path):
    db = str(tmp_path / "chain.db")
    plain = SQLiteTenantChain(db)
    plain.append(T, {"n": 0})
    anchored = SQLiteTenantChain(db, anchor=_anchor(tmp_path))
    assert "anchor_absent" in anchored.verify(T)[1]
    # The operator baselines the history as found; from then on it verifies.
    assert anchored.anchor_head(T) == (0, plain.entries(T)[0].entry_hash)
    assert anchored.verify(T) == (True, [])


def test_deleted_anchor_file_fails(tmp_path):
    chain, _, anchor = _chain(tmp_path)
    anchor.path.unlink()
    assert "anchor_absent" in chain.verify(T)[1]


def test_edited_anchor_line_is_refused(tmp_path):
    chain, _, anchor = _chain(tmp_path)
    lines = anchor.path.read_text().splitlines()
    rec = json.loads(lines[-1])
    rec["sequence_no"] = 0
    lines[-1] = json.dumps(rec)
    anchor.path.write_text("\n".join(lines) + "\n")
    ok, problems = chain.verify(T)
    assert not ok and "anchor_invalid:ChainAnchorInvalid" in problems


def test_anchor_signed_with_another_key_is_refused(tmp_path):
    chain, _, _ = _chain(tmp_path)
    other = ChainAnchor(str(tmp_path / "anchor" / "heads.jsonl"), "x" * 32)
    with pytest.raises(ChainAnchorInvalid):
        other.latest("tenant_chain", T)


def test_truncated_anchor_file_is_the_documented_limit(tmp_path):
    # Cutting the anchor file's own tail together with the chain's is what
    # append-only storage must prevent; the code cannot see it.
    chain, db, anchor = _chain(tmp_path)
    lines = anchor.path.read_text().splitlines()
    anchor.path.write_text(lines[0] + "\n")
    _rewrite_tail_and_head(db, keep=0)
    assert chain.verify(T) == (True, [])


def test_anchor_refuses_to_move_backwards(tmp_path):
    a = _anchor(tmp_path)
    a.record("c", T, 5, "a" * 64)
    with pytest.raises(ChainAnchorInvalid):
        a.record("c", T, 4, "b" * 64)
    a.record("c", T, 5, "a" * 64)  # same head again is a no-op
    assert len(a.path.read_text().splitlines()) == 1


def test_rolled_back_anchor_file_is_refused(tmp_path):
    a = _anchor(tmp_path)
    a.record("c", T, 1, "a" * 64)
    a.record("c", T, 3, "b" * 64)
    first, second = a.path.read_text().splitlines()
    a.path.write_text(second + "\n" + first + "\n")
    with pytest.raises(ChainAnchorInvalid):
        a.latest("c", T)


def test_tenants_and_chains_are_anchored_separately(tmp_path):
    anchor = _anchor(tmp_path)
    chain, db, _ = _chain(tmp_path, anchor=anchor)
    chain.append("other", {"n": 0})
    _rewrite_tail_and_head(db, keep=1)
    assert not chain.verify(T)[0]
    assert chain.verify("other") == (True, [])


def test_concurrent_appends_end_with_an_anchor_at_the_head(tmp_path):
    db = str(tmp_path / "chain.db")
    anchor = _anchor(tmp_path)
    SQLiteTenantChain(db, anchor=anchor)
    errors = []

    def worker(w):
        c = SQLiteTenantChain(db, anchor=anchor)
        try:
            for i in range(10):
                c.append(T, {"w": w, "i": i})
                assert c.verify(T)[0], c.verify(T)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    chain = SQLiteTenantChain(db, anchor=anchor)
    assert chain.verify_report(T)["anchor_lag"] == 0
    assert chain.verify(T) == (True, [])


# ------------------------------------------------------------- configuration

def test_anchor_from_env(tmp_path):
    assert anchor_from_env({}) is None
    with pytest.raises(ValueError):
        anchor_from_env({"REMORA_AUDIT_ANCHOR_PATH": str(tmp_path / "a")})
    with pytest.raises(ValueError):
        anchor_from_env({"REMORA_AUDIT_ANCHOR_PATH": str(tmp_path / "a"),
                         "REMORA_AUDIT_ANCHOR_KEY": "short"})
    a = anchor_from_env({"REMORA_AUDIT_ANCHOR_PATH": str(tmp_path / "a"),
                         "REMORA_AUDIT_ANCHOR_KEY": KEY})
    assert isinstance(a, ChainAnchor)


# ------------------------------------------------------------- JSONL (R3)

def _entry(i):
    return AuditEntry(timestamp=datetime(2026, 11, 8, 0, 0, i, tzinfo=UTC), question_hash=f"q{i}",
                      action="accept", trust_score=0.9, phase="stable", oracle_count=3,
                      verdict="ok", policy_version="v1", metadata={"n": i})


def test_jsonl_tail_truncation_is_detected_with_an_anchor(tmp_path):
    path = tmp_path / "audit.jsonl"
    anchor = _anchor(tmp_path)
    log = JSONLAudit(str(path), anchor=anchor)
    for i in range(3):
        log.append(_entry(i))
    assert JSONLAudit(str(path), anchor=anchor).verify()
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    truncated = JSONLAudit(str(path), anchor=anchor)
    assert not truncated.verify()
    assert truncated.anchor_problems() == ["anchor_truncated:anchored_seq=2:actual_seq=1"]
    # Without the anchor: the documented local-only limit.
    assert JSONLAudit(str(path), anchor=None).verify()


def test_jsonl_anchor_from_env_and_per_log_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("REMORA_AUDIT_ANCHOR_PATH", str(tmp_path / "heads.jsonl"))
    monkeypatch.setenv("REMORA_AUDIT_ANCHOR_KEY", KEY)
    a, b = JSONLAudit(str(tmp_path / "a.jsonl")), JSONLAudit(str(tmp_path / "b.jsonl"))
    a.append(_entry(0))
    a.append(_entry(1))
    b.append(_entry(0))
    assert JSONLAudit(str(tmp_path / "a.jsonl")).verify()
    assert JSONLAudit(str(tmp_path / "b.jsonl")).verify()


def test_jsonl_existing_log_without_anchor_fails_until_baselined(tmp_path):
    path = tmp_path / "audit.jsonl"
    plain = JSONLAudit(str(path), anchor=None)
    plain.append(_entry(0))
    anchor = _anchor(tmp_path)
    log = JSONLAudit(str(path), anchor=anchor)
    assert log.anchor_problems() == ["anchor_absent"]
    head = log.head()
    anchor.record(f"jsonl:{path.resolve()}", "-", *head)
    assert JSONLAudit(str(path), anchor=anchor).verify()


# ------------------------------------------------------------- API

@pytest.mark.parametrize("anchored", [True, False])
def test_audit_verify_reports_the_integrity_scope(tmp_path, monkeypatch, anchored):
    from fastapi.testclient import TestClient

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from remora.governance.tenant_chain import INTEGRITY_SCOPE_LOCAL

    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "api.db"))
    if anchored:
        monkeypatch.setenv("REMORA_AUDIT_ANCHOR_PATH", str(tmp_path / "api-heads.jsonl"))
        monkeypatch.setenv("REMORA_AUDIT_ANCHOR_KEY", KEY)
    chain = exec_mod._build_chain()
    assert isinstance(chain, SQLiteTenantChain)
    assert (chain._anchor is not None) is anchored
    monkeypatch.setattr(exec_mod, "_CHAIN", chain)
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    chain.append("acme", {"n": 0})
    body = TestClient(api_mod.app).get("/v1/execution/audit/verify").json()
    assert body["valid"] is True
    assert body["integrity_scope"] == (INTEGRITY_SCOPE_ANCHORED if anchored
                                       else INTEGRITY_SCOPE_LOCAL)


def test_build_chain_refuses_an_anchor_path_without_a_key(tmp_path, monkeypatch):
    import servers.execution_api as exec_mod
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("REMORA_AUDIT_ANCHOR_PATH", str(tmp_path / "heads.jsonl"))
    with pytest.raises(ValueError):
        exec_mod._build_chain()
