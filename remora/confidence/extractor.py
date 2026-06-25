# Author: Stian Skogbrott
# License: Apache-2.0
"""Verbalized confidence extraction from free-text model responses.

Models express confidence in three forms:
  1. Explicit percentage: "I am 85% confident", "85% sure"
  2. Explicit decimal:    "confidence: 0.92", "P(correct)=0.85"
  3. Hedging phrases:     "I'm fairly certain", "I think", "I have no idea"

The extractor returns a float in [0, 1] or None when no signal is found.
"""
from __future__ import annotations

import re

# Hedging phrases ordered longest-first to ensure greedy match.
_HEDGING: list[tuple[str, float]] = sorted(
    [
        ("absolutely certain", 0.98),
        ("completely certain", 0.97),
        ("very confident", 0.90),
        ("highly confident", 0.90),
        ("quite confident", 0.85),
        ("fairly certain", 0.80),
        ("fairly confident", 0.78),
        ("confident", 0.76),
        ("definitely", 0.88),
        ("certainly", 0.85),
        ("strongly believe", 0.82),
        ("believe", 0.70),
        ("quite likely", 0.72),
        ("very likely", 0.80),
        ("likely", 0.68),
        ("probably", 0.65),
        ("think so", 0.60),
        ("think", 0.60),
        ("possibly", 0.50),
        ("might be", 0.48),
        ("might", 0.45),
        ("not entirely sure", 0.38),
        ("not sure", 0.35),
        ("not certain", 0.33),
        ("uncertain", 0.35),
        ("unsure", 0.35),
        ("unclear", 0.35),
        ("hard to say", 0.32),
        ("no idea", 0.25),
        ("have no idea", 0.22),
        ("cannot say", 0.30),
    ],
    key=lambda kv: -len(kv[0]),
)

# "85% confident", "confident 92%", "85 percent sure"
_PCT_CONF = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*%\s+(?:confident|sure|certain)"
    r"|(?:confident|sure|certain)[^.!?\n]*?(\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)

# "confidence: 0.85", "confidence = 0.9", "P(correct) = 0.85"
_DEC_FIELD = re.compile(
    r"(?:confidence|p\s*\(\s*correct\s*\)|probability)\s*[=:]\s*(0?\.\d+|1\.0|0)",
    re.I,
)

# JSON-style {"confidence": 0.85}  or  "confidence": 0.85
_JSON_CONF = re.compile(r'"confidence"\s*:\s*(\d+(?:\.\d+)?)', re.I)


def extract_confidence(text: str) -> float | None:
    """Return a [0, 1] confidence estimate from raw model text, or None."""
    if not text:
        return None

    # 1 — JSON field inside text (highest priority, most explicit)
    m = _JSON_CONF.search(text)
    if m:
        val = float(m.group(1))
        if val > 1.0:
            val /= 100.0
        return max(0.0, min(1.0, val))

    # 2 — Explicit percentage near confidence keyword
    m = _PCT_CONF.search(text)
    if m:
        raw = m.group(1) or m.group(2)
        return max(0.0, min(1.0, float(raw) / 100.0))

    # 3 — Explicit decimal field
    m = _DEC_FIELD.search(text)
    if m:
        return max(0.0, min(1.0, float(m.group(1))))

    # 4 — Hedging phrase lookup (longest phrase wins)
    text_lower = text.lower()
    for phrase, score in _HEDGING:
        if phrase in text_lower:
            return score

    return None


def extract_confidence_from_json(extracted: dict) -> float | None:
    """Pull calibration-ready confidence from an already-parsed oracle response dict."""
    raw = extracted.get("confidence")
    if raw is None:
        return None
    try:
        val = float(raw)
        # Treat values >= 2 as percentage (e.g., 85 → 0.85).
        # Values in (1, 2) are ambiguous decimals slightly over 1 → clamp to 1.
        if val >= 2.0:
            val /= 100.0
        return max(0.0, min(1.0, val))
    except (TypeError, ValueError):
        return None
