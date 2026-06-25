# Author: Stian Skogbrott
# License: Apache-2.0
"""Canonical counterfactual stress-testing helpers for REMORA.

This module centralizes the claim-type-aware counterfactual logic that used to
be split across ``remora.causality`` and ``remora.causality_v2``.
Legacy modules remain as thin compatibility wrappers so existing imports keep
working while the engine and documentation can point to this canonical home.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from remora.core import Oracle


class ClaimType(str, Enum):
    CAUSAL = "causal"
    DEFINITIONAL = "definitional"
    OBSERVATIONAL = "observational"
    STATISTICAL = "statistical"
    UNKNOWN = "unknown"


_CAUSAL_PATTERNS = [r"\bcause(s|d)?\b", r"\bleads? to\b", r"\bresults? in\b", r"\bdue to\b", r"\bbecause of\b", r"\btriggers?\b"]
_DEFINITIONAL_PATTERNS = [r"\bby definition\b", r"\bis defined as\b", r"\ball [a-z]+ are\b", r"\ba [a-z]+ has\b", r"\bequals?\b", r"\bequivalent to\b"]
_STATISTICAL_PATTERNS = [r"\b\d+%", r"\bon average\b", r"\bmean\b", r"\bmedian\b", r"\bprobability\b", r"\bcorrelat(ed|ion)\b"]


def generate_counterfactual(question: str, context: Optional[str], red_team_oracle: Oracle) -> str:
    """Generate a premise-inverted version of a claim for stress testing."""
    ctx = f"\nContext:\n{context}\n" if context else ""
    prompt = (
        f"{ctx}You are a causal inference Red-Team agent.\n"
        "Your task is to identify a core premise, assumption, or variable "
        "in the following question, and INVERT it to stress-test an LLM ensemble.\n"
        "If the question asks about outcome Y given event X, rewrite it to ask about Y given NOT X.\n"
        "Return ONLY valid JSON.\n"
        'Format: {"intervened_variable": "<what you changed>", "counterfactual_question": "<the new inverted question>"}\n\n'
        f"Original Question: {question}\n\nJSON:"
    )

    response = red_team_oracle.ask(prompt)
    if response.extracted and isinstance(response.extracted, dict):
        counterfactual_question = response.extracted.get("counterfactual_question")
        if counterfactual_question and isinstance(counterfactual_question, str):
            return counterfactual_question

    return f"Assuming the exact opposite of the original context: {question}"


def evaluate_causal_response(original_polarity: Optional[bool], counterfactual_polarity: Optional[bool]) -> bool:
    """Evaluate the original polarity-flip heuristic used by the legacy gate."""
    if original_polarity is None or counterfactual_polarity is None:
        return True

    return original_polarity != counterfactual_polarity


def classify_claim(text: str) -> ClaimType:
    """Classify a claim so the counterfactual gate can choose the right policy."""
    low = text.lower()
    if any(re.search(pattern, low) for pattern in _DEFINITIONAL_PATTERNS):
        return ClaimType.DEFINITIONAL
    if any(re.search(pattern, low) for pattern in _CAUSAL_PATTERNS):
        return ClaimType.CAUSAL
    if any(re.search(pattern, low) for pattern in _STATISTICAL_PATTERNS):
        return ClaimType.STATISTICAL
    if re.search(r"\bis\b|\bare\b|\bwas\b|\bwere\b", low):
        return ClaimType.OBSERVATIONAL
    return ClaimType.UNKNOWN


def expected_under_intervention(claim_type: ClaimType, original_polarity: bool) -> str:
    """Describe the expected polarity behavior for a claim type under intervention."""
    if claim_type == ClaimType.CAUSAL:
        return "flip"
    if claim_type == ClaimType.DEFINITIONAL:
        return "invariant"
    if claim_type == ClaimType.STATISTICAL:
        return "soft"
    return "invariant"


def evaluate_invariance(
    claim_type: ClaimType,
    original_polarity: bool | None,
    counterfactual_polarity: bool | None,
) -> bool:
    """Evaluate whether a claim behaves as expected under counterfactual stress."""
    if original_polarity is None or counterfactual_polarity is None:
        return True

    rule = expected_under_intervention(claim_type, original_polarity)
    if rule == "flip":
        return original_polarity != counterfactual_polarity
    if rule == "invariant":
        return original_polarity == counterfactual_polarity
    return True


__all__ = [
    "ClaimType",
    "classify_claim",
    "expected_under_intervention",
    "evaluate_invariance",
    "generate_counterfactual",
    "evaluate_causal_response",
]
