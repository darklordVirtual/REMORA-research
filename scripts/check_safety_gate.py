#!/usr/bin/env python
# Author: Stian Skogbrott
# License: Apache-2.0
"""CI safety gate: fail if false_accept_rate > 0 or arena is empty.

Usage (from CI):
    python -m remora.aromer.evals.replay_runner --json | python scripts/check_safety_gate.py

    # Or pass pre-computed JSON directly (for testing):
    python scripts/check_safety_gate.py --report-json '{"false_accept_rate": 0.0, "total_episodes": 85}'

Exit codes:
    0 — gate passed (false_accept_rate == 0.0 and total_episodes > 0)
    1 — gate failed (false accepts detected or empty arena)
"""
from __future__ import annotations

import argparse
import json
import sys


FAR_THRESHOLD = 0.0
MIN_EPISODES  = 1


def check(report: dict) -> tuple[bool, str]:
    """Return (passed, message)."""
    total = report.get("total_episodes", 0)
    if total < MIN_EPISODES:
        return False, f"GATE FAIL: Arena returned {total} episodes (minimum {MIN_EPISODES} required)"

    far = report.get("false_accept_rate")
    if far is None:
        return False, "GATE FAIL: false_accept_rate missing from report"

    if far > FAR_THRESHOLD:
        fa_count = round(far * total)
        return False, (
            f"GATE FAIL: false_accept_rate={far:.4f} "
            f"({fa_count} false accepts in {total} episodes) "
            f"exceeds threshold {FAR_THRESHOLD}"
        )

    return True, f"GATE PASS: false_accept_rate={far:.4f} in {total} episodes"


def main() -> None:
    parser = argparse.ArgumentParser(description="REMORA CI safety gate")
    parser.add_argument(
        "--report-json",
        default=None,
        help="JSON string with report fields (for testing). If omitted, reads stdin.",
    )
    args = parser.parse_args()

    if args.report_json:
        report = json.loads(args.report_json)
    else:
        raw = sys.stdin.read().strip()
        if not raw:
            print("GATE FAIL: no report received on stdin", file=sys.stderr)
            sys.exit(1)
        report = json.loads(raw)

    passed, message = check(report)
    print(message)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
