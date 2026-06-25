#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Label pending AROMER episodes with ground truth.

After the PreToolUse recorder hook captures real tool calls, an operator
labels each episode: was the action actually safe (benign) or harmful?

Usage
-----
  # Label the most recent episode
  python scripts/aromer_label.py --truth benign
  python scripts/aromer_label.py --truth harmful

  # Label a specific episode
  python scripts/aromer_label.py --id abc123 --truth benign

  # Show all pending episodes from this session
  python scripts/aromer_label.py --show-pending

  # Label all pending from session log as benign (bulk — use carefully)
  python scripts/aromer_label.py --label-all --truth benign

Make targets:
  make aromer-label-benign    # last episode was safe
  make aromer-label-harmful   # last episode was harmful
  make aromer-pending         # show pending episodes
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORKER_URL  = "https://aromer.razorsharp.workers.dev"
SESSION_DIR = Path(os.environ.get("REMORA_SESSION_DIR", ".remora_session"))
_SSL        = ssl.create_default_context()


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        WORKER_URL + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "AROMER-label/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10, context=_SSL) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_last_episode_id() -> str | None:
    p = SESSION_DIR / "last_episode.txt"
    return p.read_text().strip() if p.exists() else None


def _load_session_log() -> list[dict]:
    log = SESSION_DIR / "episode_log.jsonl"
    if not log.exists():
        return []
    rows = []
    for line in log.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def _label(episode_id: str, ground_truth: str) -> bool:
    try:
        resp = _post("/outcome", {
            "episode_id":  episode_id,
            "ground_truth": ground_truth,
            "severity":     0.7 if ground_truth == "benign" else -0.8,
        })
        return resp.get("ok", False)
    except Exception as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        return False


def cmd_show_pending(args) -> int:
    rows = _load_session_log()
    if not rows:
        print("No session log found. Make some tool calls first.")
        return 0

    print(f"Session log: {SESSION_DIR / 'episode_log.jsonl'}")
    print(f"Total in session: {len(rows)}\n")
    print(f"  {'Episode ID':<38} {'Tool':<12} {'Domain':<14} {'Verdict':<10} P(harm)")
    print(f"  {'-'*80}")
    for row in rows[-20:]:
        eid  = row.get("episode_id", "?")[:36]
        tool = row.get("tool", "?")[:12]
        dom  = row.get("domain", "?")[:14]
        verd = row.get("verdict", "?")[:10]
        ph   = row.get("p_harm", 0)
        print(f"  {eid:<38} {tool:<12} {dom:<14} {verd:<10} {ph:.2f}")

    last = _get_last_episode_id()
    if last:
        print(f"\nMost recent: {last}")
        print("Label it:  python scripts/aromer_label.py --truth benign|harmful")
    return 0


def cmd_label(args) -> int:
    ep_id = args.id or _get_last_episode_id()
    if not ep_id:
        print("ERROR: No episode ID. Provide --id or ensure recorder hook has run.", file=sys.stderr)
        return 1

    truth = args.truth.lower()
    if truth not in {"benign", "harmful"}:
        print(f"ERROR: --truth must be 'benign' or 'harmful', got {truth!r}", file=sys.stderr)
        return 1

    ok = _label(ep_id, truth)
    if ok:
        print(f"Labeled {ep_id[:16]}… as {truth}")
    else:
        print(f"ERROR: Failed to label {ep_id}", file=sys.stderr)
        return 1
    return 0


def cmd_label_all(args) -> int:
    truth = args.truth.lower()
    if truth not in {"benign", "harmful"}:
        print(f"ERROR: --truth must be 'benign' or 'harmful', got {truth!r}", file=sys.stderr)
        return 1

    rows = _load_session_log()
    if not rows:
        print("No session log found.")
        return 0

    ok = 0
    for row in rows:
        ep_id = row.get("episode_id")
        if not ep_id:
            continue
        success = _label(ep_id, truth)
        flag = "OK" if success else "!!"
        dom = row.get("domain", "?")[:12]
        verd = row.get("verdict", "?")[:8]
        print(f"  [{flag}] {ep_id[:16]}… {dom:<12} {verd:<8} -> {truth}")
        if success:
            ok += 1

    print(f"\nLabeled {ok}/{len(rows)} episodes as {truth}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Label AROMER episodes")
    parser.add_argument("--id",          help="Episode ID to label (default: last)")
    parser.add_argument("--truth",       choices=["benign", "harmful"],
                        help="Ground truth: benign = safe action, harmful = caused or risked harm")
    parser.add_argument("--show-pending", action="store_true",
                        help="Show pending episodes from this session")
    parser.add_argument("--label-all",   action="store_true",
                        help="Label ALL session episodes (requires --truth)")
    args = parser.parse_args()

    if args.show_pending:
        return cmd_show_pending(args)
    if args.label_all:
        if not args.truth:
            print("ERROR: --label-all requires --truth", file=sys.stderr)
            return 1
        return cmd_label_all(args)
    if args.truth:
        return cmd_label(args)

    # Default: show pending
    return cmd_show_pending(args)


if __name__ == "__main__":
    raise SystemExit(main())
