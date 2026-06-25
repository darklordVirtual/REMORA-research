# Author: Stian Skogbrott
# License: Apache-2.0
"""Advanced adversarial input detection for REMORA admission firewall.

Layers (applied in order, fail-fast):
  1. Unicode normalisation (NFKC) + zero-width character strip
  2. Token-collapse normalisation (collapse whitespace)
  3. Leet-speak normalisation
  4. Word-boundary regex matching on normalised text
  5. Base64 payload scan
  6. Shell/SQL AST delegation (ast_guard) — for short inputs that look like
     shell/SQL only (gated on indicator characters for performance)

Known limitations
-----------------
- Split-token bypass: 'ig nore prev ious' is not rejoined; only
  whitespace between tokens is normalised, not mid-token splits.
  Mitigation: AST layer catches shell/SQL split-token attacks.
"""
from __future__ import annotations

import base64
import re
import unicodedata

from remora.safety.ast_guard import parse_and_validate

# ── Zero-width and invisible characters ──────────────────────────────────────
# Covers: zero-width space (200B), zero-width non-joiner (200C),
# zero-width joiner (200D), left-to-right mark (200E), right-to-left mark (200F),
# word joiner (2060), zero-width no-break space / BOM (FEFF),
# soft hyphen (00AD).
_ZERO_WIDTH = re.compile(
    r"[­​‌‍‎‏⁠﻿]"
)

# ── Leet-speak normalisation ─────────────────────────────────────────────────
_LEET: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "6": "g",
    "7": "t",
    "8": "b",
    "9": "g",
    "@": "a",
    "$": "s",
    "!": "i",
    "|": "i",
}


def _normalize(text: str) -> str:
    """Return maximally-normalised text for pattern matching."""
    # NFKC: decompose compatibility characters (e.g. fullwidth → ASCII)
    t = unicodedata.normalize("NFKC", text)
    # Strip zero-width and invisible characters
    t = _ZERO_WIDTH.sub("", t)
    # Collapse all whitespace (including newlines, tabs) to single space
    t = re.sub(r"\s+", " ", t)
    t = t.lower()
    # Leet-speak substitution
    t = "".join(_LEET.get(c, c) for c in t)
    return t


# ── Dangerous patterns (word-boundary anchored) ───────────────────────────────
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bignore\s+previous\b"),
    re.compile(r"\boverride\s+safety\b"),
    re.compile(r"\bbypass\s+guard\b"),
    re.compile(r"\bprompt\s+injection\b"),
    re.compile(r"\bjailbreak\b"),
    re.compile(r"\bexfiltrate\b"),
    re.compile(r"\bexfil\b"),
    re.compile(r"\bdelete\s+all\b"),
    re.compile(r"\bdrop\s+all\b"),
    re.compile(r"\bwipe\s+all\b"),
    re.compile(r"\bsudo\s+rm\b"),
    re.compile(r"\broot\s+access\b"),
    re.compile(r"\bgain\s+control\b"),
    re.compile(r"\bdrop\s+table\b"),
]


def _scan_base64(text: str) -> bool:
    """Return True if any base64 token decodes to a known dangerous string."""
    for token in text.split():
        if len(token) < 20:
            continue
        try:
            decoded = base64.b64decode(token + "==", validate=False).decode(
                "utf-8", errors="ignore"
            ).lower()
        except Exception:
            continue
        normalized_decoded = _normalize(decoded)
        if any(p.search(normalized_decoded) for p in _PATTERNS):
            return True
        if any(
            kw in decoded
            for kw in ("jailbreak", "exfiltrate", "bypass", "override safety")
        ):
            return True
    return False


_SHELL_SQL_INDICATORS = frozenset({";", "|", "`", "$", "\\", "/*", "*/", "--", "/"})


def _looks_like_shell_or_sql(text: str) -> bool:
    return any(ind in text for ind in _SHELL_SQL_INDICATORS)


def detect_adversarial(text: str) -> bool:
    """Return True if *text* contains adversarial or injection patterns.

    Applies layered normalisation to defeat common bypass techniques before
    pattern matching. Delegates to AST-backed shell/SQL validation for inputs
    under 2048 characters that contain shell/SQL indicator characters.

    Returns
    -------
    bool
        True  -> adversarial pattern detected; caller must block or escalate.
        False -> no known adversarial pattern found.
    """
    if not text:
        return False

    normalized = _normalize(text)

    if any(p.search(normalized) for p in _PATTERNS):
        return True

    if _scan_base64(text):
        return True

    # AST delegation only for inputs that look like shell/SQL commands
    if len(text) <= 2048 and _looks_like_shell_or_sql(text) and not parse_and_validate(text):
        return True

    return False
