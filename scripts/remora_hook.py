#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA pre-tool-use hook for governed agent runtimes.

The script reads a hook payload from stdin and exits with:
  0: allow the proposed tool call
  2: block the proposed tool call

It is designed as an opt-in local runtime guard. It never executes the proposed
tool itself. Locally destructive patterns are blocked deterministically. For
medium/high-risk actions that are not locally blocked, the hook can optionally
call the REMORA agent-control service when AGENT_CONTROL_SECRET is configured.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from remora.agent_hook.intent_anchor import IntentAnchor
from remora.agent_hook.lyapunov_tracker import LyapunovTracker
from remora.agent_hook.risk_classifier import RiskLevel, assess_tool_call

AGENT_CONTROL_URL = os.environ.get(
    "AGENT_CONTROL_URL",
    "https://remora-agent-control.razorsharp.workers.dev",
)
MEDIUM_BLOCK_THRESHOLD = float(os.environ.get("REMORA_HOOK_MEDIUM_BLOCK_THRESHOLD", "0.35"))
DRIFT_WARN_THRESHOLD = float(os.environ.get("REMORA_HOOK_DRIFT_WARN_THRESHOLD", "0.75"))
DRIFT_BLOCK_THRESHOLD = float(os.environ.get("REMORA_HOOK_DRIFT_BLOCK_THRESHOLD", "0.92"))
# Fail-closed for HIGH-risk by default — set REMORA_HOOK_REQUIRE_REMOTE=0 to opt out
REQUIRE_REMOTE_FOR_HIGH = os.environ.get("REMORA_HOOK_REQUIRE_REMOTE", "1") != "0"


def _load_secret() -> str:
    """Load the optional agent-control bearer token from env or local config."""

    if os.environ.get("AGENT_CONTROL_SECRET"):
        return os.environ["AGENT_CONTROL_SECRET"]

    config_paths = [
        os.path.expandvars(r"%APPDATA%\Claude\claude_desktop_config.json"),
        os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json"),
        os.path.expanduser("~/.config/claude/claude_desktop_config.json"),
        os.path.join(_REPO, ".remora_session", "hook_config.json"),
    ]
    for config_path in config_paths:
        try:
            with open(config_path, encoding="utf-8") as handle:
                config = json.load(handle)
            secret = (
                config.get("mcpServers", {})
                .get("remora", {})
                .get("env", {})
                .get("AGENT_CONTROL_SECRET", "")
            )
            if not secret and "AGENT_CONTROL_SECRET" in config:
                secret = str(config.get("AGENT_CONTROL_SECRET", ""))
            if secret:
                return secret
        except (OSError, json.JSONDecodeError):
            continue
    return ""


AGENT_CONTROL_SECRET = _load_secret()


def _ensure_session(session_id: str) -> str:
    """Return a REMORA agent-control session id, creating one when possible."""

    if session_id and len(session_id) > 10:
        return session_id
    if not AGENT_CONTROL_SECRET:
        return ""

    payload = json.dumps({"user_label": "agent-tool-hook"}).encode()
    request = urllib.request.Request(
        AGENT_CONTROL_URL + "/sessions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AGENT_CONTROL_SECRET}",
            "User-Agent": "REMORA-hook/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=15) as response:
            data = json.loads(response.read())
            return str(data.get("session_id", ""))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return ""


def remora_verify(claim: str, context: str, session_id: str) -> dict[str, Any]:
    """Verify a tool-call claim through agent-control when configured."""

    if not AGENT_CONTROL_SECRET:
        return {"error": "AGENT_CONTROL_SECRET not configured"}

    payload = json.dumps(
        {
            "tool": "remora_verify_claim",
            "input": {"claim": claim, "context": context},
            "session_id": _ensure_session(session_id),
        }
    ).encode()
    request = urllib.request.Request(
        AGENT_CONTROL_URL + "/execute",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AGENT_CONTROL_SECRET}",
            "User-Agent": "REMORA-hook/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}", "detail": exc.read().decode(errors="replace")[:200]}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def build_claim(tool_name: str, tool_input: dict[str, Any]) -> tuple[str, str]:
    """Return a claim/context pair describing the proposed tool call."""

    name = tool_name.lower()
    if name == "bash":
        command = str(tool_input.get("command", ""))[:300]
        return (
            f"Executing this shell command is safe and aligned with the session goal: {command}",
            f"An agent is about to run a shell command. Command: {command}",
        )

    if name in {"edit", "write"}:
        path = str(tool_input.get("file_path", ""))
        preview = str(tool_input.get("new_string", tool_input.get("content", "")))[:200]
        return (
            f"Modifying file '{path}' is safe, reversible, and aligned with the session goal.",
            f"An agent wants to write to file: {path}. Content preview: {preview}",
        )

    if name in {"webfetch", "websearch"}:
        target = str(tool_input.get("url", tool_input.get("query", "")))[:200]
        return (
            f"Fetching external resource '{target}' is appropriate for the session goal.",
            f"An agent wants to fetch: {target}",
        )

    if name == "agent":
        description = str(tool_input.get("description", ""))[:200]
        prompt = str(tool_input.get("prompt", ""))[:200]
        return (
            f"Spawning a sub-agent for task '{description}' is safe and aligned with the session goal.",
            f"An agent wants to spawn a sub-agent. Description: {description}. Prompt: {prompt}",
        )

    return (
        f"Executing tool '{tool_name}' is safe and aligned with the session goal.",
        f"An agent is about to call tool '{tool_name}' with input: {str(tool_input)[:200]}",
    )


def _extract_verdict(result: dict[str, Any]) -> tuple[str, float, str, str]:
    output = result.get("output", {})
    verdict = str(output.get("verdict", result.get("verdict", "UNKNOWN")))
    confidence = float(result.get("confidence", output.get("confidence", 0.5)))
    detail = str(output.get("detail", result.get("detail", "")))
    audit_id = str(result.get("audit_id", ""))
    return verdict, confidence, detail, audit_id


def _print_block(title: str, lines: list[str]) -> None:
    print("[REMORA] BLOCKED - " + title, file=sys.stderr)
    for line in lines:
        print("  " + line, file=sys.stderr)


def _read_payload() -> dict[str, Any] | None:
    try:
        # Try buffer first for proper BOM handling; fall back to text mode
        try:
            raw = sys.stdin.buffer.read().decode("utf-8-sig").strip()
        except Exception:
            raw = sys.stdin.read().strip()
        if not raw:
            return None
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        # Malformed hook input — log and fail open to avoid blocking agent.
        # Do NOT silently swallow; this could mask a hook integration bug.
        print(f"[REMORA] WARNING: could not parse hook input ({type(exc).__name__}: {exc}). Allowing action.", file=sys.stderr)
        sys.exit(0)


def main() -> None:
    payload = _read_payload()
    if not payload:
        sys.exit(0)

    tool_name = str(payload.get("tool_name", payload.get("tool", "")))
    tool_input = payload.get("tool_input", payload.get("input", {}))
    session_id = str(payload.get("session_id", ""))
    if not tool_name or not isinstance(tool_input, dict):
        sys.exit(0)

    assessment = assess_tool_call(tool_name, tool_input)
    tracker = LyapunovTracker()

    if assessment.local_block:
        tracker.record(tool_name, "BLOCKED", 0.99, drift_score=0.0)
        _print_block(
            "local deterministic safety rule",
            [
                f"Tool: {tool_name}",
                f"Risk: {assessment.risk.value} ({assessment.category})",
                f"Reason: {assessment.reason}",
                "This pattern is blocked before any remote verifier is consulted.",
            ],
        )
        sys.exit(2)

    if assessment.risk == RiskLevel.LOW:
        tracker.record(tool_name, "VERIFIED", 0.95, drift_score=0.0)
        sys.exit(0)

    anchor = IntentAnchor()
    drift = 0.0
    if anchor.anchored:
        action_description = f"{tool_name} {str(tool_input)[:200]}"
        drift = anchor.drift_score(action_description)
        anchor.record_tool_call()
        if drift >= DRIFT_BLOCK_THRESHOLD:
            tracker.record(tool_name, "BLOCKED", 0.90, drift_score=drift)
            _print_block(
                f"semantic drift from session intent: {drift:.0%}",
                [
                    f"Anchored intent: {anchor.intent[:120]}",
                    f"Current action: {action_description[:120]}",
                    "Re-anchor the session if this new direction is intentional.",
                ],
            )
            sys.exit(2)

    claim, context = build_claim(tool_name, tool_input)
    result = remora_verify(claim, context, session_id)

    if "error" in result:
        if assessment.risk == RiskLevel.HIGH and REQUIRE_REMOTE_FOR_HIGH:
            tracker.record(tool_name, "ABSTAIN", 0.25, drift_score=drift)
            _print_block(
                "remote verification required but unavailable",
                [
                    f"Tool: {tool_name}",
                    f"Risk: {assessment.risk.value} ({assessment.reason})",
                    f"Error: {str(result.get('error', 'unknown'))[:140]}",
                    "Set AGENT_CONTROL_SECRET or lower the risk of the proposed action.",
                ],
            )
            sys.exit(2)

        tracker.record(tool_name, "VERIFIED", 0.60, drift_score=drift)
        if drift >= DRIFT_WARN_THRESHOLD:
            print(f"[REMORA] WARNING - drift {drift:.0%} from session intent")
        sys.exit(0)

    verdict, confidence, detail, audit_id = _extract_verdict(result)
    lyapunov_abort, lyapunov_reason = tracker.record(
        tool_name,
        verdict,
        confidence,
        drift_score=drift,
    )

    is_bad_verdict = verdict in {"CONTRADICTED", "SUSPICIOUS"}
    is_low_confidence = confidence < MEDIUM_BLOCK_THRESHOLD

    if is_bad_verdict and (assessment.risk == RiskLevel.HIGH or is_low_confidence):
        latest_v = tracker.latest_V()
        lines = [
            f"Tool: {tool_name}",
            f"Verdict: {verdict} ({confidence:.0%} confidence)",
            f"Risk: {assessment.risk.value} ({assessment.reason})",
            f"Drift: {drift:.0%} from session intent",
        ]
        if detail:
            lines.append(f"Detail: {detail[:140]}")
        if latest_v is not None:
            lines.append(f"V(t): {latest_v:.4f}")
        if audit_id:
            lines.append(f"Audit: #{audit_id}")
        _print_block("tool call rejected by consensus", lines)
        sys.exit(2)

    if lyapunov_abort and is_bad_verdict:
        latest_v = tracker.latest_V()
        lines = [
            f"Tool: {tool_name}",
            f"Verdict: {verdict} ({confidence:.0%})",
            f"Lyapunov reason: {lyapunov_reason}",
        ]
        if latest_v is not None:
            lines.append(f"V(t): {latest_v:.4f}")
        lines.append("The local tool-call trajectory is becoming less stable.")
        _print_block("Lyapunov stability divergence detected", lines)
        sys.exit(2)

    if drift >= DRIFT_WARN_THRESHOLD:
        print(f"[REMORA] WARNING - drift {drift:.0%} from session intent")

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Unexpected error — fail open for LOW/MEDIUM, maintain hook operation
        # HIGH-risk fail-closed behaviour is handled in the main flow above
        sys.exit(0)

