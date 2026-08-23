# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The D1-backed connection used when the container has no writable disk.

The property under test is all-or-nothing for the write set: an exception
before commit must leave the store untouched. D1 over HTTP has no server-side
rollback, so that is achieved by never sending the writes rather than by
undoing them, and these pin that it actually behaves that way.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.persistence import d1_connection as d1  # noqa: E402


@pytest.fixture()
def sent(monkeypatch):
    """Record every batch that reaches the wire."""
    batches: list[list[dict]] = []

    def fake_post(statements):
        batches.append([dict(s) for s in statements])
        return [[] for _ in statements]

    monkeypatch.setenv(d1.ENDPOINT_ENV, "http://state.internal/query")
    monkeypatch.setattr(d1, "_post", fake_post)
    return batches


def test_writes_do_not_reach_the_store_before_commit(sent):
    conn = d1.connect()
    conn.execute("INSERT INTO t (a) VALUES (?)", ("x",))
    conn.execute("UPDATE t SET a = ?", ("y",))
    assert sent == [], "writes must not be sent before commit"
    conn.commit()
    assert len(sent) == 1, "commit sends exactly one batch"
    assert len(sent[0]) == 2, "both writes in the same batch"


def test_rollback_never_sends_anything(sent):
    conn = d1.connect()
    conn.execute("INSERT INTO t (a) VALUES (?)", ("x",))
    conn.rollback()
    conn.commit()
    assert sent == [], "a rolled-back transaction must reach the store not at all"


def test_an_exception_in_the_block_discards_the_writes(sent):
    # Written with an explicit try/except rather than pytest.raises around a
    # with-block: static analysis does not model pytest.raises as catching, so
    # it reads the assertion after it as unreachable and reports it.
    raised = False
    try:
        with d1.connect() as conn:
            conn.execute("INSERT INTO t (a) VALUES (?)", ("x",))
            raise ValueError("handler failed")
    except ValueError:
        raised = True

    assert raised, "the exception must propagate out of the block"
    assert sent == [], "the write set must not survive the exception"


def test_a_clean_block_commits(sent):
    with d1.connect() as conn:
        conn.execute("INSERT INTO t (a) VALUES (?)", ("x",))
    assert len(sent) == 1


def test_a_read_sees_this_transaction_s_own_writes(sent):
    """Anything pending is flushed first, in order, before the read runs."""
    conn = d1.connect()
    conn.execute("INSERT INTO t (a) VALUES (?)", ("x",))
    conn.execute("SELECT a FROM t")
    assert len(sent) == 2, "the pending write is flushed, then the read runs"
    assert sent[0][0]["sql"].startswith("INSERT")
    assert sent[1][0]["sql"].startswith("SELECT")


@pytest.mark.parametrize("sql,is_write", [
    ("SELECT 1", False),
    ("  select a from t", False),
    ("PRAGMA table_info(t)", False),
    ("WITH x AS (SELECT 1) SELECT * FROM x", False),
    ("INSERT INTO t VALUES (1)", True),
    ("update t set a = 1", True),
    ("DELETE FROM t", True),
    ("CREATE TABLE t (a)", True),
])
def test_reads_and_writes_are_told_apart(sql, is_write):
    assert d1._is_write(sql) is is_write


def test_rows_are_returned_positionally_like_sqlite3(monkeypatch):
    """Callers index the tuple, as they do with the sqlite3 branch."""
    monkeypatch.setenv(d1.ENDPOINT_ENV, "http://state.internal/query")
    monkeypatch.setattr(d1, "_post",
                        lambda s: [[{"qs_json": "{}", "it_json": "{}"}]])
    row = d1.connect().execute("SELECT qs_json, it_json FROM global_state").fetchone()
    assert row == ("{}", "{}")


def test_no_endpoint_is_a_clear_refusal(monkeypatch):
    monkeypatch.delenv(d1.ENDPOINT_ENV, raising=False)
    with pytest.raises(d1.D1Unavailable) as exc:
        d1.connect().execute("SELECT 1")
    assert d1.ENDPOINT_ENV in str(exc.value)


def test_the_endpoint_is_not_a_public_host(monkeypatch):
    """It is intercepted by the Worker; nothing resolves it on the internet."""
    monkeypatch.setenv(d1.ENDPOINT_ENV, "http://state.internal/query")
    assert "api.cloudflare.com" not in d1.endpoint()


def test_no_credential_is_read_by_this_module():
    source = Path(d1.__file__).read_text(encoding="utf-8")
    for leaked in ("API_TOKEN", "Authorization", "Bearer"):
        assert leaked not in source, f"{leaked} is referenced by the adapter"
