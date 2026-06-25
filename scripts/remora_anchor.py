#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Manage the local REMORA agent-session intent anchor.

Usage:
    python scripts/remora_anchor.py "Refactor the RAG oracle for safer chunking"
    python scripts/remora_anchor.py --show
    python scripts/remora_anchor.py --clear
"""
from __future__ import annotations

import argparse
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from remora.agent_hook.intent_anchor import IntentAnchor
from remora.agent_hook.lyapunov_tracker import LyapunovTracker


def main() -> None:
    parser = argparse.ArgumentParser(description="REMORA agent-session intent anchor")
    parser.add_argument("intent", nargs="?", help="Session goal to anchor")
    parser.add_argument("--show", action="store_true", help="Show current anchor")
    parser.add_argument("--clear", action="store_true", help="Clear anchor and Lyapunov state")
    parser.add_argument("--session-id", default="", help="Optional external session id")
    args = parser.parse_args()

    anchor = IntentAnchor()
    tracker = LyapunovTracker()

    if args.clear:
        anchor.clear()
        tracker.clear()
        print("[REMORA] Session intent and Lyapunov state cleared.")
        return

    if args.show:
        if not anchor.anchored:
            print("[REMORA] No intent anchored for this session.")
            return

        summary = tracker.summary()
        print(f"[REMORA] Anchored intent: {anchor.intent}")
        print(f"         Session ID:      {anchor.session_id or '(none)'}")
        print(f"         Tool calls:      {anchor.tool_call_count}")
        print(f"         Lyapunov V(t):   {summary.get('V', 'N/A')}")
        print(f"         Converging:      {summary.get('converging', 'N/A')}")
        return

    if not args.intent:
        parser.print_help()
        return

    anchor.anchor(args.intent, session_id=args.session_id, verified=False)
    print(f"[REMORA] Intent anchored: {args.intent}")
    print("         Future tool calls will be measured for drift against this goal.")
    print("         To clear: python scripts/remora_anchor.py --clear")


if __name__ == "__main__":
    main()
