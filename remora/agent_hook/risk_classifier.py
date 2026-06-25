# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic risk classification for agent tool calls.

The classifier is intentionally conservative and dependency-free. It does not
execute tools or inspect live systems. It only labels the proposed call so the
runtime hook can decide whether to allow it locally, ask REMORA for verification,
or block a clearly destructive action before execution.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Any

from remora.agent_hook.shell_ast import DestructiveIntent, has_destructive_intent


class RiskLevel(str, Enum):
    """Coarse risk levels for proposed agent tool calls."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class ToolRiskAssessment:
    """Structured risk assessment for a proposed tool call."""

    risk: RiskLevel
    reason: str
    category: str
    local_block: bool = False


_LOCAL_BLOCK_BASH = [
    r"\brm\s+-[^\n]*[rf][^\n]*\s+(/|~|\.{1,2}|[A-Za-z]:\\)",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bformat\b",
    r">\s*/dev/",
    r"\bcurl\b.*\|\s*(sh|bash|powershell|pwsh)",
    r"\bwget\b.*\|\s*(sh|bash|powershell|pwsh)",
    r"\bbase64\b[^\n|]*(?:-d|--decode)[^\n|]*\|\s*(sh|bash|powershell|pwsh)",
    r"\bpoweroff\b|\breboot\b|\bshutdown\b",
    r"\bgit\s+push\b(?=.*(\s--force\b|\s-f\b))(?!.*--force-with-lease)",
    r"\bgit\s+reset\s+--hard\b",
    r"\bdrop\s+table\b",
    r"\btruncate\s+table\b",
    r"\bnpx\s+wrangler\s+secret\b",
    r"\bnpx\s+wrangler\s+delete\b",
]

_HIGH_BASH = [
    *_LOCAL_BLOCK_BASH,
    r"\bsudo\b",
    r"\bchmod\s+[0-7]*7[0-7][0-7]\b",
    r"\b(SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY)\s*=\s*['\"]?[A-Za-z0-9/+_-]{8,}",
    r"\b(python3?|node|ruby|perl|php)\b[^\n]*\s+-(c|e)\s",
]

_MEDIUM_BASH = [
    r"\bgit\s+push\b",
    r"\bgit\s+commit\b",
    r"\bgit\s+checkout\b",
    r"\bgh\b",
    r"\bnpm\s+publish\b",
    r"\bnpx\s+wrangler\s+deploy\b",
    r"\bnpx\s+wrangler\s+publish\b",
    r"\bpip\s+install\b",
    r"\bapt\s+install\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bpython\b.*\bscripts\b",
    r"\bwrangler\b",
]

_OBFUSCATION_PATTERNS = [
    r"\beval\b",
    r"\bbase64\b.*(?:-d|--decode)",
    r"echo\s+\S+\s*\|\s*(?:sh|bash)",
    r"printf\s+.*\|\s*(?:sh|bash)",
    r"\$\([^)]*(?:sh|bash|eval)[^)]*\)",
    r"`[^`]*(?:sh|bash|eval)[^`]*`",
]

_CRITICAL_TOKENS = frozenset(
    [
        "rm",
        "dd",
        "mkfs",
        "format",
        "poweroff",
        "reboot",
        "shutdown",
        "drop",
        "truncate",
    ]
)

_VAR_EXPANSION_RE = re.compile(r"\$[{(]?[A-Za-z_][A-Za-z0-9_]*")

_HIGH_FILE_PATTERNS = [
    r"\.env$",
    r"settings\.json$",
    r"wrangler\.toml$",
    r"secrets?\.",
    r"claude_desktop_config",
    r"\.gitconfig$",
    r"authorized_keys",
    r"id_rsa",
    r"id_ed25519",
]

_MEDIUM_FILE_PATTERNS = [
    r"\.py$",
    r"\.ts$",
    r"\.js$",
    r"\.toml$",
    r"\.yaml$",
    r"\.yml$",
    r"src/",
    r"workers/",
    r"servers/",
    r"scripts/",
]


def _tokenize_bash(command: str) -> list[str]:
    """Return a best-effort token list from a shell command string."""

    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _contains_obfuscation(command: str) -> bool:
    """Return True if the command contains known obfuscation patterns."""

    return any(re.search(pattern, command, re.IGNORECASE) for pattern in _OBFUSCATION_PATTERNS)


def _has_indirect_critical(command: str) -> bool:
    """Return True when variable expansion wraps a critical command token."""

    if not _VAR_EXPANSION_RE.search(command):
        return False
    tokens = {token.strip("'\";") for token in _tokenize_bash(command)}
    return bool(tokens & _CRITICAL_TOKENS)


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _shell_obfuscation_view(command: str) -> str:
    """Return a conservative view that catches simple shell token splitting.

    This does not execute or decode commands. It only removes common
    quote/backslash separators so patterns such as `r''m -r''f /tmp/x` are
    treated like `rm -rf /tmp/x`.
    """

    dequoted = re.sub(r"[`'\"]+", "", command)
    deescaped = dequoted.replace("\\", "")
    return re.sub(r"\s+", " ", deescaped)


def assess_tool_call(tool_name: str, tool_input: dict[str, Any]) -> ToolRiskAssessment:
    """Return a structured risk assessment for an agent tool call."""

    name = tool_name.lower()

    if name == "bash":
        command = str(tool_input.get("command", ""))
        normalized_command = _shell_obfuscation_view(command)

        # AST-based intent analysis (primary, obfuscation-resistant)
        ast_destructive, ast_intents = has_destructive_intent(command)
        _BLOCK_INTENTS = {
            DestructiveIntent.DELETE_RECURSIVE,
            DestructiveIntent.DISK_WIPE,
            DestructiveIntent.PIPE_EXECUTE,
            DestructiveIntent.FORCE_PUSH,
            DestructiveIntent.HARD_RESET,
            DestructiveIntent.SQL_DROP,
            DestructiveIntent.POWER_CYCLE,
            DestructiveIntent.SECRET_EXPOSURE,
            DestructiveIntent.SUBSHELL_DECODE,
        }
        blocking_intents = [i for i in ast_intents if i in _BLOCK_INTENTS]
        if blocking_intents:
            return ToolRiskAssessment(
                risk=RiskLevel.HIGH,
                reason=f"AST-classified destructive intent: {', '.join(i.value for i in blocking_intents)}",
                category="shell_destructive",
                local_block=True,
            )

        # Obfuscation fallback (regex, catches what AST tokenizer misses).
        # Skip obfuscation scan for a narrow set of CLI invocations that
        # legitimately embed heredocs or structured text in their arguments.
        # The exemption is tightened to specific subcommands (not all `gh`
        # invocations) and is revoked if shell-chaining operators (`;`, `&&`,
        # `||`) appear anywhere in the command — these could inject a second
        # payload after the trusted prefix.
        #   - `git commit -m` — commit message body (heredoc $(...) is not shell exec)
        #   - `gh pr/issue/release/... create|edit|...` — PR/issue body text
        # Pipe (`|`) and backticks are not exempted; the AST check above handles
        # PIPE_EXECUTE and SUBSHELL_DECODE intents before we reach this point.
        # Trusted-CLI exemption: a narrow set of CLI invocations whose arguments
        # legitimately contain heredocs or structured text.
        #
        # For `gh` subcommands: block immediately when shell-chaining or
        # shell-level metacharacters appear (`;`, `&&`, `||`, single `|`, backtick).
        # Legitimate heredoc usage — `gh pr create --body "$(cat <<'EOF'…EOF)"` —
        # contains no top-level pipe; PR body text with `|` must use --body-file.
        _gh_match = re.match(
            r"\s*gh\s+(pr|issue|release|repo|run|api|workflow|auth|gist)\s+",
            command,
        )
        if _gh_match and re.search(r";|&&|\|\||\|(?!\|)|`", command):
            return ToolRiskAssessment(
                risk=RiskLevel.HIGH,
                reason="gh command contains shell metacharacters (;, &&, ||, |, `) — potential injection",
                category="shell_gh_injection",
                local_block=True,
            )
        is_trusted_cli = bool(
            re.match(r"\s*git\s+commit\b", command) or bool(_gh_match)
        )
        if not is_trusted_cli and (_contains_obfuscation(command) or _has_indirect_critical(command)):
            return ToolRiskAssessment(
                risk=RiskLevel.HIGH,
                reason="obfuscated or indirect command; cannot classify safely by pattern matching",
                category="shell_obfuscated",
                local_block=True,
            )
        if _match_any(command, _LOCAL_BLOCK_BASH) or _match_any(normalized_command, _LOCAL_BLOCK_BASH):
            return ToolRiskAssessment(
                risk=RiskLevel.HIGH,
                reason="locally blocked destructive or production-sensitive command",
                category="shell_destructive",
                local_block=True,
            )
        if _match_any(command, _HIGH_BASH) or _match_any(normalized_command, _HIGH_BASH):
            return ToolRiskAssessment(
                risk=RiskLevel.HIGH,
                reason="sensitive shell command",
                category="shell_sensitive",
            )
        if _match_any(command, _MEDIUM_BASH) or _match_any(normalized_command, _MEDIUM_BASH):
            return ToolRiskAssessment(
                risk=RiskLevel.MEDIUM,
                reason="network, git, deployment, or package operation",
                category="shell_operational",
            )
        return ToolRiskAssessment(
            risk=RiskLevel.LOW,
            reason="read-only or local computation",
            category="shell_readonly",
        )

    if name in {"edit", "write"}:
        path = str(tool_input.get("file_path", ""))
        normalized_path = path.replace("\\", "/")
        if _match_any(normalized_path, _HIGH_FILE_PATTERNS):
            return ToolRiskAssessment(
                risk=RiskLevel.HIGH,
                reason=f"sensitive file: {path}",
                category="file_sensitive",
            )
        if _match_any(normalized_path, _MEDIUM_FILE_PATTERNS):
            return ToolRiskAssessment(
                risk=RiskLevel.MEDIUM,
                reason=f"source or configuration file: {path}",
                category="file_source",
            )
        return ToolRiskAssessment(
            risk=RiskLevel.LOW,
            reason="non-sensitive file operation",
            category="file_low_risk",
        )

    if name in {"read", "glob", "grep", "ls"}:
        return ToolRiskAssessment(
            risk=RiskLevel.LOW,
            reason="read-only operation",
            category="read_only",
        )

    if name == "webfetch":
        url = str(tool_input.get("url", ""))
        # Calls to REMORA's own Cloudflare infrastructure are trusted — fast-path allow.
        # Parse the hostname properly; substring checks on the raw URL can be bypassed
        # via userinfo, path, or query smuggling (e.g. evil.com/?x=razorsharp.workers.dev).
        try:
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(url)
            _host = (_parsed.hostname or "").lower().rstrip(".")
            _trusted = (
                _parsed.scheme in ("http", "https")
                and (
                    _host == "razorsharp.workers.dev"
                    or _host.endswith(".razorsharp.workers.dev")
                )
            )
        except Exception:
            _trusted = False
        if _trusted:
            return ToolRiskAssessment(
                risk=RiskLevel.LOW,
                reason="fetch from trusted REMORA infrastructure",
                category="network_trusted",
            )
        return ToolRiskAssessment(
            risk=RiskLevel.MEDIUM,
            reason="external network lookup",
            category="network_lookup",
        )

    if name == "websearch":
        return ToolRiskAssessment(
            risk=RiskLevel.MEDIUM,
            reason="external network lookup",
            category="network_lookup",
        )

    if name == "agent":
        return ToolRiskAssessment(
            risk=RiskLevel.HIGH,
            reason="spawns autonomous sub-agent",
            category="agent_delegation",
        )

    return ToolRiskAssessment(
        risk=RiskLevel.MEDIUM,
        reason=f"unknown tool '{tool_name}'",
        category="unknown_tool",
    )


def classify_tool_call(tool_name: str, tool_input: dict[str, Any]) -> tuple[RiskLevel, str]:
    """Backward-compatible tuple form used by lightweight integrations."""

    assessment = assess_tool_call(tool_name, tool_input)
    return assessment.risk, assessment.reason

