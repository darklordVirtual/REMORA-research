"""Retrieval-Augmented Generation (RAG) evidence provider for REMORA.

This provider fetches real documents from a vector store or search backend
and produces grounded evidence signals, replacing the oracle-proxy approach
with actual retrieved passages + NLI-style scoring.

Architecture
------------
1. Query formulation: extract key claims from oracle responses + question
2. Retrieval: call a pluggable retrieval backend (vector DB, BM25, hybrid)
3. Scoring: NLI-style relevance scoring of passages against the claim
4. Signal synthesis: aggregate passage scores into an EvidenceSignal

The provider is intentionally backend-agnostic. Implement RetrievalBackend
for your vector store (Qdrant, Pinecone, ChromaDB, Cloudflare Vectorize, etc.).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from remora.core import OracleResponse
from remora.evidence.evidence_types import EvidenceSignal


# ---------------------------------------------------------------------------
# Retrieval backend protocol
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetrievedPassage:
    """A single passage returned by a retrieval backend."""

    text: str
    source: str  # e.g. "wikipedia:en:Albert_Einstein", "arxiv:2301.00001"
    score: float  # retrieval relevance score in [0, 1]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source_authority(self) -> float:
        """Heuristic authority score based on source type."""
        s = self.source.lower()
        if any(t in s for t in ("wikipedia", "pubmed", "gov", "ieee", "arxiv")):
            return 0.90
        if any(t in s for t in ("stackoverflow", "docs.", "documentation")):
            return 0.75
        if any(t in s for t in ("reddit", "twitter", "forum", "blog")):
            return 0.40
        return 0.60


class RetrievalBackend(Protocol):
    """Protocol for pluggable retrieval backends."""

    def search(self, query: str, *, top_k: int = 5) -> list[RetrievedPassage]:
        """Return top-k passages for the given query."""
        ...


# ---------------------------------------------------------------------------
# NLI scorer protocol
# ---------------------------------------------------------------------------

class NLIScorer(Protocol):
    """Score how well a passage supports or contradicts a claim."""

    def score(self, claim: str, passage: str) -> NLIResult:
        ...


@dataclass(frozen=True)
class NLIResult:
    """NLI classification result."""

    supports: float  # P(entailment)
    neutral: float   # P(neutral)
    contradicts: float  # P(contradiction)

    @property
    def label(self) -> str:
        scores = {"supports": self.supports, "neutral": self.neutral, "contradicts": self.contradicts}
        return max(scores, key=scores.get)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Default implementations (no external deps required)
# ---------------------------------------------------------------------------

class JaccardNLIScorer:
    """Lightweight lexical NLI scorer using Jaccard overlap.

    This is a transparent baseline. Production deployments should replace
    it with a cross-encoder model (e.g. DeBERTa-v3-base-mnli-fever-anli).
    """

    def score(self, claim: str, passage: str) -> NLIResult:
        claim_tokens = set(claim.lower().split())
        passage_tokens = set(passage.lower().split())
        if not claim_tokens or not passage_tokens:
            return NLIResult(supports=0.0, neutral=1.0, contradicts=0.0)

        overlap = len(claim_tokens & passage_tokens)
        union = len(claim_tokens | passage_tokens)
        jaccard = overlap / union if union else 0.0

        # Negation detection (very simple heuristic)
        negation_words = {"not", "no", "never", "neither", "nor", "false", "incorrect", "wrong"}
        passage_has_neg = bool(passage_tokens & negation_words)
        claim_has_neg = bool(claim_tokens & negation_words)
        contradiction_signal = 1.0 if (passage_has_neg != claim_has_neg) else 0.0

        if jaccard > 0.3 and contradiction_signal > 0.5:
            return NLIResult(supports=0.1, neutral=0.2, contradicts=0.7)
        if jaccard > 0.3:
            return NLIResult(supports=jaccard, neutral=1.0 - jaccard, contradicts=0.0)
        return NLIResult(supports=jaccard, neutral=1.0 - jaccard, contradicts=0.0)


class InMemoryRetrievalBackend:
    """Simple in-memory retrieval backend for testing and demos.

    Stores passages in a list and retrieves by Jaccard similarity.
    """

    def __init__(self, passages: list[RetrievedPassage] | None = None) -> None:
        self._passages = list(passages or [])

    def add(self, text: str, source: str, metadata: dict[str, Any] | None = None) -> None:
        self._passages.append(RetrievedPassage(
            text=text, source=source, score=0.0, metadata=metadata or {},
        ))

    def search(self, query: str, *, top_k: int = 5) -> list[RetrievedPassage]:
        query_tokens = set(query.lower().split())
        scored = []
        for p in self._passages:
            p_tokens = set(p.text.lower().split())
            union = len(query_tokens | p_tokens)
            overlap = len(query_tokens & p_tokens) / union if union else 0.0
            scored.append(RetrievedPassage(
                text=p.text, source=p.source, score=overlap, metadata=p.metadata,
            ))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# RAG Evidence Provider
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RAGProviderResult:
    """Extended result from RAG provider with full provenance."""

    signal: EvidenceSignal
    signal_source: str = "retrieval"
    passages: list[RetrievedPassage] = field(default_factory=list)
    nli_results: list[NLIResult] = field(default_factory=list)
    query_used: str = ""
    retrieval_latency_ms: float = 0.0
    provenance_hash: str = ""
    provenance: dict[str, Any] | None = None


class RAGEvidenceProvider:
    """Retrieval-Augmented evidence provider.

    Fetches passages from a retrieval backend, scores them via NLI,
    and synthesizes an EvidenceSignal grounded in real documents.
    """

    def __init__(
        self,
        backend: RetrievalBackend,
        scorer: NLIScorer | None = None,
        *,
        top_k: int = 5,
        min_relevance: float = 0.1,
    ) -> None:
        self._backend = backend
        self._scorer = scorer or JaccardNLIScorer()
        self._top_k = top_k
        self._min_relevance = min_relevance

    def _build_query(
        self,
        question: str,
        oracle_responses: Sequence[OracleResponse],
    ) -> str:
        """Formulate a retrieval query from question + oracle consensus."""
        parts = [question]
        for r in oracle_responses[:3]:
            if r.error is None and r.raw_text:
                # Use raw text snippets rather than canonical verdicts
                snippet = r.raw_text[:200].strip()
                if snippet:
                    parts.append(snippet)
        return " ".join(parts)

    def _provenance_hash(self, passages: list[RetrievedPassage], query: str) -> str:
        """SHA-256 hash of retrieval provenance for audit trail."""
        content = json.dumps({
            "query": query,
            "passages": [{"text": p.text, "source": p.source, "score": p.score} for p in passages],
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()

    def fetch(
        self,
        *,
        question: str,
        domain: str | None = None,
        risk_tier: str | None = None,
        action_type: str | None = None,
        target_environment: str | None = None,
        oracle_responses: Sequence[OracleResponse] = (),
    ) -> RAGProviderResult:
        """Retrieve evidence and produce a grounded signal."""
        del domain, risk_tier, action_type, target_environment  # future use

        query = self._build_query(question, oracle_responses)
        t0 = time.monotonic()
        passages = self._backend.search(query, top_k=self._top_k)
        retrieval_ms = (time.monotonic() - t0) * 1000

        # Filter by minimum relevance
        relevant = [p for p in passages if p.score >= self._min_relevance]

        if not relevant:
            return RAGProviderResult(
                signal=EvidenceSignal(
                    evidence_strength=0.0,
                    contradiction_score=0.0,
                    citation_coverage=0.0,
                    cross_evidence_consistency=0.0,
                    source_reliability=0.0,
                ),
                signal_source="retrieval",
                query_used=query,
                retrieval_latency_ms=retrieval_ms,
                provenance_hash=self._provenance_hash([], query),
            )

        # NLI scoring
        claim = query  # simplified: use query as claim
        nli_results = [self._scorer.score(claim, p.text) for p in relevant]

        # Aggregate signals
        support_scores = [n.supports for n in nli_results]
        contradict_scores = [n.contradicts for n in nli_results]
        authority_scores = [p.source_authority for p in relevant]

        avg_support = sum(support_scores) / len(support_scores)
        avg_contradict = sum(contradict_scores) / len(contradict_scores)
        avg_authority = sum(authority_scores) / len(authority_scores)

        # Cross-evidence consistency: do passages agree with each other?
        if len(nli_results) >= 2:
            labels = [n.label for n in nli_results]
            majority_count = max(labels.count(label) for label in set(labels))
            consistency = majority_count / len(labels)
        else:
            consistency = 1.0

        # Citation coverage: fraction of original passages that were relevant
        coverage = len(relevant) / max(len(passages), 1)

        signal = EvidenceSignal(
            evidence_strength=round(min(1.0, avg_support * (1 + coverage)), 3),
            contradiction_score=round(avg_contradict, 3),
            citation_coverage=round(coverage, 3),
            cross_evidence_consistency=round(consistency, 3),
            source_reliability=round(avg_authority, 3),
        )

        return RAGProviderResult(
            signal=signal,
            signal_source="retrieval",
            passages=relevant,
            nli_results=nli_results,
            query_used=query,
            retrieval_latency_ms=round(retrieval_ms, 2),
            provenance_hash=self._provenance_hash(relevant, query),
            provenance={
                "passage_count": len(relevant),
                "sources": list({p.source for p in relevant}),
                "avg_retrieval_score": round(sum(p.score for p in relevant) / len(relevant), 3),
            },
        )
