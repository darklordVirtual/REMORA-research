#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Standalone outbox reconciler (Phase 4): wall-clock, traffic-independent.

The lazy sweep in servers/execution_api.py runs on request traffic, so an
IDLE tenant's stuck DISPATCHING rows would wait for the tenant's next call.
This entry point reconciles on a schedule instead: every tenant with
recorded intents is swept, stale claimed rows settle as UNKNOWN (never
retried), unclaimed rows as FAILED (provably never dispatched), and every
settlement is appended to the tenant audit chain — the same semantics as the
in-request sweep, exercised by the fault-injection suite.

Usage:
    python scripts/run_outbox_reconciler.py --once
    python scripts/run_outbox_reconciler.py --interval 300

Durability config comes from the same environment as the API
(REMORA_PG_DSN / REMORA_CHAIN_DB, REMORA_OUTBOX_STALE_SECONDS). Running it
against an in-process outbox is refused: a separate process cannot see the
API's memory, and sweeping an empty store would report health it cannot
know.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sweep_once() -> int:
    from servers import execution_api as exec_mod

    outbox = exec_mod._outbox()
    if type(outbox) is exec_mod.ExecutionOutbox:
        print(
            "[FAIL] in-process outbox: a separate reconciler process cannot "
            "see the API's memory. Set REMORA_PG_DSN or REMORA_CHAIN_DB."
        )
        raise SystemExit(2)

    settled_total = 0
    for tenant in outbox.tenants():
        # reconcile_stale_dispatches also runs the idempotent terminal
        # projector (issue #416), so a wall-clock sweep finishes any
        # projection a crashed process left behind.
        settled = exec_mod.reconcile_stale_dispatches(tenant)
        for row in settled:
            print(f"[SETTLED] tenant={tenant} proposal={row.proposal_id} "
                  f"outbox={row.outbox_id} state={row.state.value} "
                  f"detail={row.detail}")
        settled_total += len(settled)
    print(f"[OK]   sweep complete: {settled_total} row(s) settled "
          f"across {len(outbox.tenants())} tenant(s)")
    return settled_total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="single sweep, then exit")
    group.add_argument("--interval", type=int, metavar="SECONDS",
                       help="sweep repeatedly at this interval")
    args = parser.parse_args()

    if args.once:
        sweep_once()
        return 0

    interval = max(30, int(args.interval))
    stale = os.environ.get("REMORA_OUTBOX_STALE_SECONDS", "900")
    print(f"[OK]   reconciler loop: every {interval}s "
          f"(staleness threshold {stale}s). Ctrl+C to stop.")
    while True:
        try:
            sweep_once()
        except SystemExit:
            raise
        except Exception as exc:  # one failed sweep must not kill the loop
            print(f"[WARN] sweep failed: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
