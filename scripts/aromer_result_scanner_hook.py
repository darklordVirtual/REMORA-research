#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA tool-result content scanner — Claude Code PostToolUse hook.

Intercepts tool results BEFORE they reach the LLM and scans for
indirect prompt injection attacks. An attacker who controls server
content (WebFetch, database query, external file) can embed instructions
that hijack the agent mid-session. This hook closes that gap.

Verdict actions
---------------
  ACCEPT   → exit 0  (result passes through unchanged)
  VERIFY   → output JSON with prepended security notice (result still shown)
  ESCALATE → output blocking JSON (result quarantined, LLM never sees it)

Registration in .claude/settings.json (MUST run before aromer_auto_label_hook):
  "PostToolUse": [
    {"matcher": "WebFetch|WebSearch|Bash|Read",
     "hooks": [{"type": "command",
                "command": "python <repo-root>/scripts/aromer_result_scanner_hook.py"}]},
    ...existing hooks...
  ]
"""
from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from remora.agent_hook.result_scanner import ScanVerdict, ToolResultScanner

# Network-origin or otherwise attacker-reachable tool output.
_REMOTE_TOOLS = {
    "WebFetch", "WebSearch",
    "mcp__brave_search", "mcp__fetch",
}
# Local tool output is attacker-reachable too (``curl`` through Bash, a
# README in a cloned repository through Read), so it is always scanned by the
# local heuristics. SR-08 / SEC-08 concerns only the oracle: it sends text
# off-host, so local output reaches it solely on explicit opt-in. (The SR-08
# change first dropped local tools from scanning altogether; PR #1140 review.)
_LOCAL_TOOLS = {"Bash", "Read"}
_SCAN_TOOLS = _REMOTE_TOOLS | _LOCAL_TOOLS
_LOCAL_ORACLE_OPT_IN = os.environ.get("AROMER_SCAN_LOCAL") == "1"

# The oracle requires an explicitly configured destination and credential;
# there is no default public worker (SR-08).
_scanner = ToolResultScanner(
    oracle_enabled=bool(
        os.environ.get("AROMER_WORKER_URL", "").strip()
        and os.environ.get("AROMER_WORKER_TOKEN", "").strip()
    )
)
_local_only_scanner = ToolResultScanner(oracle_enabled=False)


def _scanner_for(tool_name: str) -> ToolResultScanner:
    if tool_name in _LOCAL_TOOLS and not _LOCAL_ORACLE_OPT_IN:
        return _local_only_scanner
    return _scanner


def _extract_result_text(hook_input: dict) -> str:
    """Pull the result text from the hook payload."""
    tool_response = hook_input.get("tool_response", {})
    # Claude Code wraps the result in tool_response
    if isinstance(tool_response, dict):
        content = tool_response.get("content", "")
        if isinstance(content, list):
            # Content blocks
            return " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return str(content)
    return str(tool_response)


def main() -> None:
    try:
        raw = sys.stdin.read()
        hook_input: dict = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)  # malformed input — pass through

    tool_name = str(hook_input.get("tool_name", "unknown"))

    # Only scan relevant tools
    if tool_name not in _SCAN_TOOLS:
        sys.exit(0)

    result_text = _extract_result_text(hook_input)
    if not result_text or len(result_text) < 20:
        sys.exit(0)  # too short to contain an injection

    try:
        envelope = _scanner_for(tool_name).scan(tool_name, result_text)
    except Exception:
        sys.exit(0)  # scanner error — fail open (don't break agent)

    if envelope.verdict == ScanVerdict.ACCEPT:
        sys.exit(0)

    if envelope.verdict == ScanVerdict.VERIFY:
        # Prepend warning — result still shown to LLM
        print(json.dumps({
            "decision": "inject_content",
            "content":  envelope.sanitized_result or result_text,
            "remora_scan": envelope.to_dict(),
        }))
        sys.exit(0)

    # ESCALATE — block result entirely
    print(json.dumps({
        "decision": "block",
        "reason":   (
            f"REMORA ESCALATE: injection attack detected in {tool_name} result. "
            f"Signals: {', '.join(s.pattern_name for s in envelope.injection_signals)}. "
            f"Result hash {envelope.result_hash[:16]}… quarantined. Human review required."
        ),
        "remora_scan": envelope.to_dict(),
    }))
    sys.exit(2)  # non-zero to signal block to Claude Code


if __name__ == "__main__":
    main()
