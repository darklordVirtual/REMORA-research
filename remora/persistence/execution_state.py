# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review-state transaction adapter (issue #241, extraction slice 2).

Moved from servers/execution_api.py with the module globals turned into
explicit parameters — the transaction semantics (all-or-nothing across the
database row AND the in-memory mirrors, ambient connection for the outbox via
a contextvar) are byte-for-byte the behavior the fault-injection suite pins.

No HTTP knowledge: the API layer passes its queue, its item→tenant mirror,
its contextvar and the durability configuration.
"""
from __future__ import annotations

import copy
import dataclasses
import json
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from typing import Any

from remora.governance.review_queue import Approval, ItemStatus, PendingReview
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction


def to_dict(obj):
    # Recurse into containers: dataclasses.asdict() leaves datetimes and
    # Enums untouched inside NESTED dataclasses (e.g. PendingReview.approval),
    # and the previous version never descended into plain dicts — approvals
    # were unserializable, which went unnoticed exactly because they were
    # never persisted (external review 2026-07-27, finding 2).
    if dataclasses.is_dataclass(obj):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    return obj


def from_dict(d, cls):
    if hasattr(cls, "__dataclass_fields__"):
        kwargs = {}
        for k, v in d.items():
            field_type = cls.__dataclass_fields__[k].type
            if 'datetime' in str(field_type) and isinstance(v, str):
                kwargs[k] = datetime.fromisoformat(v)
            elif 'ItemStatus' in str(field_type):
                kwargs[k] = ItemStatus(v)
            elif 'DecisionAction' in str(field_type):
                kwargs[k] = DecisionAction(v)
            elif 'Observation' in str(field_type) and isinstance(v, dict):
                kwargs[k] = PolicyObservation(**v)
            elif 'Approval' in str(field_type) and isinstance(v, dict):
                v['expires_at'] = datetime.fromisoformat(v['expires_at'])
                v['issued_at'] = datetime.fromisoformat(v['issued_at'])
                v['approved_action'] = DecisionAction(v['approved_action'])
                kwargs[k] = Approval(**v)
            else:
                kwargs[k] = v
        return cls(**kwargs)
    return d


@contextmanager
def transaction_state(
    tenant: str,
    *,
    queue: Any,
    item_tenant: dict[str, str],
    active_tx_connection: Any,
    dsn: str,
    db_path: str,
):
    """One all-or-nothing review-state transaction for *tenant*.

    Postgres (``dsn``) and SQLite (``db_path``) branches load the persisted
    queue state, expose the open connection through ``active_tx_connection``
    (so the outbox row joins the SAME transaction), and on exception roll back
    both the database and the in-memory mirrors. The in-process branch keeps
    the identical all-or-nothing promise via deep-copied snapshots.
    """
    q = queue

    if dsn:
        import psycopg  # type: ignore
        with psycopg.connect(dsn) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS global_state (tenant_id TEXT PRIMARY KEY, qs_json TEXT, it_json TEXT)")
            with conn.transaction():
                row = conn.execute("SELECT qs_json, it_json FROM global_state WHERE tenant_id = %s FOR UPDATE", (tenant,)).fetchone()
                if row and row[0]:
                    q._items = {k: from_dict(v, PendingReview) for k, v in json.loads(row[0]).items()}
                if row and row[1]:

                    item_tenant.update(json.loads(row[1]))
                # Snapshot the in-memory mirrors: the DB transaction rolls
                # back on exception, but q._items / item_tenant would keep
                # aborted mutations and leak them into the NEXT successful
                # commit (self-review 2026-07-28).
                items_snapshot = dict(q._items)
                tenant_snapshot = dict(item_tenant)
                _tx_token = active_tx_connection.set(conn)
                try:
                    yield q
                except BaseException:
                    q._items = items_snapshot
                    item_tenant.clear()
                    item_tenant.update(tenant_snapshot)
                    raise
                else:
                    conn.execute(
                        "INSERT INTO global_state (tenant_id, qs_json, it_json) VALUES (%s, %s, %s) "
                        "ON CONFLICT (tenant_id) DO UPDATE SET qs_json = EXCLUDED.qs_json, it_json = EXCLUDED.it_json",
                        (tenant, json.dumps({k: to_dict(v) for k, v in q._items.items()}), json.dumps(item_tenant))
                    )
                finally:
                    active_tx_connection.reset(_tx_token)
    elif db_path:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS global_state (tenant_id TEXT PRIMARY KEY, qs_json TEXT, it_json TEXT)")
            conn.commit()
            conn.execute("BEGIN EXCLUSIVE TRANSACTION")
            row = conn.execute("SELECT qs_json, it_json FROM global_state WHERE tenant_id = ?", (tenant,)).fetchone()
            if row and row[0]:
                q._items = {k: from_dict(v, PendingReview) for k, v in json.loads(row[0]).items()}
            if row and row[1]:

                item_tenant.update(json.loads(row[1]))
            # Snapshot in-memory mirrors (see Postgres branch comment).
            items_snapshot = dict(q._items)
            tenant_snapshot = dict(item_tenant)
            _tx_token = active_tx_connection.set(conn)
            try:
                yield q
            except BaseException:
                # An exception inside the handler must roll the WHOLE
                # transaction back — the DB via rollback(), and the
                # in-memory mirrors via snapshot restore — never persist
                # partially mutated queue state (external review
                # 2026-07-28, N1 + self-review follow-up).
                conn.rollback()
                q._items = items_snapshot
                item_tenant.clear()
                item_tenant.update(tenant_snapshot)
                raise
            else:
                conn.execute(
                    "INSERT INTO global_state (tenant_id, qs_json, it_json) VALUES (?, ?, ?) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET qs_json = excluded.qs_json, it_json = excluded.it_json",
                    (tenant, json.dumps({k: to_dict(v) for k, v in q._items.items()}), json.dumps(item_tenant))
                )
                conn.commit()
            finally:
                active_tx_connection.reset(_tx_token)
    else:
        # In-process branch: no database to roll back, but the SAME
        # all-or-nothing promise must hold or crash-matrix row 1 is false
        # here — a failed authorization would leave the item AUTHORIZED and
        # not re-executable (found by the fault-injection suite, 2026-08-05).
        with q._lock:
            # DEEP copy: q.execute() mutates the PendingReview in place, so a
            # shallow dict copy restores the mapping while leaving the item
            # itself mutated. The durable branches survive this because their
            # next transaction reloads every item from the store; in-process
            # has no such reload, so the snapshot must own its objects.
            items_snapshot = copy.deepcopy(q._items)
            tenant_snapshot = dict(item_tenant)
            try:
                yield q
            except BaseException:
                q._items = items_snapshot
                item_tenant.clear()
                item_tenant.update(tenant_snapshot)
                raise
