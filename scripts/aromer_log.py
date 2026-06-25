#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER Progress Log Viewer

Queries the live AROMER Cloudflare Worker and shows learning progression:
  - Episode count + outcome distribution
  - Adaptation cycle history (every hour via cron)
  - World model P(harm) estimates per domain
  - Oracle bandit rankings
  - Recent governance decisions

Usage
-----
  python scripts/aromer_log.py                # live worker log
  python scripts/aromer_log.py --local        # local JSONL only
  python scripts/aromer_log.py --watch 30     # refresh every 30s
  python scripts/aromer_log.py --post-demo    # push demo episodes to live worker

Make target:  make aromer-log
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORKER_URL  = "https://aromer.razorsharp.workers.dev"
LOCAL_STORE = Path.home() / ".aromer" / "episodes.jsonl"
_SSL        = ssl.create_default_context()


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_log(url: str = WORKER_URL, limit: int = 15) -> dict | None:
    try:
        req = urllib.request.Request(
            f"{url}/log?limit={limit}",
            headers={"User-Agent": "AROMER-log/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10, context=_SSL) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def fetch_status(url: str = WORKER_URL) -> dict | None:
    try:
        req = urllib.request.Request(f"{url}/status",
                                     headers={"User-Agent": "AROMER-log/1.0"})
        with urllib.request.urlopen(req, timeout=8, context=_SSL) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def count_local_episodes() -> int:
    if not LOCAL_STORE.exists():
        return 0
    return sum(1 for line in LOCAL_STORE.read_text("utf-8").splitlines() if line.strip())


# ---------------------------------------------------------------------------
# Demo episode pusher (to populate the live worker for testing)
# ---------------------------------------------------------------------------

def push_demo_episodes(url: str = WORKER_URL) -> None:
    """Push a set of representative episodes + outcomes to the live worker."""
    print("\nPushing demo episodes to live AROMER Worker...\n")

    import uuid
    from datetime import datetime, timezone

    episodes = [
        dict(domain="financial",     risk_tier="critical", action_type="write",     trust_score=0.30, entropy_h=0.88, dissensus_d=0.71, verdict="ESCALATE", confidence=0.92, ground_truth="harmful", outcome="correct_block"),
        dict(domain="information",   risk_tier="low",      action_type="read",      trust_score=0.85, entropy_h=0.20, dissensus_d=0.08, verdict="ACCEPT",    confidence=0.88, ground_truth="benign",  outcome="correct_accept"),
        dict(domain="database",      risk_tier="high",     action_type="write",     trust_score=0.80, entropy_h=0.40, dissensus_d=0.18, verdict="ACCEPT",    confidence=0.82, ground_truth="harmful", outcome="false_accept"),
        dict(domain="cybersecurity", risk_tier="critical", action_type="execution", trust_score=0.25, entropy_h=0.91, dissensus_d=0.82, verdict="ESCALATE", confidence=0.95, ground_truth="harmful", outcome="correct_block"),
        dict(domain="database",      risk_tier="critical", action_type="delete",    trust_score=0.20, entropy_h=0.92, dissensus_d=0.85, verdict="ESCALATE", confidence=0.97, ground_truth="harmful", outcome="correct_block"),
        dict(domain="information",   risk_tier="low",      action_type="read",      trust_score=0.90, entropy_h=0.15, dissensus_d=0.05, verdict="ACCEPT",    confidence=0.91, ground_truth="benign",  outcome="correct_accept"),
        dict(domain="financial",     risk_tier="high",     action_type="write",     trust_score=0.45, entropy_h=0.78, dissensus_d=0.62, verdict="VERIFY",    confidence=0.80, ground_truth="harmful", outcome="correct_intercept_verify"),
        dict(domain="cybersecurity", risk_tier="high",     action_type="read",      trust_score=0.60, entropy_h=0.55, dissensus_d=0.40, verdict="VERIFY",    confidence=0.82, ground_truth="benign",  outcome="benign_review"),
        dict(domain="agentic",       risk_tier="critical", action_type="execution", trust_score=0.35, entropy_h=0.87, dissensus_d=0.75, verdict="ESCALATE", confidence=0.93, ground_truth="harmful", outcome="correct_block"),
        dict(domain="agentic",       risk_tier="medium",   action_type="write",     trust_score=0.65, entropy_h=0.60, dissensus_d=0.48, verdict="ESCALATE", confidence=0.78, ground_truth="benign",  outcome="false_block"),
    ]

    posted = 0
    for ep_data in episodes:
        outcome = ep_data.pop("outcome")
        ground_truth = ep_data.pop("ground_truth")
        ep_id   = str(uuid.uuid4())
        ep_data["id"]        = ep_id
        ep_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        ep_data["phase"]     = "ordered" if ep_data["entropy_h"] < 0.45 else (
                               "critical" if ep_data["entropy_h"] < 0.75 else "disordered")

        # POST episode
        payload = json.dumps(ep_data).encode()
        req = urllib.request.Request(f"{url}/episode", data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "AROMER-log/1.0"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10, context=_SSL) as r:
                json.loads(r.read())
        except Exception as exc:
            print(f"  ERROR posting episode: {exc}")
            continue

        # POST outcome
        harmful_miss = outcome in {"false_accept", "safety_violation"}
        out_payload = json.dumps({
            "episode_id": ep_id,
            "outcome": outcome,
            "ground_truth": ground_truth,
            "severity": -0.8 if harmful_miss else 0.7,
        }).encode()
        req2 = urllib.request.Request(f"{url}/outcome", data=out_payload,
            headers={"Content-Type": "application/json", "User-Agent": "AROMER-log/1.0"},
            method="POST")
        try:
            with urllib.request.urlopen(req2, timeout=10, context=_SSL) as r:
                json.loads(r.read())
            posted += 1
            print(f"  OK  {ep_data['domain']:<14} {ep_data['verdict']:<10} -> {outcome}")
        except Exception as exc:
            print(f"  ERROR posting outcome: {exc}")

    print(f"\n  Pushed {posted}/{len(episodes)} episodes to live worker")

    # Trigger adaptation cycle
    print("\nTriggering adaptation cycle...")
    req3 = urllib.request.Request(f"{url}/adapt", data=b"{}",
        headers={"Content-Type": "application/json", "User-Agent": "AROMER-log/1.0"},
        method="POST")
    try:
        with urllib.request.urlopen(req3, timeout=30, context=_SSL) as r:
            result = json.loads(r.read())
        print("  Adaptation complete:")
        print(f"    episodes_processed: {result.get('episodes_processed', '?')}")
        print(f"    false_accept_rate:  {result.get('false_accept_rate', '?')}")
        print(f"    meta_judge_critiques: {result.get('meta_judge_critiques', '?')}")
    except Exception as exc:
        print(f"  ERROR: {exc}")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def bar(value: float, width: int = 20) -> str:
    n = max(0, min(width, int(value * width)))
    return "#" * n + "." * (width - n)


def print_log(data: dict, local_count: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*66}")
    print(f"  AROMER Progress Log  |  {ts}")
    print(f"{'='*66}")

    if "error" in data:
        print(f"\n  [!] Worker error: {data['error']}")
        print(f"  Local episodes: {local_count}")
        return

    totals = data.get("totals", {})
    print(f"\n  Worker:          {data.get('worker', 'aromer')} v{data.get('version', '?')}")
    print(f"  Episodes total:  {totals.get('episodes', 0)}  "
          f"(local JSONL: {local_count})")
    print(f"  Cycles run:      {len(data.get('recent_cycles', []))}")

    # Outcome distribution
    outcomes = totals.get("outcome_distribution", [])
    if outcomes:
        print("\n  Decision-quality distribution:")
        for r in outcomes:
            outcome = str(r.get("outcome", "?"))
            n       = int(r.get("n", 0))
            color   = ""
            if "correct" in outcome:
                color = "\033[92m"
            elif "false" in outcome or "violation" in outcome:
                color = "\033[91m"
            print(f"    {color}{outcome:<22}\033[0m  {n}")

    # World model
    world = data.get("world_model", [])
    if world:
        print("\n  World model P(harm) — top contexts:")
        for r in world:
            ph     = float(r.get("p_harm", 0))
            n_obs  = int(r.get("n_observations", 0))
            domain = str(r.get("domain", "?"))
            action = str(r.get("action_type", "?"))
            risk   = str(r.get("risk_tier", "?"))
            conf   = str(r.get("confidence", r.get("confidence_level", "low")))
            b      = bar(ph)
            color  = "\033[91m" if ph > 0.65 else ("\033[93m" if ph > 0.45 else "\033[92m")
            print(f"    {domain:<14} {action:<12} {risk:<9}  "
                  f"{color}P={ph:.3f}{chr(27)}[0m  [{b}]  n={n_obs}  confidence={conf}")

    # Oracle bandits
    oracles = data.get("oracle_bandits", [])
    if oracles:
        print("\n  Oracle bandit rankings (Thompson Sampling):")
        for i, r in enumerate(oracles, 1):
            oracle_id = str(r.get("oracle_id", "?"))
            acc       = float(r.get("expected_accuracy", 0.5))
            n_obs     = int(r.get("n_observations", 0))
            print(f"    {i}. {oracle_id:<14}  accuracy={acc:.3f}  n={n_obs}")

    # Adaptation cycles
    cycles = data.get("recent_cycles", [])
    if cycles:
        print("\n  Adaptation cycle history (most recent first):")
        print(f"    {'Timestamp':<22} {'Eps':>5} {'FA rate':>8} {'FB rate':>8} "
              f"{'Judge':>6} {'Score':>6}")
        print(f"    {'-'*62}")
        for c in cycles[:8]:
            ts_raw = str(c.get("timestamp", "?"))[:19]
            eps    = int(c.get("episodes_processed", 0))
            fa     = float(c.get("false_accept_rate") or 0)
            fb     = float(c.get("false_block_rate",  0))
            judge  = int(c.get("meta_judge_count", 0))
            score_raw = c.get("mean_critique_score")
            score = f"{float(score_raw):.2f}" if score_raw is not None else "  -"
            fa_color = "\033[91m" if fa > 0.10 else "\033[92m"
            print(f"    {ts_raw:<22} {eps:>5} "
                  f"{fa_color}{fa:.4f}{chr(27)}[0m  {fb:.4f}  {judge:>5}  {score:>6}")
    else:
        print("\n  No adaptation cycles yet — cron runs at :00 each hour")

    # Recent episodes
    recent = data.get("recent_episodes", [])
    if recent:
        print("\n  Recent episodes:")
        print(f"    {'Time':<19} {'Domain':<14} {'Verdict':<10} {'Quality':<26} "
              f"{'Trust':>6} {'Critique':>8}")
        print(f"    {'-'*82}")
        for e in recent[:8]:
            ts_e     = str(e.get("timestamp", "?"))[:19]
            domain   = str(e.get("domain", "?"))
            verdict  = str(e.get("verdict", "?"))
            outcome  = str(e.get("decision_quality") or e.get("outcome", "pending"))
            trust    = float(e.get("trust_score", 0))
            critique_raw = e.get("critique_score")
            critique = f"{float(critique_raw):+.2f}" if critique_raw is not None else "   -"
            o_color  = "\033[91m" if "false" in outcome or "violation" in outcome else (
                       "\033[92m" if "correct" in outcome else "")
            v_color  = "\033[91m" if verdict == "ESCALATE" else (
                       "\033[93m" if verdict in ("VERIFY","ABSTAIN") else "\033[92m")
            print(f"    {ts_e:<19} {domain:<14} "
                  f"{v_color}{verdict:<10}{chr(27)}[0m "
                  f"{o_color}{outcome:<26}{chr(27)}[0m "
                  f"{trust:>6.3f}  {critique:>8}")

    print("\n  Next cron run: top of next hour (0 * * * *)")
    print(f"  Live log:      {WORKER_URL}/log?format=text")
    print(f"  Worker stats:  {WORKER_URL}/stats")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AROMER progress log viewer")
    parser.add_argument("--url",        default=WORKER_URL)
    parser.add_argument("--limit",      type=int, default=15)
    parser.add_argument("--watch",      type=int, metavar="SECONDS",
                        help="Refresh every N seconds")
    parser.add_argument("--local",      action="store_true",
                        help="Show local JSONL store only")
    parser.add_argument("--post-demo",  action="store_true",
                        help="Push demo episodes to live worker (for testing)")
    args = parser.parse_args()

    if args.post_demo:
        push_demo_episodes(args.url)
        time.sleep(1)

    while True:
        local_count = count_local_episodes()
        if args.local:
            data: dict = {"totals": {"episodes": local_count}, "version": "local",
                          "worker": "local", "recent_cycles": [], "world_model": [],
                          "oracle_bandits": [], "recent_episodes": []}
        else:
            status = fetch_status(args.url)
            data   = fetch_log(args.url, args.limit) or {}
            if status and "error" not in status:
                data["version"] = status.get("version", "?")
                data["worker"]  = status.get("worker", "aromer")

        print_log(data, local_count)

        if not args.watch:
            break
        print(f"  [Refreshing in {args.watch}s — Ctrl+C to stop]\n")
        try:
            time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n  Stopped.")
            break


if __name__ == "__main__":
    main()
