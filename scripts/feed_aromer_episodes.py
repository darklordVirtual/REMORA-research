#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Feed 125 diverse labeled episodes to the live AROMER Worker.

Covers all key decision types across 10+ domains so the world model
can build medium+ confidence in frequently-seen contexts.

Usage:
    python scripts/feed_aromer_episodes.py [--dry-run] [--worker-url URL] [--delay 0.15]

Episode types generated:
  - correct_block           (ESCALATE + harmful)  — clear harm blocked
  - correct_accept          (ACCEPT + benign)      — clear safe action
  - correct_intercept_verify (VERIFY + harmful)   — gray-zone harmful caught
  - benign_review           (VERIFY + benign)      — safe action reviewed (friction)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

WORKER_URL = "https://aromer.razorsharp.workers.dev"
random.seed(42)

# fmt: off
# (domain, risk_tier, action_type, phase, trust, H, D, verdict, ground_truth, confidence, severity, count)
TEMPLATES: list[tuple] = [
    # ── Clear harmful blocks: ESCALATE + harmful → correct_block ──────────────
    ("database",       "critical", "destructive_write",  "ordered",    0.15, 0.18, 0.08, "ESCALATE", "harmful", 0.94, -0.90,  8),
    ("agentic",        "critical", "execution",          "ordered",    0.20, 0.22, 0.10, "ESCALATE", "harmful", 0.92, -0.85,  8),
    ("shell",          "critical", "execution",          "disordered", 0.12, 0.95, 0.72, "ESCALATE", "harmful", 0.88, -0.92,  6),
    ("financial",      "critical", "execute_transfer",   "ordered",    0.18, 0.20, 0.12, "ESCALATE", "harmful", 0.91, -0.88,  6),
    ("infrastructure", "high",     "deployment",         "ordered",    0.25, 0.30, 0.15, "ESCALATE", "harmful", 0.85, -0.75,  5),
    ("git",            "high",     "force_push",         "ordered",    0.22, 0.25, 0.12, "ESCALATE", "harmful", 0.87, -0.78,  4),
    ("network",        "high",     "write",              "ordered",    0.28, 0.32, 0.18, "ESCALATE", "harmful", 0.83, -0.72,  4),
    ("medical",        "critical", "write",              "ordered",    0.10, 0.15, 0.08, "ESCALATE", "harmful", 0.95, -0.95,  3),
    ("communication",  "high",     "write",              "critical",   0.20, 0.85, 0.62, "ESCALATE", "harmful", 0.82, -0.70,  2),

    # ── Clear safe accepts: ACCEPT + benign → correct_accept ──────────────────
    ("information",    "low",      "read",               "ordered",    0.88, 0.10, 0.05, "ACCEPT",   "benign",  0.95,  0.00, 12),
    ("database",       "low",      "read",               "ordered",    0.85, 0.12, 0.06, "ACCEPT",   "benign",  0.93,  0.00,  8),
    ("git",            "low",      "read",               "ordered",    0.90, 0.08, 0.04, "ACCEPT",   "benign",  0.96,  0.00,  6),
    ("communication",  "low",      "write",              "ordered",    0.82, 0.15, 0.08, "ACCEPT",   "benign",  0.90,  0.00,  5),
    ("medical",        "low",      "read",               "ordered",    0.87, 0.11, 0.06, "ACCEPT",   "benign",  0.92,  0.00,  5),
    ("network",        "low",      "read",               "ordered",    0.84, 0.13, 0.07, "ACCEPT",   "benign",  0.91,  0.00,  5),
    ("infrastructure", "low",      "read",               "ordered",    0.89, 0.09, 0.05, "ACCEPT",   "benign",  0.94,  0.00,  5),
    ("agentic",        "low",      "read",               "ordered",    0.86, 0.11, 0.06, "ACCEPT",   "benign",  0.93,  0.00,  3),
    ("financial",      "low",      "read",               "ordered",    0.83, 0.13, 0.07, "ACCEPT",   "benign",  0.92,  0.00,  3),

    # ── Gray-zone harmful caught: VERIFY + harmful → correct_intercept_verify ─
    ("agentic",        "medium",   "write",              "critical",   0.45, 0.82, 0.55, "VERIFY",   "harmful", 0.65, -0.55,  5),
    ("database",       "medium",   "write",              "critical",   0.42, 0.78, 0.52, "VERIFY",   "harmful", 0.62, -0.50,  4),
    ("financial",      "medium",   "read",               "critical",   0.48, 0.75, 0.48, "VERIFY",   "harmful", 0.60, -0.45,  4),
    ("infrastructure", "medium",   "write",              "critical",   0.44, 0.80, 0.54, "VERIFY",   "harmful", 0.63, -0.52,  3),
    ("shell",          "high",     "read",               "disordered", 0.38, 1.10, 0.75, "VERIFY",   "harmful", 0.55, -0.60,  4),

    # ── Benign review friction: VERIFY + benign → benign_review ───────────────
    ("agentic",        "medium",   "write",              "critical",   0.60, 0.70, 0.45, "VERIFY",   "benign",  0.55,  0.00,  3),
    ("infrastructure", "high",     "read",               "critical",   0.65, 0.65, 0.42, "VERIFY",   "benign",  0.58,  0.00,  2),
    ("financial",      "high",     "read",               "critical",   0.62, 0.68, 0.44, "VERIFY",   "benign",  0.56,  0.00,  2),
    ("database",       "high",     "read",               "critical",   0.58, 0.72, 0.46, "VERIFY",   "benign",  0.54,  0.00,  2),
    ("git",            "medium",   "write",              "critical",   0.63, 0.66, 0.43, "VERIFY",   "benign",  0.57,  0.00,  2),
    ("network",        "medium",   "write",              "critical",   0.61, 0.69, 0.44, "VERIFY",   "benign",  0.55,  0.00,  1),
]
# fmt: on


def jitter(v: float, scale: float = 0.10) -> float:
    """Gaussian noise ±scale·v, clamped to [0.01, 0.99]."""
    return round(max(0.01, min(0.99, v + random.gauss(0, scale * abs(v) + 0.01))), 3)


def build_episodes() -> list[dict]:
    episodes: list[dict] = []
    for (domain, risk_tier, action_type, phase, trust, H, D,
         verdict, ground_truth, confidence, severity, count) in TEMPLATES:
        for _ in range(count):
            episodes.append({
                "domain":           domain,
                "risk_tier":        risk_tier,
                "action_type":      action_type,
                "phase":            phase,
                "trust_score":      jitter(trust, 0.08),
                "entropy_h":        jitter(H, 0.12),
                "dissensus_d":      jitter(D, 0.12),
                "verdict":          verdict,
                "ground_truth":     ground_truth,
                "confidence":       jitter(confidence, 0.05),
                "outcome_severity": round(severity + random.gauss(0, 0.04), 3) if severity != 0 else 0.0,
                "rules_triggered":  [],
            })
    return episodes


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "AROMER-feed/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "body": e.read().decode(errors="replace")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Feed labeled episodes to AROMER Worker")
    parser.add_argument("--dry-run",    action="store_true", help="Print summary without POSTing")
    parser.add_argument("--worker-url", default=WORKER_URL)
    parser.add_argument("--delay",      type=float, default=0.15, help="Seconds between POSTs")
    args = parser.parse_args()

    episodes = build_episodes()
    total = len(episodes)
    print(f"Generated {total} episodes from {len(TEMPLATES)} templates")

    # Distribution summary
    dist = Counter(
        f"{e['domain']}/{e['action_type']} ({e['verdict']}+{e['ground_truth']})"
        for e in episodes
    )
    if args.dry_run:
        print("\nDistribution:")
        for label, n in sorted(dist.items(), key=lambda x: -x[1]):
            print(f"  {n:3d}x  {label}")
        # Decision quality summary
        quality_map = {
            ("ESCALATE", "harmful"): "correct_block",
            ("ACCEPT",   "benign"):  "correct_accept",
            ("VERIFY",   "harmful"): "correct_intercept_verify",
            ("VERIFY",   "benign"):  "benign_review",
            ("ACCEPT",   "harmful"): "false_accept",
            ("ESCALATE", "benign"):  "false_block",
        }
        quality_dist = Counter(
            quality_map.get((e["verdict"], e["ground_truth"]), "unknown")
            for e in episodes
        )
        print("\nDecision quality breakdown:")
        for q, n in sorted(quality_dist.items(), key=lambda x: -x[1]):
            print(f"  {n:3d}x  {q}")
        return

    ep_url = f"{args.worker_url}/episode"
    ok = fail = 0
    for i, ep in enumerate(episodes, 1):
        result = post_json(ep_url, ep)
        if result.get("ok"):
            ok += 1
        else:
            fail += 1
            print(f"  [{i}] FAIL: {result}", file=sys.stderr)
        if (i % 25 == 0 or i == total) and ok + fail > 0:
            print(f"  [{i}/{total}] {ok} OK  {fail} failed")
        if args.delay > 0 and i < total:
            time.sleep(args.delay)

    print(f"\nDone: {ok} OK  {fail} failed")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
