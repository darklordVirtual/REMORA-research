from __future__ import annotations

# Author: Stian Skogbrott
# License: Apache-2.0
"""EvidenceOracleV3 — per-claim evidence table with lexical scoring.

Stronger interface than EvidenceOracleV2:
- Extract atomic claims from candidate_answer (sentence-level)
- For each claim: score lexical support from each source
- Detect source-level contradictions
- Return per-claim evidence table + aggregate decision

Limitation: relation detection is lexical (token overlap + negation heuristic).
No semantic entailment inference. Designed to be pluggable via relation_fn.
"""

import re
from dataclasses import dataclass
from typing import Callable

from remora.oracles.evidence_verifier import (
    EvidenceVerifierProtocol,
    LexicalEvidenceVerifier,
    has_negation,
    lexical_score,
    tokens,
)
from remora.oracles.sources import SourceCorpus, score_reliability


# ---------------------------------------------------------------------------
# Negation vocabulary
# ---------------------------------------------------------------------------

_NEG_TOKENS = frozenset({
    "not", "no", "never", "neither", "without",
    "doesn't", "doesn't", "isn't", "isn't",
    "wasn't", "wasn't", "weren't", "weren't",
    "cannot", "can't", "can't",
})


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, minimum length 2."""
    return tokens(text)


def _lexical_score(claim: str, snippet: str) -> float:
    """Jaccard overlap of claim tokens in snippet tokens, in [0, 1]."""
    return lexical_score(claim, snippet)


def _has_negation(text: str) -> bool:
    """Return True if *text* contains a negation token."""
    return has_negation(text)


def _is_contradiction(claim: str, snippet: str, overlap_threshold: float) -> bool:
    """Return True when overlap >= threshold AND exactly one side has negation."""
    claim_toks = _tokens(claim)
    snippet_toks = _tokens(snippet)
    if not claim_toks or not snippet_toks:
        return False
    union = claim_toks | snippet_toks
    overlap = len(claim_toks & snippet_toks) / len(union)
    if overlap < overlap_threshold:
        return False
    return _has_negation(claim) != _has_negation(snippet)


def _extract_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation [.!?], strip, filter empty."""
    parts = re.split(r"[.!?]", text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AtomicClaim:
    text: str
    index: int  # position in answer


@dataclass(frozen=True)
class EvidenceSnippet:
    source_url: str
    source_reliability: float
    text: str
    lexical_support_score: float   # Jaccard overlap with claim tokens [0, 1]
    is_contradiction: bool


@dataclass(frozen=True)
class ClaimEvidence:
    claim: AtomicClaim
    supporting_snippets: tuple[EvidenceSnippet, ...]
    contradicting_snippets: tuple[EvidenceSnippet, ...]
    best_lexical_support: float    # max support score across snippets
    n_sources_support: int
    n_sources_contradict: int
    is_supported: bool             # n_sources_support >= min_support and best_support >= threshold
    is_contradicted: bool          # n_sources_contradict > 0


@dataclass(frozen=True)
class EvidenceDecision:
    action: str                    # "answer" | "abstain" | "verify"
    answer: str | None
    confidence: float
    per_claim_evidence: tuple[ClaimEvidence, ...]
    cited_sources: tuple[str, ...]  # sorted source URLs
    unsupported_claims: tuple[str, ...]
    contradicted_claims: tuple[str, ...]
    reason: str


# ---------------------------------------------------------------------------
# Default relation function type alias
# ---------------------------------------------------------------------------

RelationFn = Callable[[str, str, float], bool]


# ---------------------------------------------------------------------------
# Main oracle
# ---------------------------------------------------------------------------

@dataclass
class EvidenceOracleV3:
    """Per-claim evidence oracle with lexical scoring.

    Parameters
    ----------
    min_reliability:
        Minimum ``score_reliability`` for a source to be considered.
    min_support:
        Minimum number of distinct sources that must support a claim for it
        to be considered *supported*.
    lexical_threshold:
        Minimum ``lexical_support_score`` for a snippet to count as a
        *supporting* snippet.
    contradiction_threshold:
        Minimum Jaccard overlap required before polarity is checked for a
        possible contradiction.
    top_k_per_source:
        Maximum number of sentences extracted from each source per claim.
    relation_fn:
        Optional callable with signature ``(claim, snippet_text,
        overlap_threshold) -> bool`` that overrides the built-in
        ``_is_contradiction`` heuristic.  Provide an NLI-backed function
        here to upgrade the contradiction detector without changing any
        other logic.
    """

    min_reliability: float = 0.5
    min_support: int = 2
    lexical_threshold: float = 0.15
    contradiction_threshold: float = 0.30
    top_k_per_source: int = 5
    relation_fn: RelationFn | None = None
    verifier: EvidenceVerifierProtocol | None = None

    def evaluate(
        self,
        question: str,
        candidate_answer: str,
        corpus: SourceCorpus,
    ) -> EvidenceDecision:
        """Evaluate *candidate_answer* against *corpus* on a per-claim basis.

        Parameters
        ----------
        question:
            The original user question (reserved for future use / pluggable
            scorers; not used by the lexical scorer directly).
        candidate_answer:
            The answer text to verify.  Atomic claims are extracted by
            sentence splitting.
        corpus:
            The evidence corpus to check against.
        """
        # Step 1 — filter by reliability
        reliable_corpus = corpus.filter_by_min_reliability(self.min_reliability)
        if not reliable_corpus.sources:
            return EvidenceDecision(
                action="abstain",
                answer=None,
                confidence=0.0,
                per_claim_evidence=(),
                cited_sources=(),
                unsupported_claims=(),
                contradicted_claims=(),
                reason="no_reliable_sources",
            )

        # Step 2 — pre-compute reliability scores for kept sources
        reliability: dict[str, float] = {
            s.url: score_reliability(s) for s in reliable_corpus.sources
        }

        verifier = self.verifier or LexicalEvidenceVerifier(
            support_threshold=self.lexical_threshold,
            contradiction_threshold=self.contradiction_threshold,
        )

        # Choose the contradiction function (legacy pluggable compatibility)
        contradiction_fn: RelationFn = self.relation_fn or _is_contradiction

        # Step 3 — extract atomic claims from candidate answer
        raw_sentences = _extract_sentences(candidate_answer)
        if not raw_sentences:
            # Treat entire answer as a single claim if splitting yields nothing
            raw_sentences = [candidate_answer.strip()] if candidate_answer.strip() else [""]

        claims: list[AtomicClaim] = [
            AtomicClaim(text=s, index=i) for i, s in enumerate(raw_sentences)
        ]

        # Step 4 — build ClaimEvidence for each claim
        per_claim: list[ClaimEvidence] = []
        all_cited: set[str] = set()

        for claim in claims:
            supporting: list[EvidenceSnippet] = []
            contradicting: list[EvidenceSnippet] = []
            supporting_sources: set[str] = set()
            contradicting_sources: set[str] = set()

            for src in reliable_corpus.sources:
                # Extract sentences from the source text
                src_sentences = _extract_sentences(src.text)
                if not src_sentences:
                    continue

                # Score all sentences and take top-k
                scored = sorted(
                    ((sent, _lexical_score(claim.text, sent)) for sent in src_sentences),
                    key=lambda x: -x[1],
                )[: self.top_k_per_source]

                for sent_text, score in scored:
                    relation = verifier.classify(claim.text, sent_text)
                    if relation == "supports":
                        score = max(score, self.lexical_threshold)
                    is_contra = relation == "contradicts"
                    if self.relation_fn is not None:
                        is_contra = contradiction_fn(
                            claim.text, sent_text, self.contradiction_threshold
                        )
                    snippet = EvidenceSnippet(
                        source_url=src.url,
                        source_reliability=reliability[src.url],
                        text=sent_text,
                        lexical_support_score=score,
                        is_contradiction=is_contra,
                    )
                    if is_contra:
                        contradicting.append(snippet)
                        contradicting_sources.add(src.url)
                        all_cited.add(src.url)
                    elif relation == "supports" or score >= self.lexical_threshold:
                        supporting.append(snippet)
                        supporting_sources.add(src.url)
                        all_cited.add(src.url)

            best_support = max(
                (s.lexical_support_score for s in supporting), default=0.0
            )
            is_supported = (
                len(supporting_sources) >= self.min_support
                and best_support >= self.lexical_threshold
            )
            is_contradicted = len(contradicting_sources) > 0

            per_claim.append(
                ClaimEvidence(
                    claim=claim,
                    supporting_snippets=tuple(supporting),
                    contradicting_snippets=tuple(contradicting),
                    best_lexical_support=best_support,
                    n_sources_support=len(supporting_sources),
                    n_sources_contradict=len(contradicting_sources),
                    is_supported=is_supported,
                    is_contradicted=is_contradicted,
                )
            )

        # Step 5 / 6 — aggregate
        unsupported = [ce.claim.text for ce in per_claim if not ce.is_supported]
        contradicted = [ce.claim.text for ce in per_claim if ce.is_contradicted]

        # Step 7 — contradiction anywhere → abstain
        if contradicted:
            return EvidenceDecision(
                action="abstain",
                answer=None,
                confidence=0.0,
                per_claim_evidence=tuple(per_claim),
                cited_sources=tuple(sorted(all_cited)),
                unsupported_claims=tuple(unsupported),
                contradicted_claims=tuple(contradicted),
                reason="contradiction_detected",
            )

        # Step 8 — too many unsupported claims
        n_claims = len(claims)
        n_unsupported = len(unsupported)

        if n_unsupported > n_claims / 2:
            n_supported = n_claims - n_unsupported
            if n_supported == 0 and n_claims > 0:
                return EvidenceDecision(
                    action="abstain",
                    answer=None,
                    confidence=0.0,
                    per_claim_evidence=tuple(per_claim),
                    cited_sources=tuple(sorted(all_cited)),
                    unsupported_claims=tuple(unsupported),
                    contradicted_claims=tuple(contradicted),
                    reason="insufficient_support",
                )
            return EvidenceDecision(
                action="verify",
                answer=candidate_answer,
                confidence=0.0,
                per_claim_evidence=tuple(per_claim),
                cited_sources=tuple(sorted(all_cited)),
                unsupported_claims=tuple(unsupported),
                contradicted_claims=tuple(contradicted),
                reason="insufficient_support",
            )

        # Step 9 — answer
        support_scores = [ce.best_lexical_support for ce in per_claim]
        confidence = sum(support_scores) / len(support_scores) if support_scores else 0.0

        return EvidenceDecision(
            action="answer",
            answer=candidate_answer,
            confidence=min(1.0, confidence),
            per_claim_evidence=tuple(per_claim),
            cited_sources=tuple(sorted(all_cited)),
            unsupported_claims=tuple(unsupported),
            contradicted_claims=tuple(contradicted),
            reason="sufficient_lexical_support",
        )
