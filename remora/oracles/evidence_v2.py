# Author: Stian Skogbrott
# License: Apache-2.0
"""Source-anchored answer policy.

Pipeline per question:
  1. Filter the corpus by reliability >= min_reliability.
  2. Extract candidate claim sentences from each kept source.
  3. Score each claim's lexical overlap with the question; keep top supporters.
  4. Detect polarity contradictions across supporters.
  5. Answer only when support count >= min_support AND contradictions <=
     max_contradictions; otherwise abstain.

All heuristics are deterministic, stdlib-only. They can be swapped for a
learned scorer later; the interface intentionally keeps reliability,
support, and contradiction as orthogonal knobs so they can be tuned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from remora.oracles.sources import SourceCorpus, score_reliability


_NEG_TOKENS = {"not", "no", "never", "without", "doesn't", "does", "don't",
               "didn't", "isn't", "wasn't", "won't", "cannot", "can't"}


def extract_claims(text: str) -> list[str]:
    """Split text into claim-sized sentences (very simple sentence tokeniser)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+", text.lower()))


def _support_score(claim: str, question: str) -> float:
    q_tokens = _tokens(question)
    if not q_tokens:
        return 0.0
    c_tokens = _tokens(claim)
    overlap = q_tokens & c_tokens
    return len(overlap) / len(q_tokens)


def _has_negation(text: str) -> bool:
    return any(tok in _NEG_TOKENS for tok in _tokens(text))


def detect_contradictions(claims: Sequence[str]) -> int:
    """Count pairs of claims whose token sets are similar but polarity differs."""
    n = len(claims)
    conflicts = 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = claims[i], claims[j]
            ta, tb = _tokens(a), _tokens(b)
            if not ta or not tb:
                continue
            jacc = len(ta & tb) / len(ta | tb)
            if jacc >= 0.3 and _has_negation(a) != _has_negation(b):
                conflicts += 1
    return conflicts


@dataclass(frozen=True)
class EvidenceVerdict:
    action: str  # "answer" or "abstain"
    answer: str | None
    confidence: float
    supporters: int
    contradictions: int
    cited_sources: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""


@dataclass
class EvidenceOracleV2:
    min_reliability: float = 0.5
    min_support: int = 2
    max_contradictions: int = 0
    support_overlap_threshold: float = 0.30
    top_k_per_source: int = 3

    def answer(self, question: str, corpus: SourceCorpus) -> EvidenceVerdict:
        kept = corpus.filter_by_min_reliability(self.min_reliability)
        if not kept.sources:
            return EvidenceVerdict(
                action="abstain", answer=None, confidence=0.0,
                supporters=0, contradictions=0, cited_sources=(),
                reason="No source meets min_reliability.",
            )

        supporters: list[tuple[str, str, float]] = []  # (url, claim, score)
        for src in kept.sources:
            claims = extract_claims(src.text)
            scored = sorted(
                ((c, _support_score(c, question)) for c in claims),
                key=lambda x: -x[1],
            )[: self.top_k_per_source]
            for claim, score in scored:
                if score >= self.support_overlap_threshold:
                    supporters.append((src.url, claim, score))

        if len(supporters) < self.min_support:
            return EvidenceVerdict(
                action="abstain", answer=None, confidence=0.0,
                supporters=len(supporters), contradictions=0, cited_sources=(),
                reason=f"Only {len(supporters)} supporters meet overlap threshold.",
            )

        contradictions = detect_contradictions([claim for _, claim, _ in supporters])
        if contradictions > self.max_contradictions:
            return EvidenceVerdict(
                action="abstain", answer=None, confidence=0.0,
                supporters=len(supporters), contradictions=contradictions,
                cited_sources=tuple(sorted({url for url, _, _ in supporters})),
                reason=f"{contradictions} polarity contradictions across supporters.",
            )

        # Pick the highest-scoring supporter's claim as the answer body; combine
        # source reliabilities into a confidence proxy.
        supporters.sort(key=lambda x: -x[2])
        best_url, best_claim, best_score = supporters[0]
        reliability_avg = sum(
            score_reliability(s) for s in kept.sources if s.url in {u for u, _, _ in supporters}
        ) / max(1, len({u for u, _, _ in supporters}))
        confidence = min(1.0, 0.5 * reliability_avg + 0.5 * best_score)
        return EvidenceVerdict(
            action="answer", answer=best_claim, confidence=confidence,
            supporters=len(supporters), contradictions=contradictions,
            cited_sources=tuple(sorted({url for url, _, _ in supporters})),
            reason="Sufficient on-topic support without contradictions.",
        )
