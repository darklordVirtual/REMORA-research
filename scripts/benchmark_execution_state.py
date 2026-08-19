#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Benchmark the review-state store across tenant counts (Phase 8).

Measures transaction_state load+persist cycles against a SQLite store at
1 / 100 / 1000 tenants with a configurable review volume per tenant, and
reports the size of the serialized global_state blob versus the normalized
projection row count. Output is informational for capacity planning — it is
NOT a governed claim and must not be cited in README/paper without an
archived artifact per docs/05-claim-hygiene.md.

Usage:
    python scripts/benchmark_execution_state.py [--tenants 1 100 1000]
                                                [--items 10]
"""
from __future__ import annotations

import argparse
import contextvars
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def bench(tenant_count: int, items_per_tenant: int) -> dict:
    from remora.governance.review_queue import ReviewQueue
    from remora.persistence.execution_state import transaction_state
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionAction

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "bench.db")
        engine = RemoraDecisionEngine()
        var: contextvars.ContextVar = contextvars.ContextVar("tx", default=None)

        t0 = time.perf_counter()
        for t in range(tenant_count):
            tenant = f"tenant-{t:04d}"
            queue = ReviewQueue(engine=engine)
            item_tenant: dict[str, str] = {}
            with transaction_state(
                tenant, queue=queue, item_tenant=item_tenant,
                active_tx_connection=var, dsn="", db_path=db_path,
            ) as q:
                for i in range(items_per_tenant):
                    obs = PolicyObservation(
                        question=f"bench {t}/{i}",
                        proposed_tool_name="update_work_order",
                        proposal_id=f"p-{t}-{i}",
                    )
                    q.enqueue(obs, DecisionAction.VERIFY)
                    item_tenant[f"item-{t}-{i}"] = tenant
        write_s = time.perf_counter() - t0

        # Reload cycle: one empty transaction per tenant (load + persist).
        t0 = time.perf_counter()
        for t in range(tenant_count):
            tenant = f"tenant-{t:04d}"
            queue = ReviewQueue(engine=engine)
            with transaction_state(
                tenant, queue=queue, item_tenant={},
                active_tx_connection=var, dsn="", db_path=db_path,
            ):
                pass
        reload_s = time.perf_counter() - t0

        # contextlib.closing: sqlite3's context manager commits but does NOT
        # close, and an open handle blocks TemporaryDirectory cleanup on
        # Windows.
        from contextlib import closing
        with closing(sqlite3.connect(db_path)) as conn:
            blob_bytes = conn.execute(
                "SELECT COALESCE(SUM(LENGTH(qs_json)), 0) FROM global_state"
            ).fetchone()[0]
            proj_rows = conn.execute(
                "SELECT COUNT(*) FROM review_items_projection"
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM review_items_projection WHERE status = 'pending'"
            ).fetchone()[0]

    return {
        "tenants": tenant_count,
        "items_per_tenant": items_per_tenant,
        "write_s": round(write_s, 3),
        "reload_s": round(reload_s, 3),
        "global_state_bytes": int(blob_bytes),
        "projection_rows": int(proj_rows),
        "projection_pending": int(pending),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenants", type=int, nargs="+", default=[1, 100, 1000])
    parser.add_argument("--items", type=int, default=10)
    args = parser.parse_args()

    print(f"{'tenants':>8} {'items':>6} {'write_s':>9} {'reload_s':>9} "
          f"{'blob_KiB':>9} {'proj_rows':>9}")
    for n in args.tenants:
        r = bench(n, args.items)
        print(f"{r['tenants']:>8} {r['items_per_tenant']:>6} "
              f"{r['write_s']:>9} {r['reload_s']:>9} "
              f"{r['global_state_bytes'] // 1024:>9} {r['projection_rows']:>9}")
    print("\nInformational only — not a governed claim "
          "(docs/05-claim-hygiene.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
