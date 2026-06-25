#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER episode recorder — Claude Code PreToolUse hook.

Reads a tool-call payload from stdin, infers domain/action_type/risk,
and POSTs a labeled episode to the live AROMER worker.  Always exits 0
(never blocks — this is a recorder, not a gatekeeper).

The episode is recorded with ground_truth='unknown' and verdict='pending'.
Label it later via:
  python scripts/aromer_log.py --label <episode_id> --truth harmful|benign

Add to .claude/settings.json:
  {
    "hooks": {
      "PreToolUse": [
        {"matcher": ".*", "hooks": [
          {"type": "command", "command": "python scripts/aromer_recorder_hook.py"}
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

WORKER_URL = os.environ.get("AROMER_WORKER_URL", "https://aromer.razorsharp.workers.dev")
ENABLED    = os.environ.get("AROMER_RECORDER", "1") == "1"
_SSL       = ssl.create_default_context()

# ── Domain/action_type inference ─────────────────────────────────────────────

_CRITICAL_PATTERNS = [
    # ── CRITICAL (irreversible, destructive) ─────────────────────────────────
    (r"rm\s+-rf|rmdir|del\s+/", "system", "destructive_write", "critical"),
    (r"drop\s+table|truncate\s+table|delete\s+from.*where\s+1", "database", "destructive_write", "critical"),
    (r"git\s+push\s+.*--force|git\s+reset\s+--hard", "git", "force_push", "critical"),
    (r"terraform\s+apply|terraform\s+destroy", "infrastructure", "deployment", "critical"),
    (r"docker\s+run.*--privileged|podman\s+run.*--privileged", "system", "execution", "critical"),
    # ── HIGH (production-mutating, privileged) ────────────────────────────────
    (r"wrangler\s+deploy|npx\s+wrangler\s+publish", "cloudflare", "deployment", "high"),
    (r"npx\s+wrangler\s+d1\s+execute.*--remote", "cloudflare", "destructive_write", "high"),
    (r"kubectl\s+delete|kubectl\s+apply", "infrastructure", "deployment", "high"),
    (r"iptables|firewall-cmd|ufw", "network", "write", "high"),
    (r"ssh\s+.*root@|scp\s+.*root@", "system", "execution", "high"),
    (r"chmod\s+777|chown\s+-R\s+root", "system", "write", "high"),
    # ── MEDIUM (network-mutating, package-mutating) ───────────────────────────
    (r"git\s+push\b(?!.*--force)", "git", "write", "medium"),
    (r"curl\s+.*-X\s+(POST|PUT|PATCH|DELETE)", "network", "write", "medium"),
    (r"insert\s+into|update\s+.*set\b", "database", "write", "medium"),
    # ── LOW (reads, local builds, safe dev-cycle commands) ───────────────────
    (r"git\s+commit", "git", "write", "low"),
    (r"git\s+(status|log|diff|branch|fetch|pull|add)\b", "git", "read", "low"),
    (r"select\s+.*from\b", "database", "read", "low"),
    (r"curl\s+.*-X\s+GET|curl\s+[^-]", "network", "read", "low"),
    (r"npm\s+(install|ci|run|test|build)\b", "system", "write", "low"),
    (r"pip\s+install\b", "system", "write", "low"),
    (r"python\s+-m\s+pytest|pytest\b", "system", "read", "low"),
    (r"python\s+-m\s+mypy|mypy\b|ruff\b|flake8\b|pylint\b", "system", "read", "low"),
    (r"\bmake\b", "system", "execution", "low"),
    (r"cargo\s+(build|test|check|clippy)\b", "system", "read", "low"),
    (r"go\s+(build|test|vet|run)\b", "system", "read", "low"),
    (r"uvicorn\b|gunicorn\b|flask\s+run\b", "system", "execution", "low"),
    (r"docker\s+(build|ps|images|logs)\b", "system", "read", "low"),
    (r"cat\b|less\b|head\b|tail\b|grep\b|find\b|ls\b|pwd\b", "system", "read", "low"),
]

def _infer_bash(command: str) -> tuple[str, str, str, float]:
    """(domain, action_type, risk_tier, entropy_H)"""
    cmd = command.lower().strip()
    for pat, domain, action, risk in _CRITICAL_PATTERNS:
        if re.search(pat, cmd):
            h_map = {"critical": 0.88, "high": 0.72, "medium": 0.55, "low": 0.22}
            return domain, action, risk, h_map.get(risk, 0.55)
    # Default: unrecognised Bash — treat as low-risk dev-cycle command.
    # Previously "medium" caused trust=0.45 → ABSTAIN/VERIFY on benign commands.
    # Unknown commands in a developer session are almost always benign (test runs,
    # ad-hoc scripts, tool invocations). High-risk patterns are matched above.
    return "system", "execution", "low", 0.22


def _infer_tool(tool_name: str, tool_input: dict) -> tuple[str, str, str, float]:
    name = tool_name.lower()
    if name == "bash":
        return _infer_bash(str(tool_input.get("command", "")))
    if name in ("write", "edit"):
        path = str(tool_input.get("file_path", ""))
        if re.search(r"\.(env|secret|key|pem|pfx)\b", path, re.IGNORECASE):
            return "system", "write", "high", 0.65
        return "system", "write", "low", 0.25
    if name in ("read", "glob", "grep"):
        return "information", "read", "low", 0.18
    if name == "agent":
        return "agentic", "execution", "high", 0.72
    return "system", "execution", "medium", 0.50


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    if not ENABLED:
        return 0

    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0   # malformed — don't block

    tool_name  = str(payload.get("tool_name", "unknown"))
    tool_input = payload.get("tool_input", {})
    session_id = str(payload.get("session_id", ""))

    domain, action_type, risk_tier, entropy_H = _infer_tool(tool_name, tool_input)

    # Heuristic trust score: low entropy → high trust; high entropy → low trust
    trust_score = round(max(0.1, min(0.9, 1.0 - entropy_H)), 3)
    dissensus_D = round(max(0.05, entropy_H * 0.8), 3)

    phase = "critical" if entropy_H > 0.70 else "ordered"

    try:
        # Step 1: Ask AROMER for a real governance verdict via /decide
        # This is what turns the recorder into a real governance signal.
        decide_body = {
            "domain":      domain,
            "action_type": action_type,
            "risk_tier":   risk_tier,
            "trust_score": trust_score,
            "entropy_h":   entropy_H,
            "dissensid_d": dissensus_D,
            "phase":       phase,
            "record_episode": False,   # we handle episode recording below
        }
        req_decide = urllib.request.Request(
            WORKER_URL + "/decide",
            data=json.dumps(decide_body).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "AROMER-hook/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req_decide, timeout=4, context=_SSL) as r:
            decide_resp = json.loads(r.read())

        verdict    = str(decide_resp.get("verdict",    "verify")).upper()
        confidence = float(decide_resp.get("confidence", 0.5))
        p_harm     = float(decide_resp.get("p_harm",    0.5))
    except Exception:
        verdict, confidence, p_harm = "VERIFY", 0.5, 0.5

    try:
        # Step 2: Record the episode with the real verdict
        episode = {
            "domain":       domain,
            "action_type":  action_type,
            "risk_tier":    risk_tier,
            "trust_score":  trust_score,
            "entropy_h":    entropy_H,
            "dissensus_d":  dissensus_D,
            "verdict":      verdict,
            "confidence":   confidence,
            "outcome":      "pending",
            "ground_truth": "unknown",   # operator labels this later
            "phase":        phase,
            "meta": {
                "source":        "claude_code_pretooluse",
                "tool":          tool_name,
                "session_id":    session_id[:32],
                "input_preview": json.dumps(tool_input)[:200],
                "p_harm":        round(p_harm, 4),
            },
        }
        req_ep = urllib.request.Request(
            WORKER_URL + "/episode",
            data=json.dumps(episode).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "AROMER-hook/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req_ep, timeout=3, context=_SSL) as r:
            resp = json.loads(r.read())
            ep_id = resp.get("episode_id", "")
            if ep_id:
                import pathlib
                session_dir = pathlib.Path(os.environ.get("REMORA_SESSION_DIR", ".remora_session"))
                session_dir.mkdir(exist_ok=True)
                # Append to session log so all episode IDs from this session are reachable
                log = session_dir / "episode_log.jsonl"
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "episode_id": ep_id, "tool": tool_name,
                        "domain": domain, "verdict": verdict, "p_harm": round(p_harm, 4),
                    }) + "\n")
                (session_dir / "last_episode.txt").write_text(ep_id)
    except Exception:
        pass  # fire-and-forget — never slow down or block the tool call

    return 0   # always allow — recorder never blocks


if __name__ == "__main__":
    raise SystemExit(main())
