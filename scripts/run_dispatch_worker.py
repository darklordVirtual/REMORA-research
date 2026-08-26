#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Standalone dispatch worker (issue #82): the process/liveness boundary.

With ``REMORA_ASYNC_DISPATCH=1`` the API answers 202 after durable
authorization — the queue's EXECUTE outcome and the dispatch-intent row
commit in one transaction — and this process performs the dispatch half:
claim (exclusive) → grant minted and PEP-consumed at the moment of
honouring → ``execution_authorized`` chain entry → governed dispatch under
a lease → settle with what actually happened → ``execution_result`` entry.
The record shapes are identical to the synchronous path.

What it deliberately does NOT do:

* touch rows without a persisted call payload (pre-#82 rows and
  synchronous-path rows) — it cannot reconstruct the call, and the
  reconciler owns their fate;
* retry anything: a settled row is terminal, and an UNKNOWN outcome is
  never replayed — proving the effect is the effect-verification path's
  job, not this loop's.

Usage:
    python scripts/run_dispatch_worker.py --once
    python scripts/run_dispatch_worker.py --interval 5

Durability config comes from the same environment as the API
(REMORA_PG_DSN / REMORA_CHAIN_DB). Running against an in-process outbox is
refused: a separate process cannot see the API's memory.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sweep_once(worker_id: str) -> int:
    from servers import execution_api as exec_mod

    outbox = exec_mod._outbox()
    if type(outbox) is exec_mod.ExecutionOutbox:
        print(
            "[FAIL] in-process outbox: a separate dispatch worker cannot "
            "see the API's memory. Set REMORA_PG_DSN or REMORA_CHAIN_DB."
        )
        raise SystemExit(2)

    dispatched_total = 0
    for tenant in outbox.tenants():
        for result in exec_mod.dispatch_pending_intents(
            tenant, worker_id=worker_id
        ):
            te = result.get("tool_execution", {})
            print(f"[DISPATCHED] tenant={tenant} "
                  f"proposal={result.get('proposal_id')} "
                  f"executed={te.get('executed')} "
                  f"refusal={te.get('refusal_reason')}")
            dispatched_total += 1
    print(f"[OK]   sweep complete: {dispatched_total} intent(s) dispatched "
          f"across {len(outbox.tenants())} tenant(s)")
    return dispatched_total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true",
                       help="one sweep, then exit")
    group.add_argument("--interval", type=float, metavar="SECONDS",
                       help="sweep repeatedly at this interval")
    args = parser.parse_args()

    worker_id = f"dispatch-worker:{os.getpid()}"
    if args.once:
        sweep_once(worker_id)
        return 0
    while True:
        sweep_once(worker_id)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
