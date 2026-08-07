# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Lock and evaluate the disjoint BFCL v4 holdout exactly once."""
from __future__ import annotations

import argparse
from pathlib import Path

import scripts.run_bfcl_holdout as shared

ROOT = Path(__file__).resolve().parent.parent
shared.HOLDOUT = ROOT / "data" / "routing_bench_bfcl_v4"
shared.OUT = ROOT / "results" / "routing_bench_bfcl_v4_results.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", metavar="SNAPSHOT")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.lock:
        raise SystemExit(shared.lock(args.lock))
    if args.run:
        raise SystemExit(shared.run())
    parser.error("pass --lock <snapshot> or --run")


if __name__ == "__main__":
    main()
