#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER auto-label — Claude Code PostToolUse hook.

Runs after every tool call.  Reads the last recorded episode ID from
the session log and automatically labels it as benign.

Rationale
---------
In a developer session, almost every tool call is benign — git push,
wrangler deploy, file edits, bash commands.  A failed tool call is also
benign: it failed safely, no harm done.  The rare harmful case (wrong
directory deleted, wrong env deployed) requires the developer to notice
and manually label it:

  make aromer-label-harmful   # you notice something went wrong

Auto-label heuristics
---------------------
  SUCCESS (exit 0, no error markers)  →  benign
  FAILURE (exit non-zero, error text) →  benign  (failed safely)
  DESTRUCTIVE PATTERN + success       →  benign_review  (higher friction)

The PostToolUse hook receives JSON on stdin with tool_response included.
We use that to detect destructive patterns and adjust severity accordingly.

Registration
------------
.claude/settings.json:
  {
    "hooks": {
      "PostToolUse": [
        {"matcher": ".*", "hooks": [
          {"type": "command",
           "command": "python C:/Users/Stian/REMORA/scripts/aromer_auto_label_hook.py"}
        ]}
      ]
    }
  }
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.request
from pathlib import Path

WORKER_URL  = os.environ.get("AROMER_WORKER_URL", "https://aromer.razorsharp.workers.dev")
ENABLED     = os.environ.get("AROMER_RECORDER", "1") == "1"
SESSION_DIR = Path(os.environ.get("REMORA_SESSION_DIR", ".remora_session"))
_SSL        = ssl.create_default_context()

_DESTRUCTIVE = re.compile(
    r"rm\s+-rf|rmdir|drop\s+table|truncate|git\s+reset\s+--hard|"
    r"wrangler\s+d1.*--remote|terraform\s+destroy|kubectl\s+delete",
    re.IGNORECASE,
)

_HARM_INDICATORS = [
    "permission denied",
    "access denied",
    "fatal error",
    "unrecoverable",
    "data loss",
    "cannot be undone",
]


def _label(episode_id: str, ground_truth: str, severity: float) -> None:
    body = json.dumps({
        "episode_id":   episode_id,
        "ground_truth": ground_truth,
        "outcome":      "benign_review" if ground_truth == "benign" and severity < 0 else
                        "correct_accept" if ground_truth == "benign" else "correct_block",
        "severity":     severity,
    }).encode("utf-8")
    req = urllib.request.Request(
        WORKER_URL + "/outcome", data=body,
        headers={"Content-Type": "application/json", "User-Agent": "AROMER-auto/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3, context=_SSL):
        pass


def _last_episode_id() -> str | None:
    p = SESSION_DIR / "last_episode.txt"
    return p.read_text("utf-8").strip() if p.exists() else None


def _read_session_log_last() -> dict | None:
    log = SESSION_DIR / "episode_log.jsonl"
    if not log.exists():
        return None
    lines = [line.strip() for line in log.read_text("utf-8").splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else None


def _update_local_bridge(log_entry: dict, outcome_type_str: str, severity: float) -> None:
    """Propagate the outcome to the local AromerAdapterBridge (fire-and-forget).

    This closes the local feedback loop so the Python adaptation engines
    (ThermodynamicAdapter, AdaptiveThresholdEngine, OracleBandit) receive
    outcome signals — not just the remote Cloudflare Worker.
    """
    try:
        import sys as _sys
        import pathlib as _pathlib
        _repo = str(_pathlib.Path(__file__).resolve().parents[1])
        if _repo not in _sys.path:
            _sys.path.insert(0, _repo)

        from remora.aromer.experience.episode import (
            Episode, OutcomeType, GroundTruth,
        )
        from remora.aromer.integration.bridge import AromerAdapterBridge

        # Map string to enum
        _outcome_map = {
            "correct_accept": OutcomeType.CORRECT_ACCEPT,
            "benign_review":  OutcomeType.BENIGN_REVIEW,
            "correct_block":  OutcomeType.CORRECT_BLOCK,
            "false_accept":   OutcomeType.FALSE_ACCEPT,
            "false_block":    OutcomeType.FALSE_BLOCK,
        }
        outcome = _outcome_map.get(outcome_type_str, OutcomeType.CORRECT_ACCEPT)

        episode = Episode(
            domain=log_entry.get("domain", "system"),
            risk_tier=log_entry.get("risk_tier", "low"),
            action_type=log_entry.get("action_type", "execution"),
            phase="ordered",
            trust_score=float(log_entry.get("trust_score", 0.72)),
            entropy_H=float(log_entry.get("entropy_h", 0.22)),
            dissensus_D=float(log_entry.get("dissensus_d", 0.05)),
            verdict=log_entry.get("verdict", "ACCEPT"),
            confidence=float(log_entry.get("confidence", 0.85)),
            rules_triggered=[],
        )
        # Attach outcome before passing to bridge
        object.__setattr__(episode, "outcome", outcome)
        object.__setattr__(episode, "ground_truth", GroundTruth.BENIGN)

        bridge = AromerAdapterBridge()
        bridge.record_outcome(episode)
    except Exception:
        pass  # never slow down the session


def main() -> int:
    if not ENABLED:
        return 0

    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0

    ep_id = _last_episode_id()
    if not ep_id:
        return 0

    tool_input = payload.get("tool_input", {})
    tool_response = str(payload.get("tool_response", ""))

    # Determine severity
    command = str(tool_input.get("command", "")) if isinstance(tool_input, dict) else ""
    is_destructive = bool(_DESTRUCTIVE.search(command))
    has_harm_text  = any(h in tool_response.lower() for h in _HARM_INDICATORS)

    if has_harm_text:
        ground_truth  = "benign"
        severity      = -0.1
        outcome_type  = "benign_review"
    elif is_destructive:
        ground_truth  = "benign"
        severity      = -0.2
        outcome_type  = "benign_review"
    else:
        ground_truth  = "benign"
        severity      = 0.5
        outcome_type  = "correct_accept"

    try:
        _label(ep_id, ground_truth, severity)
        (SESSION_DIR / "last_episode.txt").write_text("")
    except Exception:
        pass  # fire-and-forget Worker call

    # Also update local adaptation engines — the Worker call alone is not enough
    log_entry = _read_session_log_last() or {}
    _update_local_bridge(log_entry, outcome_type, severity)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
