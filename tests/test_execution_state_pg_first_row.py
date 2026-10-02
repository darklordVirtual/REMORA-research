# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Postgres branch of transaction_state must create the tenant row before locking.

``SELECT ... FOR UPDATE`` locks nothing when the row does not exist, so two
concurrent first transactions for a new tenant would both read an empty queue
and last-writer-win. The fix inserts an empty row (ON CONFLICT DO NOTHING)
first, so the FOR UPDATE always has a row to lock.

No Postgres is available in CI for this test: a recording fake ``psycopg``
pins the statement ORDER only. Lock behaviour itself is not exercised.
"""
from __future__ import annotations

import contextlib
import contextvars
import sys
import types

from remora.governance.review_queue import ReviewQueue
from remora.persistence.execution_state import transaction_state


class _Cursor:
    def fetchone(self):
        return None


class _Conn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @contextlib.contextmanager
    def transaction(self):
        self.log.append("BEGIN")
        yield
        self.log.append("COMMIT")

    def execute(self, sql, params=None):
        self.log.append(" ".join(sql.split()))
        return _Cursor()


def test_pg_first_transaction_inserts_row_before_for_update(monkeypatch):
    log: list[str] = []
    fake = types.SimpleNamespace(connect=lambda dsn: _Conn(log))
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    with transaction_state(
        "new-tenant",
        queue=ReviewQueue(),
        item_tenant={},
        active_tx_connection=contextvars.ContextVar("c", default=None),
        dsn="postgresql://fake",
        db_path="",
    ):
        pass
    begin = log.index("BEGIN")
    insert = next(
        i for i, s in enumerate(log)
        if s.startswith("INSERT INTO global_state") and "DO NOTHING" in s
    )
    select = next(i for i, s in enumerate(log) if "FOR UPDATE" in s)
    assert begin < insert < select
