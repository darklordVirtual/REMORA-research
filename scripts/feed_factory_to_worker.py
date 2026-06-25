#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Feed Episode Factory cases to the live AROMER Worker.

Each factory episode has a fixed expected_truth (benign/harmful) and
expected_verdict (accept/escalate/verify).  We post them as labeled
episodes — this gives AROMER clean, curated training signal.

Usage
-----
  python scripts/feed_factory_to_worker.py
  python scripts/feed_factory_to_worker.py --dry-run
  python scripts/feed_factory_to_worker.py --repeat 3   # feed 3x for weight
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.aromer.evals.episode_factory import build_episodes, ArenaEpisode

WORKER_URL = "https://aromer.razorsharp.workers.dev"
_SSL = ssl.create_default_context()

_VERDICT_MAP = {
    "accept":   {"verdict": "ACCEPT",   "trust": 0.85, "H": 0.20, "D": 0.08},
    "verify":   {"verdict": "VERIFY",   "trust": 0.50, "H": 0.72, "D": 0.55},
    "escalate": {"verdict": "ESCALATE", "trust": 0.18, "H": 0.88, "D": 0.71},
    "abstain":  {"verdict": "ABSTAIN",  "trust": 0.45, "H": 0.90, "D": 0.60},
}

_QUALITY_SEVERITY = {
    "correct_block":            +0.80,
    "correct_accept":           +0.70,
    "correct_intercept_verify": +0.60,
    "benign_review":            -0.15,
    "false_accept":             -0.90,
    "false_block":              -0.80,
}


def _post(path: str, body: dict) -> dict:
    req = __import__("urllib.request", fromlist=["Request", "urlopen"])
    r = req.Request(WORKER_URL + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "AROMER-factory/1.0"},
        method="POST")
    with req.urlopen(r, timeout=10, context=_SSL) as resp:
        return json.loads(resp.read().decode("utf-8"))


def feed_episode(ep: ArenaEpisode, dry_run: bool = False) -> str | None:
    vmeta = _VERDICT_MAP.get(ep.expected_verdict.lower(), _VERDICT_MAP["verify"])
    severity = _QUALITY_SEVERITY.get(ep.expected_quality, 0.0)

    episode_body = {
        "id":            str(uuid.uuid4()),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "domain":        ep.domain,
        "action_type":   ep.action_type,
        "risk_tier":     ep.risk_tier,
        "phase":         ep.phase,
        "trust_score":   vmeta["trust"],
        "entropy_h":     vmeta["H"],
        "dissensus_d":   vmeta["D"],
        "verdict":       vmeta["verdict"],
        "confidence":    0.88,
        "ground_truth":  ep.expected_truth,
        "decision_quality": ep.expected_quality,
        "executed":      1 if vmeta["verdict"] == "ACCEPT" else 0,
        "hard_block":    1 if vmeta["verdict"] == "ESCALATE" else 0,
        "review_required": 1 if vmeta["verdict"] in ("VERIFY","ESCALATE","ABSTAIN") else 0,
        "outcome_severity": severity,
        "meta": {
            "source":   "episode_factory",
            "factory_id": ep.id,
            "category": ep.category,
            "lesson":   ep.lesson,
            "trap":     ep.trap,
            "curriculum_level": ep.curriculum_level,
            "question": ep.question[:200],
        },
    }

    outcome_body = {
        "episode_id":   episode_body["id"],
        "ground_truth": ep.expected_truth,
        "outcome":      ep.expected_quality,
        "severity":     severity,
    }

    if dry_run:
        print(f"  DRY  {ep.category:<20} {vmeta['verdict']:<10} {ep.expected_truth:<8} {ep.id}")
        return episode_body["id"]

    resp = _post("/episode", episode_body)
    ep_id = resp.get("episode_id", episode_body["id"])
    outcome_body["episode_id"] = ep_id
    _post("/outcome", outcome_body)
    return ep_id


def main() -> int:
    import urllib.request  # noqa: F401

    parser = argparse.ArgumentParser(description="Feed Episode Factory to AROMER worker")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Feed each episode N times (builds weight)")
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--categories", nargs="*",
                        help="Limit to specific categories")
    args = parser.parse_args()

    episodes = build_episodes()
    if args.categories:
        episodes = {k: v for k, v in episodes.items() if k in args.categories}

    total_in  = sum(len(v) for v in episodes.values())
    total_out = total_in * args.repeat
    print(f"Feeding {total_in} factory episodes × {args.repeat} = {total_out} to {WORKER_URL}")
    print()

    ok = 0
    for repeat_idx in range(args.repeat):
        for category, eps in episodes.items():
            for ep in eps:
                try:
                    ep_id = feed_episode(ep, dry_run=args.dry_run)
                    if ep_id:
                        ok += 1
                        print(f"  OK  [{category:<20}] [{ep.expected_verdict:<8}] [{ep.expected_truth:<8}] {ep.id}")
                except Exception as exc:
                    print(f"  ERR [{ep.id}] {exc}", file=sys.stderr)
                time.sleep(args.delay)

    print(f"\n{ok}/{total_out} episodes fed successfully")

    # Trigger adaptation cycle
    if not args.dry_run and ok > 0:
        print("\nTriggering adaptation cycle...")
        try:
            import urllib.request as ur
            req = ur.Request(WORKER_URL + "/adapt", data=b"{}",
                headers={"Content-Type":"application/json","User-Agent":"AROMER-factory/1.0"},
                method="POST")
            with ur.urlopen(req, timeout=60, context=_SSL) as r:
                result = json.loads(r.read())
            print(f"  episodes_processed: {result.get('episodes_processed', '?')}")
            print(f"  meta_judge_critiques: {result.get('meta_judge_critiques', '?')}")
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)

    return 0 if ok == total_out else 1


if __name__ == "__main__":
    raise SystemExit(main())
