"""AST-based command validation using bashlex (shell) and sqlglot (SQL).

Attempts to import bashlex and sqlglot at module load time.  Falls back to
the heuristic ``shell_ast`` classifier when either library is absent (the
common case for lightweight REMORA deployments — neither is a hard dependency).

``parse_and_validate(command)`` is the single public entry point:
    True  → command appears safe.
    False → forbidden AST node or destructive intent detected.
"""
from __future__ import annotations

from typing import Any

# ── optional AST libraries ────────────────────────────────────────────────────

try:
    import bashlex as _bashlex
    _BASHLEX_AVAILABLE = True
except ImportError:
    _bashlex = None  # type: ignore[assignment]
    _BASHLEX_AVAILABLE = False

try:
    import sqlglot as _sqlglot
    _SQLGLOT_AVAILABLE = True
except ImportError:
    _sqlglot = None  # type: ignore[assignment]
    _SQLGLOT_AVAILABLE = False

import re as _re

from remora.agent_hook.shell_ast import has_destructive_intent as _hdi


# -- supplemental heuristics (run regardless of bashlex availability) ---------

_SUPPLEMENT_PATTERNS = [
    # rm with -f flag alone (force-delete; -rf caught by shell_ast)
    _re.compile(r"\brm\s+[^|;&\n]*-[a-zA-Z]*f", _re.IGNORECASE),
    # sudo or su at the start of a command
    _re.compile(r"^\s*(sudo|su)\s", _re.IGNORECASE),
    # sudo/su after a semicolon
    _re.compile(r";\s*(sudo|su)\s"),
]


def _supplemental_heuristics(command):
    for pattern in _SUPPLEMENT_PATTERNS:
        if pattern.search(command):
            return True
    return False



# ── bashlex validation ────────────────────────────────────────────────────────

# Programs whose presence (with any flag) is suspicious enough to block.
_BLOCK_ALWAYS = frozenset({"sudo", "su", "pkexec"})

# Programs that are only blocked when combined with specific destructive flags.
_DESTRUCTIVE_FLAGS: dict[str, frozenset[str]] = {
    "rm":     frozenset({"-r", "-f", "-rf", "-fr", "--force", "--recursive"}),
    "rmdir":  frozenset({"--ignore-fail-on-non-empty"}),
    "git":    frozenset({"--force", "-f", "--hard", "--delete", "-D"}),
    "dd":     frozenset({"of=/dev/sd", "of=/dev/hd", "of=/dev/nvme", "if=/dev/zero"}),
    "chmod":  frozenset({"777", "a+x", "+x"}),
    "shred":  frozenset({"-u", "--remove", "-n"}),
}

# Shell interpreters that are dangerous on the receiving end of a pipe.
_PIPE_SHELLS = frozenset({"sh", "bash", "zsh", "fish", "python", "python3", "perl", "ruby"})


def _node_program(node: Any) -> str:
    """Extract the bare program name from a bashlex command node."""
    parts = getattr(node, "parts", [])
    for part in parts:
        if getattr(part, "kind", "") == "word":
            word = getattr(part, "word", "")
            return word.split("/")[-1].lstrip(".")
    return ""


def _node_words(node: Any) -> list[str]:
    """Return all word tokens from a bashlex command node."""
    return [
        getattr(p, "word", "")
        for p in getattr(node, "parts", [])
        if getattr(p, "kind", "") == "word"
    ]


def _check_bashlex_node(node: Any) -> bool:
    """Return False if *node* or any descendant contains a forbidden pattern."""
    kind = getattr(node, "kind", "")

    if kind == "command":
        program = _node_program(node)
        if program in _BLOCK_ALWAYS:
            return False
        required_flags = _DESTRUCTIVE_FLAGS.get(program)
        if required_flags is not None:
            words = _node_words(node)[1:]  # skip program itself
            for word in words:
                if word in required_flags or any(word.startswith(f) for f in required_flags):
                    return False

    elif kind == "pipeline":
        # Pipe-to-shell: last command is a bare interpreter
        parts = getattr(node, "parts", [])
        for i, part in enumerate(parts):
            if i > 0 and getattr(part, "kind", "") == "command":
                prog = _node_program(part)
                if prog in _PIPE_SHELLS:
                    return False

    # Recurse into child collections
    for attr in ("parts", "list"):
        children = getattr(node, attr, None)
        if isinstance(children, list):
            for child in children:
                if hasattr(child, "kind") and not _check_bashlex_node(child):
                    return False
    for attr in ("command",):
        child = getattr(node, attr, None)
        if hasattr(child, "kind") and not _check_bashlex_node(child):
            return False

    return True


def _validate_with_bashlex(command: str) -> bool:
    """Return False if bashlex parse tree contains a forbidden AST node."""
    try:
        for node in _bashlex.parse(command):
            if not _check_bashlex_node(node):
                return False
    except Exception:
        pass  # parse error or unsupported syntax → defer to heuristic
    return True


# ── sqlglot validation ────────────────────────────────────────────────────────

_FORBIDDEN_SQL_TYPES = frozenset({
    "Drop",
    "TruncateTable",
    "AlterTable",
    "Delete",
    "Update",
    "Create",
    "Insert",
    "Command",   # raw EXEC / COPY etc.
})


def _validate_with_sqlglot(command: str) -> bool:
    """Return False if the string contains a forbidden SQL statement type."""
    try:
        for expr in _sqlglot.parse(command):
            if expr is None:
                continue
            if type(expr).__name__ in _FORBIDDEN_SQL_TYPES:
                return False
            for node in expr.walk():
                if type(node).__name__ in _FORBIDDEN_SQL_TYPES:
                    return False
    except Exception:
        pass
    return True


# ── public interface ──────────────────────────────────────────────────────────

def parse_and_validate(command: str) -> bool:
    """Return True if *command* appears safe; False if a forbidden pattern is found.

    Validation runs in three layers, always in order:

    1. **bashlex shell AST** (if installed): rejects destructive shell programs
       with dangerous flags (``rm -rf``, ``git push --force``, pipe-to-shell,
       privilege escalation via ``sudo``/``su``).
    2. **sqlglot SQL AST** (if installed): rejects SQL containing ``DROP``,
       ``TRUNCATE``, ``DELETE``, ``ALTER``, ``UPDATE``, ``INSERT``, or ``CREATE``
       expressions — blocks agents from issuing database-mutating queries.
    3. **Heuristic fallback** (always runs): passes the command through
       :func:`remora.agent_hook.shell_ast.has_destructive_intent`, which uses
       variable-tracking regex analysis and is available with zero extra deps.

    Returns
    -------
    bool
        ``True`` → safe.  ``False`` → blocked; caller should escalate or abort.
    """
    if not command or not command.strip():
        return True

    if _BASHLEX_AVAILABLE and not _validate_with_bashlex(command):
        return False

    if _SQLGLOT_AVAILABLE and not _validate_with_sqlglot(command):
        return False

    if _supplemental_heuristics(command):
        return False

    destructive, _ = _hdi(command)
    if destructive:
        return False

    return True


def bashlex_available() -> bool:
    """Return True if the bashlex library is installed."""
    return _BASHLEX_AVAILABLE


def sqlglot_available() -> bool:
    """Return True if the sqlglot library is installed."""
    return _SQLGLOT_AVAILABLE
