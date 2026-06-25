# Author: Stian Skogbrott
# License: Apache-2.0
"""LLM-as-judge verifier for REMORA.

Replaces the purely lexical EvidenceVerifier with an oracle that reasons about
whether a proposed answer is supported by the evidence and the question context.

The judge is oracle-agnostic: pass any Oracle implementation.  Using a model
from a different family than the consensus oracles maximises independence.

Usage:
    judge = LLMJudge(oracle=OpenRouterOracle("mistralai/mistral-7b-instruct:free"))
    verdict = judge.evaluate(
        question="Is the Earth older than 4 billion years?",
        answer="Yes, approximately 4.5 billion years old.",
        evidence=["Earth formed about 4.54 billion years ago (USGS)"],
    )
    verdict.outcome   # JudgeOutcome.SUPPORTED
    verdict.confidence  # 0.97
    verdict.critique    # "Answer is accurate and consistent with cited evidence."
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from remora.core import Oracle


class JudgeOutcome(str, Enum):
    SUPPORTED = "supported"
    CHALLENGED = "challenged"
    REFUTED = "refuted"
    PARSE_ERROR = "parse_error"


@dataclass(frozen=True)
class JudgeVerdict:
    outcome: JudgeOutcome
    confidence: float
    critique: str
    raw_response: str = ""

    @property
    def is_trustworthy(self) -> bool:
        return self.outcome == JudgeOutcome.SUPPORTED and self.confidence >= 0.70

    @property
    def is_refuted(self) -> bool:
        return self.outcome == JudgeOutcome.REFUTED


_JUDGE_PROMPT = """\
You are a rigorous, impartial fact-checker. Evaluate whether a proposed answer \
correctly addresses the question, given the evidence.

Question:
{question}

Proposed answer:
{answer}

Evidence (may be empty — rely on your knowledge if so):
{evidence}

Rules:
- Be strict. A plausible-sounding but unsupported claim is "challenged", not "supported".
- If the answer contradicts the evidence or known facts, use "refuted".
- Respond with ONLY valid JSON. No preamble, no explanation outside the JSON.

Response format:
{{"verdict": "supported" | "challenged" | "refuted", "confidence": 0.0-1.0, "critique": "<one concise sentence>"}}

Definitions:
  supported  — factually correct and consistent with all available evidence
  challenged — partially correct, incomplete, ambiguous, or insufficiently supported
  refuted    — factually wrong or directly contradicted by evidence"""

_VERDICT_WORDS = {o.value: o for o in JudgeOutcome if o != JudgeOutcome.PARSE_ERROR}


class LLMJudge:
    """Oracle-backed LLM judge that evaluates answer quality against evidence."""

    def __init__(self, oracle: Oracle, max_evidence_chars: int = 1200) -> None:
        self.oracle = oracle
        self.max_evidence_chars = max_evidence_chars

    def evaluate(
        self,
        question: str,
        answer: str,
        evidence: Optional[list[str]] = None,
    ) -> JudgeVerdict:
        """Ask the judge oracle to evaluate a proposed answer.

        Args:
            question: the original question.
            answer:   the consensus answer to evaluate.
            evidence: optional list of evidence snippets (RAG results, citations).

        Returns:
            JudgeVerdict with outcome, confidence, and critique.
        """
        evidence_text = self._format_evidence(evidence)
        prompt = _JUDGE_PROMPT.format(
            question=question.strip(),
            answer=answer.strip(),
            evidence=evidence_text,
        )
        response = self.oracle.ask(prompt)
        return _parse_verdict(response.raw_text)

    def _format_evidence(self, snippets: Optional[list[str]]) -> str:
        if not snippets:
            return "(none)"
        combined = "\n".join(f"- {s.strip()}" for s in snippets if s.strip())
        if len(combined) > self.max_evidence_chars:
            combined = combined[: self.max_evidence_chars] + "\n[...truncated]"
        return combined


def _parse_verdict(raw: str) -> JudgeVerdict:
    """Extract JudgeVerdict from raw oracle text.  Falls back gracefully."""
    if not raw:
        return JudgeVerdict(JudgeOutcome.PARSE_ERROR, 0.0, "empty response", raw)

    # Try full JSON parse first
    obj = _try_json(raw)
    if obj:
        return _build_from_dict(obj, raw)

    # Try extracting a JSON object from messy text
    m = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
    if m:
        obj = _try_json(m.group(0))
        if obj:
            return _build_from_dict(obj, raw)

    # Last resort: scan for verdict keyword in the text
    lower = raw.lower()
    for word, outcome in _VERDICT_WORDS.items():
        if word in lower:
            return JudgeVerdict(outcome, 0.5, "verdict inferred from text (parse failed)", raw)

    return JudgeVerdict(JudgeOutcome.PARSE_ERROR, 0.0, f"could not parse: {raw[:80]}", raw)


def _try_json(text: str) -> dict | None:
    try:
        obj = json.loads(text.strip())
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _build_from_dict(obj: dict, raw: str) -> JudgeVerdict:
    verdict_raw = str(obj.get("verdict", "")).lower().strip()
    outcome = _VERDICT_WORDS.get(verdict_raw, JudgeOutcome.PARSE_ERROR)
    try:
        conf = float(obj.get("confidence", 0.5))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.5
    critique = str(obj.get("critique", obj.get("reason", obj.get("explanation", "")))).strip()
    return JudgeVerdict(outcome, conf, critique, raw)
