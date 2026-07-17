#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
POST golden seed episodes to the live AROMER Cloudflare Worker.

Usage:
    python scripts/seed_aromer_worker.py [--dry-run] [--worker-url URL]

The golden episodes in remora/aromer/seeds/ are training priors that should be
reflected in the Worker's D1 database so the world model can learn from them.
Episodes that are already in the DB (same episode_id) are skipped (INSERT OR REPLACE
is idempotent on the Worker side).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

WORKER_URL = "https://aromer.razorsharp.workers.dev"
SEED_DIR   = Path(__file__).parent.parent / "remora" / "aromer" / "seeds"

SEED_FILES = [
    SEED_DIR / "10_golden_episodes.seed.jsonl",
    SEED_DIR / "22_golden_cognitive_episodes.seed.jsonl",
]

# Map seed verdict strings to what the Worker gate() helper normalises
VERDICT_MAP = {
    "escalate": "ESCALATE",
    "verify":   "VERIFY",
    "accept":   "ACCEPT",
    "abstain":  "ABSTAIN",
    "ESCALATE": "ESCALATE",
    "VERIFY":   "VERIFY",
    "ACCEPT":   "ACCEPT",
    "ABSTAIN":  "ABSTAIN",
}


def post_json(url: str, payload: dict, dry_run: bool = False) -> dict:
    if dry_run:
        return {"ok": True, "dry_run": True}
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent":    "AROMER-seed/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"ok": False, "status": e.code, "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def load_seeds() -> list[dict]:
    episodes: list[dict] = []
    for path in SEED_FILES:
        if not path.exists():
            print(f"  [SKIP] {path.name} not found", file=sys.stderr)
            continue
        with path.open() as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ep = json.loads(line)
                    ep["_source_file"] = path.name
                    ep["_source_line"] = lineno
                    episodes.append(ep)
                except json.JSONDecodeError as exc:
                    print(f"  [WARN] {path.name}:{lineno}: {exc}", file=sys.stderr)
    return episodes


def build_payload(ep: dict) -> dict:
    """Convert seed schema → Worker /episode POST payload."""
    return {
        "id":              ep.get("episode_id"),          # deterministic id = idempotent
        "domain":          ep.get("domain", "unknown"),
        "risk_tier":       ep.get("risk_tier", "medium"),
        "action_type":     ep.get("action_type", "execution"),
        "phase":           ep.get("phase", "critical"),
        "trust_score":     ep.get("trust_score", 0.5),
        "entropy_h":       ep.get("entropy_H", 0.5),
        "dissensus_d":     ep.get("dissensus_D", 0.5),
        "verdict":         VERDICT_MAP.get(ep.get("verdict", "ABSTAIN"), "ABSTAIN"),
        "confidence":      ep.get("confidence", 0.5),
        "rules_triggered": ep.get("rules_triggered", []),
        "ground_truth":    ep.get("ground_truth", "unknown"),
        "decision_quality":ep.get("decision_quality"),
        "outcome":         ep.get("outcome"),
        "outcome_severity":ep.get("outcome_severity", 0.0),
        "executed":        0 if ep.get("hard_block") or not ep.get("executed") else 1,
        "hard_block":      1 if ep.get("hard_block") else 0,
        "review_required": 1 if ep.get("review_required") else 0,
        "meta":            ep.get("meta", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed golden episodes into AROMER Worker")
    parser.add_argument("--dry-run",    action="store_true", help="Print payloads, don't POST")
    parser.add_argument("--worker-url", default=WORKER_URL,  help="Worker base URL")
    parser.add_argument("--delay",      type=float, default=0.25, help="Seconds between POSTs (default 0.25)")
    args = parser.parse_args()

    episodes = load_seeds()
    print(f"Loaded {len(episodes)} seed episodes from {len(SEED_FILES)} files")

    ep_url     = f"{args.worker_url}/episode"
    ok = fail = skip = 0

    for i, ep in enumerate(episodes, 1):
        payload = build_payload(ep)
        src     = f"{ep['_source_file']}:{ep['_source_line']}"

        if args.dry_run:
            print(f"[{i:3d}] DRY-RUN {src} → {payload['id']} verdict={payload['verdict']}")
            ok += 1
            continue

        result = post_json(ep_url, payload)
        eid    = result.get("episode_id", payload["id"])

        if result.get("ok"):
            status_char = "✓"
            ok += 1
        else:
            status_char = "✗"
            fail += 1
            print(f"[{i:3d}] FAIL {src} → {result}", file=sys.stderr)

        print(f"[{i:3d}] {status_char} {src} → {eid}")

        if args.delay > 0 and i < len(episodes):
            time.sleep(args.delay)

    print(f"\nDone: {ok} OK  {fail} failed  {skip} skipped")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
