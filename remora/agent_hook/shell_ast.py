"""Lightweight shell intent AST — robust against obfuscation.

Problem with regex
------------------
Regex matches text patterns, so `r''m -rf /` passes a check for `rm -rf`
because the quotes break the literal string.  shlex.split() removes the quotes
first: `shlex.split("r''m -rf /")` → `["rm", "-rf", "/"]`.  Regex never sees
the de-quoted token.

This module parses shell commands into a minimal semantic AST using stdlib-only
tools (shlex, re) and classifies destructive intent from the AST structure —
not from text patterns.

Attack vectors addressed
------------------------
1. Quote-splitting:      r''m -rf /         → rm -rf /      (shlex handles)
2. Variable assignment:  CMD=rm; $CMD -rf / → rm -rf /      (assignment tracker)
3. Base64 pipe:          echo ... | base64 -d | bash        → sub-shell (existing)
4. Concatenation:        PROG=r; PROG+=m; $PROG -rf /       → rm -rf /  (concat tracker)
5. Arithmetic:           :; rm -rf /        → skip no-op, find rm  (skip list)
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum


class DestructiveIntent(str, Enum):
    """Classified destructive intents, independent of how the command is written."""
    DELETE_RECURSIVE   = "delete_recursive"        # rm -r / rm -rf
    DISK_WIPE          = "disk_wipe"               # dd, mkfs, format
    PIPE_EXECUTE       = "pipe_execute"            # ... | bash / | sh
    FORCE_PUSH         = "force_push"              # git push --force
    HARD_RESET         = "hard_reset"              # git reset --hard
    SQL_DROP           = "sql_drop"                # DROP TABLE / TRUNCATE TABLE
    POWER_CYCLE        = "power_cycle"             # poweroff / reboot / shutdown
    SECRET_EXPOSURE    = "secret_exposure"         # wrangler secret / env SECRET=
    SUBSHELL_DECODE    = "subshell_decode"         # eval $(base64 -d ...) patterns
    UNKNOWN_SUBSHELL   = "unknown_subshell"        # $(...) or `...` expanding to exec


@dataclass
class ShellCommandNode:
    """Minimal semantic representation of a parsed shell command."""
    program: str                           # resolved program name (after var subst)
    args: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)  # flags normalised (no leading -)
    redirects: list[str] = field(default_factory=list)
    redirect_targets: list[str] = field(default_factory=list)  # paths/devices redirected to
    pipe_targets: list[str] = field(default_factory=list)  # programs piped into
    raw_tokens: list[str] = field(default_factory=list)
    piped_input: bool = False              # True when this command receives piped input


# ---------------------------------------------------------------------------
# Dangerous command lookup tables (program + required flag or sub-command)
# ---------------------------------------------------------------------------

_DELETE_PROGRAMS = frozenset(["rm", "del", "rmdir", "erase", "deltree", "unlink"])
_DELETE_RECURSIVE_FLAGS = frozenset(["r", "R", "rf", "fr", "rF", "fR"])  # after normalising
_DISK_PROGRAMS = frozenset(["dd", "mkfs", "mkfs.ext4", "mkfs.ntfs", "format", "diskpart", "shred"])
_POWER_PROGRAMS = frozenset(["poweroff", "reboot", "shutdown", "halt", "init"])
_EXEC_SHELLS = frozenset(["sh", "bash", "zsh", "ksh", "dash", "fish", "pwsh", "powershell", "cmd"])
_SECRET_SUBCOMMANDS = frozenset(["secret"])  # wrangler secret put
_FORCE_FLAGS = frozenset(["force", "f"])

_SQL_DROP_RE = re.compile(
    r"\b(drop\s+table|truncate\s+table|drop\s+database|drop\s+schema)\b",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Variable assignment tracker
# ---------------------------------------------------------------------------

class _VarTracker:
    """Tracks simple shell variable assignments and resolves $VAR references."""

    def __init__(self) -> None:
        self._vars: dict[str, str] = {}

    def record_assignment(self, token: str) -> bool:
        """If token looks like VAR=value or VAR+=value, record it and return True."""
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(\+?)=(.*)$", token)
        if not m:
            return False
        name, op, value = m.group(1), m.group(2), m.group(3).strip("\"'")
        if op == "+":
            self._vars[name] = self._vars.get(name, "") + value
        else:
            self._vars[name] = value
        return True

    def resolve(self, token: str) -> str:
        """Substitute $VAR and ${VAR} references with recorded values."""
        def _sub(m: re.Match) -> str:  # type: ignore[type-arg]
            return self._vars.get(m.group(1) or m.group(2), m.group(0))
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", _sub, token)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_NOOPS = frozenset([":", "true", "false", "echo", "printf", "test", "[", "[["])


def parse_shell_commands(command: str) -> list[ShellCommandNode]:
    """Parse a shell command string into a list of ShellCommandNodes.

    Uses shlex.split() for tokenization (handles quotes/escapes correctly)
    then builds semantic nodes while tracking variable assignments.

    Security guarantee: the token list seen here is the de-quoted form that
    the shell itself would see — quote tricks like r''m are resolved before
    destructive-intent matching runs.
    """
    # Split on statement separators while preserving pipes
    # Strategy: replace ; and && and || with newlines, then process line by line
    normalized = re.sub(r"(;|&&|\|\||\n)", "\n", command)
    # Mark single-pipe boundaries (not ||) so downstream shells are detectable
    normalized = re.sub(r"(?<!\|)\|(?!\|)", "\n\x00PIPE\x00\n", normalized)
    segments = [s.strip() for s in normalized.split("\n") if s.strip()]

    nodes: list[ShellCommandNode] = []
    tracker = _VarTracker()
    piped_from_prev = False

    for segment in segments:
        if segment == "\x00PIPE\x00":
            piped_from_prev = True
            continue

        # Tokenize — shlex.split resolves quoting and backslash escapes
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        if not tokens:
            continue

        # Resolve any variable references using tracker state
        tokens = [tracker.resolve(t) for t in tokens]

        # Skip tokens that are pure assignments (record them instead)
        program_tokens = [t for t in tokens if not tracker.record_assignment(t)]
        if not program_tokens:
            continue

        program = program_tokens[0].split("/")[-1].lstrip(".")  # strip path prefixes
        # Remove exec/env/sudo wrappers to find real program
        while program in {"sudo", "env", "exec", "nice", "nohup", "time", "xargs"}:
            program_tokens = program_tokens[1:]
            if not program_tokens:
                break
            program = program_tokens[0].split("/")[-1].lstrip(".")

        if not program_tokens:
            continue

        args = program_tokens[1:]
        flags: set[str] = set()
        pipe_targets: list[str] = []
        redirects: list[str] = []

        in_pipe = False
        in_redirect = False
        redirect_targets: list[str] = []
        for arg in args:
            if arg == "|":
                in_pipe = True
                in_redirect = False
                continue
            if arg in {">", ">>", "<", "2>", "2>>"}:
                redirects.append(arg)
                in_redirect = True
                in_pipe = False
                continue
            if in_redirect:
                redirect_targets.append(arg)
                in_redirect = False
                continue
            if in_pipe:
                pipe_targets.append(arg.lstrip("./"))
                in_pipe = False
                continue
            # Pipe target embedded in token: "cmd | bash" was already split by shlex
            if arg.startswith("-"):
                # Expand combined flags: "-rf" → {"r", "f"}
                flag_str = arg.lstrip("-")
                if len(flag_str) > 1 and not arg.startswith("--"):
                    flags.update(flag_str)
                else:
                    flags.add(flag_str.lstrip("-"))

        # Also check for inline pipes not caught above (|bash patterns)
        full_segment = " ".join(tokens)
        pipe_re = re.finditer(r"\|\s*([a-zA-Z_][a-zA-Z0-9_/.-]*)", full_segment)
        for m in pipe_re:
            target = m.group(1).lstrip("./").split("/")[-1]
            if target not in pipe_targets:
                pipe_targets.append(target)

        if program not in _NOOPS:
            nodes.append(
                ShellCommandNode(
                    program=program,
                    args=args,
                    flags=flags,
                    redirects=redirects,
                    redirect_targets=redirect_targets,
                    pipe_targets=pipe_targets,
                    raw_tokens=tokens,
                    piped_input=piped_from_prev,
                )
            )
        piped_from_prev = False

    return nodes


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

def classify_destructive_intents(nodes: list[ShellCommandNode]) -> list[DestructiveIntent]:
    """Return the list of destructive intents found in the command AST."""
    intents: list[DestructiveIntent] = []
    full_raw = " ".join(" ".join(n.raw_tokens) for n in nodes)

    for node in nodes:
        prog = node.program.lower()
        flags = {f.lower() for f in node.flags}

        # DELETE_RECURSIVE: rm/del with recursive flag
        if prog in _DELETE_PROGRAMS:
            if flags & _DELETE_RECURSIVE_FLAGS or "recursive" in flags:
                intents.append(DestructiveIntent.DELETE_RECURSIVE)
            elif not flags and any(a in {"/", "~", "."} for a in node.args[:3]):
                # rm / or rm ~ with no flags but targeting root-like paths
                intents.append(DestructiveIntent.DELETE_RECURSIVE)

        # DISK_WIPE
        if prog in _DISK_PROGRAMS:
            intents.append(DestructiveIntent.DISK_WIPE)

        # POWER_CYCLE
        if prog in _POWER_PROGRAMS:
            intents.append(DestructiveIntent.POWER_CYCLE)

        # PIPE_EXECUTE: anything piped to a shell
        if any(t in _EXEC_SHELLS for t in node.pipe_targets):
            intents.append(DestructiveIntent.PIPE_EXECUTE)

        # Shell receiving piped input = PIPE_EXECUTE
        if getattr(node, "piped_input", False) and node.program.lower() in _EXEC_SHELLS:
            intents.append(DestructiveIntent.PIPE_EXECUTE)

        # Device-write redirect
        redirect_targets = getattr(node, "redirect_targets", [])
        if any(str(t).startswith("/dev/") for t in redirect_targets):
            intents.append(DestructiveIntent.DISK_WIPE)

        # FORCE_PUSH
        if prog == "git" and node.args and node.args[0] == "push" and (
            flags & _FORCE_FLAGS or "--force" in node.args or "-f" in node.args
        ):
            intents.append(DestructiveIntent.FORCE_PUSH)

        # HARD_RESET
        if prog == "git" and node.args and node.args[0] == "reset" and (
            "hard" in flags or "--hard" in node.args
        ):
            intents.append(DestructiveIntent.HARD_RESET)

        # SECRET_EXPOSURE
        if prog in {"wrangler", "npx"} and any(
            a in _SECRET_SUBCOMMANDS for a in node.args
        ):
            intents.append(DestructiveIntent.SECRET_EXPOSURE)

        # SQL_DROP (within bash -c "..." or similar)
        for arg in node.args:
            if _SQL_DROP_RE.search(arg):
                intents.append(DestructiveIntent.SQL_DROP)

        # SUBSHELL_DECODE: eval with base64/decode
        if prog in {"eval", "exec"} and any("base64" in a or "decode" in a for a in node.args):
            intents.append(DestructiveIntent.SUBSHELL_DECODE)

    # Check full raw text for SQL patterns not caught in per-node args
    if _SQL_DROP_RE.search(full_raw) and DestructiveIntent.SQL_DROP not in intents:
        intents.append(DestructiveIntent.SQL_DROP)

    return intents


def has_destructive_intent(command: str) -> tuple[bool, list[DestructiveIntent]]:
    """Top-level API: parse command and return (is_destructive, intents)."""
    nodes = parse_shell_commands(command)
    intents = classify_destructive_intents(nodes)
    return bool(intents), intents
