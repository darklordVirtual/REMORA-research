# Author: Stian Skogbrott
# License: Apache-2.0
"""Adaptive question decomposition layer (L1) for REMORA."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from remora.core import Oracle

_DECOMPOSE_PROMPT = """\
Split the question below into {n} simple, fact-based sub-questions.
Each sub-question should be answerable with yes/no or a single fact.
Return ONLY valid JSON.
Format: {{"subquestions": ["question 1", "question 2", ...]}}

Question: {question}

JSON:"""

_PARALLEL_PROMPT = """\
Formulate {n} different ways to investigate the question below.
Each variant should offer a new angle or check a prerequisite.
Return ONLY valid JSON.
Format: {{"subquestions": ["variant 1", "variant 2", ...]}}

Question: {question}

JSON:"""


def adaptive_decompose(
    question: str,
    oracles: "list[Oracle]",
    max_subquestions: int = 2,
    strategy: str = "simple",
) -> list[str]:
    """Return a list of sub-questions derived from question."""
    if max_subquestions <= 1 or strategy == "simple" or not oracles:
        return [question]
    oracle = oracles[0]
    prompt = _DECOMPOSE_PROMPT if strategy == "chain" else _PARALLEL_PROMPT
    response = oracle.ask(prompt.format(n=max_subquestions, question=question))
    subs = response.extracted.get("subquestions")
    if isinstance(subs, list):
        valid = [str(s).strip() for s in subs if str(s).strip()][:max_subquestions]
        if valid:
            return valid
    return [question]
