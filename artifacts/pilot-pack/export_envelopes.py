#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pilot-pack export recipe: protocol metrics over the envelope stream.

Reads DecisionEnvelopes — either a JSONL file (one envelope per line, e.g.
exported from the control-plane store) or fetched live via
``GET /v1/envelope/{request_id}`` for the ids in a supplied event file —
and prints the pilot protocol's selectivity and technical metrics WITH
DENOMINATORS, plus a missing-audit count. This is the minimal dashboard:
one table per run, suitable for the evaluation worksheet.

Usage:
    python export_envelopes.py envelopes.jsonl
    python export_envelopes.py --api http://localhost:8000 --token T events.jsonl

No metric here decides anything. Thresholds live in the worksheet, frozen
before the first scored event.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]


def load_envelopes(args: argparse.Namespace) -> tuple[list[dict], int]:
    """(envelopes, missing_count)."""
    lines = [json.loads(ln) for ln
             in open(args.path, encoding="utf-8") if ln.strip()]
    if not args.api:
        return lines, 0
    envelopes, missing = [], 0
    for event in lines:
        rid = event.get("event_id") or event.get("request_id")
        req = urllib.request.Request(
            f"{args.api.rstrip('/')}/v1/envelope/{rid}",
            headers={"Authorization": f"Bearer {args.token}"} if args.token else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                envelopes.append(json.load(resp))
        except Exception:
            missing += 1  # counted, never silently dropped
    return envelopes, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="envelopes.jsonl, or events.jsonl with --api")
    parser.add_argument("--api", default="", help="fetch envelopes live from this base URL")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    envelopes, missing = load_envelopes(args)
    total = len(envelopes) + missing
    if total == 0:
        print("no events", file=sys.stderr)
        return 1

    actions: Counter[str] = Counter()
    latencies: list[float] = []
    unsigned = 0
    for env in envelopes:
        decision = env.get("decision") or {}
        actions[str(decision.get("action", "unknown")).lower()] += 1
        lat = (env.get("meta") or {}).get("latency_ms") or decision.get("latency_ms")
        if isinstance(lat, (int, float)):
            latencies.append(float(lat))
        if not env.get("signature"):
            unsigned += 1

    print(f"events total:            {total}")
    print(f"envelopes retrieved:     {len(envelopes)}")
    print(f"missing audit data:      {missing} ({missing / total:.2%})  "
          f"<- worksheet criterion 'Missing audit data'")
    print(f"unsigned envelopes:      {unsigned}")
    print("decision mix (selectivity, denominators included):")
    for action, n in actions.most_common():
        print(f"  {action:<10} {n:>6}  ({n / len(envelopes):.2%} of retrieved)")
    for p in (50, 95, 99):
        v = _percentile(latencies, p)
        print(f"p{p} latency ms:          "
              f"{v if v is not None else 'n/a (no latency field in stream)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
