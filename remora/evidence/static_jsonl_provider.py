# Author: Stian Skogbrott
# License: Apache-2.0
"""StaticJsonlEvidenceProvider — retrieval-backed evidence from curated JSONL.

Loads ``datasets/remora_knowledge_v1/evidence_packs/evidence_objects.jsonl``
(or any compatible JSONL file) at construction time and performs lightweight
in-memory retrieval based on keyword, domain, and risk_tag matching.

This is an *additional* provider alongside ``OracleProxyEvidenceProvider``.
It does **not** replace or modify policy automatically — it only supplies an
``EvidenceProviderResult`` that the policy engine can factor in.

Design
------
- Pure Python, zero external runtime dependencies (pathlib + json only).
- Deterministic: same query → same ranked result set.
- Graceful degradation: if the JSONL file is missing or empty, returns a
  zero-signal result rather than raising.
- Thread-safe for read access after construction (immutable evidence store).
- Retrieval quality: lexical relevance first-pass + lightweight semantic
    similarity + deterministic reranking.
- Provenance: returns ranked evidence metadata and scoring strategy details.

Evidence object schema (required fields)
-----------------------------------------
  evidence_id         str
  source              str
  title               str
  content             str
  domain              str
  risk_tags           list[str]
  authority_score     float  (0-1)
  freshness_score     float  (0-1)
  coverage_score      float  (0-1)
  contradiction_score float  (0-1)  — per-object contradiction estimate

All other fields (source_url, version, license_note …) are optional and
preserved transparently in ``retrieved_evidence``.

Signal computation
------------------
  evidence_strength          = mean(authority_score × freshness_score) over top-k hits
  citation_coverage          = min(1.0, k / MAX_USEFUL_CITATIONS)
  source_reliability         = mean(authority_score) over top-k hits
  cross_evidence_consistency = 1 - std(authority_score) over top-k hits
  contradiction_score        = mean(contradiction_score) over top-k hits

MAX_USEFUL_CITATIONS = 5 — beyond five citations the marginal coverage gain
is negligible for a single policy decision.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Optional, Sequence

from remora.core import OracleResponse
from remora.evidence.evidence_types import EvidenceSignal
from remora.evidence.provider import EvidenceProviderResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_USEFUL_CITATIONS = 5
DEFAULT_JSONL_PATH = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "remora_knowledge_v1"
    / "evidence_packs"
    / "evidence_objects.jsonl"
)

_REQUIRED_FIELDS = {
    "evidence_id",
    "source",
    "title",
    "content",
    "domain",
    "risk_tags",
    "authority_score",
    "freshness_score",
    "coverage_score",
    "contradiction_score",
}

SEMANTIC_SCORER_VERSION = "semantic-lite-v1"
RERANKER_VERSION = "deterministic-rerank-v1"


# ---------------------------------------------------------------------------
# Helper — zero signal sentinel
# ---------------------------------------------------------------------------

def _zero_result(reason: str = "no_match") -> EvidenceProviderResult:
    return EvidenceProviderResult(
        signal=EvidenceSignal(
            evidence_strength=0.0,
            contradiction_score=0.0,
            citation_coverage=0.0,
            cross_evidence_consistency=0.0,
            source_reliability=0.0,
        ),
        signal_source=f"retrieval_static_jsonl:{reason}",
    )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Relevance scorer
# ---------------------------------------------------------------------------

def _relevance_score(
    obj: dict[str, Any],
    *,
    keywords: list[str],
    domain: str | None,
    risk_tags: list[str],
) -> float:
    """Return a [0, 1] relevance score for one evidence object.

    Scoring components (additive, then normalised):
      - domain exact match: +0.40
      - risk_tag overlap (Jaccard × 0.30)
      - keyword hits in title/content (capped at 0.30)
    """
    score = 0.0

    # Domain match
    obj_domain = str(obj.get("domain", "")).lower()
    if domain and obj_domain == domain.lower():
        score += 0.40

    # Risk-tag overlap (Jaccard)
    obj_tags = {t.lower() for t in (obj.get("risk_tags") or [])}
    query_tags = {t.lower() for t in risk_tags}
    if query_tags or obj_tags:
        union = query_tags | obj_tags
        intersection = query_tags & obj_tags
        score += 0.30 * (len(intersection) / len(union) if union else 0.0)

    # Keyword hits in title + content
    if keywords:
        text = (
            str(obj.get("title", "")).lower()
            + " "
            + str(obj.get("content", "")).lower()
        )
        hits = sum(1 for kw in keywords if kw.lower() in text)
        keyword_score = min(1.0, hits / len(keywords))
        score += 0.30 * keyword_score

    return min(1.0, score)


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_\-]{3,}", text.lower())
    out: list[str] = []
    for token in tokens:
        t = token
        for suffix in ("ing", "ed", "es", "s"):
            if len(t) > 5 and t.endswith(suffix):
                t = t[: -len(suffix)]
                break
        out.append(t)
    return out


def _soft_token_overlap(query_tokens: list[str], doc_tokens: list[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0

    doc_set = set(doc_tokens)
    exact = sum(1 for t in query_tokens if t in doc_set)
    soft = 0
    for token in query_tokens:
        if token in doc_set:
            continue
        if any(dt.startswith(token[:4]) or token.startswith(dt[:4]) for dt in doc_set if len(dt) >= 4):
            soft += 1
    return min(1.0, (exact + 0.5 * soft) / len(query_tokens))


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    compact = re.sub(r"\s+", " ", text.lower()).strip()
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i : i + n] for i in range(0, len(compact) - n + 1)}


def _semantic_similarity(query_text: str, doc_text: str) -> float:
    query_tokens = _tokenize(query_text)
    doc_tokens = _tokenize(doc_text)
    token_score = _soft_token_overlap(query_tokens, doc_tokens)

    q_ngrams = _char_ngrams(query_text)
    d_ngrams = _char_ngrams(doc_text)
    if q_ngrams or d_ngrams:
        union = q_ngrams | d_ngrams
        ngram_score = (len(q_ngrams & d_ngrams) / len(union)) if union else 0.0
    else:
        ngram_score = 0.0

    return min(1.0, 0.7 * token_score + 0.3 * ngram_score)


# ---------------------------------------------------------------------------
# Main provider
# ---------------------------------------------------------------------------

class StaticJsonlEvidenceProvider:
    """Retrieval-backed evidence provider over a curated JSONL evidence store.

    Parameters
    ----------
    jsonl_path:
        Path to the evidence_objects.jsonl file.  Defaults to the bundled
        ``datasets/remora_knowledge_v1/evidence_packs/evidence_objects.jsonl``.
    top_k:
        Maximum number of evidence objects to include in a result.
        Defaults to ``MAX_USEFUL_CITATIONS`` (5).
    min_relevance:
        Objects with a relevance score below this threshold are excluded even
        if no better matches exist.  Defaults to 0.05 so that truly unrelated
        evidence is suppressed.
    strict_load:
        If True, raise ``ValueError`` for evidence objects that are missing
        required fields.  If False (default), skip invalid objects with a
        warning.

    Usage
    -----
        from remora.evidence.static_jsonl_provider import StaticJsonlEvidenceProvider

        provider = StaticJsonlEvidenceProvider()
        result = provider.fetch(
            question="Should the agent execute kubectl delete namespace prod?",
            domain="kubernetes",
            risk_tier="critical",
            action_type="destructive_write",
            target_environment="production",
            oracle_responses=[],
        )
        print(result.signal.evidence_strength, result.signal_source)
    """

    def __init__(
        self,
        jsonl_path: Optional[Path | str] = None,
        *,
        top_k: int = MAX_USEFUL_CITATIONS,
        min_relevance: float = 0.05,
        min_semantic: float = 0.10,
        rerank_pool_size: int | None = None,
        strict_load: bool = False,
    ) -> None:
        self._path = Path(jsonl_path) if jsonl_path is not None else DEFAULT_JSONL_PATH
        self._top_k = max(1, top_k)
        self._min_relevance = min_relevance
        self._min_semantic = min_semantic
        self._rerank_pool_size = max(self._top_k, int(rerank_pool_size or (self._top_k * 4)))
        self._strict_load = strict_load
        self._store: list[dict[str, Any]] = []
        self._load_errors: list[str] = []
        self._loaded = False
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            self._load_errors.append(f"evidence file not found: {self._path}")
            self._loaded = False
            return

        loaded = 0
        skipped = 0
        with self._path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    msg = f"line {lineno}: JSON parse error — {exc}"
                    if self._strict_load:
                        raise ValueError(msg) from exc
                    self._load_errors.append(msg)
                    skipped += 1
                    continue

                missing = _REQUIRED_FIELDS - obj.keys()
                if missing:
                    msg = f"line {lineno}: missing fields {sorted(missing)}"
                    if self._strict_load:
                        raise ValueError(msg)
                    self._load_errors.append(msg)
                    skipped += 1
                    continue

                self._store.append(obj)
                loaded += 1

        self._loaded = loaded > 0

    # ------------------------------------------------------------------
    # Public interface (EvidenceProvider Protocol)
    # ------------------------------------------------------------------

    def fetch(
        self,
        *,
        question: str,
        domain: str | None,
        risk_tier: str | None,
        action_type: str | None,
        target_environment: str | None,
        oracle_responses: Sequence[OracleResponse],
    ) -> EvidenceProviderResult:
        """Retrieve matching evidence and compute an EvidenceSignal.

        Parameters mirror the ``EvidenceProvider`` Protocol so this class is
        a drop-in additional provider.
        """
        del oracle_responses  # not used — this is retrieval-only

        if not self._loaded or not self._store:
            return _zero_result("store_empty")

        # Build query signals from the question + structured fields
        query_text = " ".join(
            filter(None, [question, domain, risk_tier, action_type, target_environment])
        )
        keywords = self._extract_keywords(question, action_type, risk_tier, target_environment)
        risk_tags = self._infer_risk_tags(risk_tier, action_type, target_environment)

        # Score all objects (lexical first pass + semantic similarity)
        scored: list[tuple[float, float, dict[str, Any]]] = []
        for obj in self._store:
            rel = _relevance_score(
                obj,
                keywords=keywords,
                domain=domain,
                risk_tags=risk_tags,
            )
            doc_text = " ".join(
                [
                    str(obj.get("title", "")),
                    str(obj.get("content", "")),
                    str(obj.get("domain", "")),
                    " ".join(str(t) for t in (obj.get("risk_tags") or [])),
                ]
            )
            semantic = _semantic_similarity(query_text, doc_text)
            if rel >= self._min_relevance or semantic >= self._min_semantic:
                scored.append((rel, semantic, obj))

        if not scored:
            return _zero_result("no_relevant_evidence")

        # Sort by first-pass retrieval score, then authority as tiebreak
        scored.sort(
            key=lambda t: (
                0.65 * t[0] + 0.35 * t[1],
                _safe_float(t[2].get("authority_score")),
            ),
            reverse=True,
        )
        rerank_pool = scored[: self._rerank_pool_size]

        reranked: list[tuple[float, float, float, dict[str, Any]]] = []
        for rel, semantic, obj in rerank_pool:
            authority = _safe_float(obj.get("authority_score"))
            freshness = _safe_float(obj.get("freshness_score"))
            coverage = _safe_float(obj.get("coverage_score"))
            quality = 0.5 * authority + 0.3 * freshness + 0.2 * coverage
            rerank_score = 0.55 * rel + 0.25 * semantic + 0.20 * quality
            reranked.append((rerank_score, rel, semantic, obj))

        reranked.sort(
            key=lambda t: (t[0], _safe_float(t[3].get("authority_score"))),
            reverse=True,
        )
        top = reranked[: self._top_k]

        # Compute signal components
        authority_scores = [_safe_float(obj.get("authority_score")) for _, _, _, obj in top]
        freshness_scores = [_safe_float(obj.get("freshness_score")) for _, _, _, obj in top]
        contradiction_scores = [_safe_float(obj.get("contradiction_score")) for _, _, _, obj in top]

        evidence_strength = _mean([a * f for a, f in zip(authority_scores, freshness_scores)])
        citation_coverage = min(1.0, len(top) / MAX_USEFUL_CITATIONS)
        source_reliability = _mean(authority_scores)
        cross_evidence_consistency = max(0.0, 1.0 - _std(authority_scores))
        contradiction_score = _mean(contradiction_scores)

        ranked_evidence: list[dict[str, Any]] = []
        for idx, (rerank_score, rel, semantic, obj) in enumerate(top, start=1):
            ranked_evidence.append(
                {
                    "rank": idx,
                    "evidence_id": str(obj.get("evidence_id", "")),
                    "source": str(obj.get("source", "")),
                    "source_url": obj.get("source_url"),
                    "title": str(obj.get("title", ""))[:200],
                    "relevance": round(rel, 3),
                    "semantic_similarity": round(semantic, 3),
                    "rerank_score": round(rerank_score, 3),
                }
            )

        provenance = {
            "retrieval_strategy": "lexical_plus_semantic_rerank",
            "semantic_scorer_version": SEMANTIC_SCORER_VERSION,
            "reranker_version": RERANKER_VERSION,
            "top_k": self._top_k,
            "rerank_pool_size": min(self._rerank_pool_size, len(scored)),
            "query_keywords": keywords[:12],
            "risk_tags": risk_tags,
            "evidence": ranked_evidence,
        }

        return EvidenceProviderResult(
            signal=EvidenceSignal(
                evidence_strength=round(evidence_strength, 3),
                contradiction_score=round(contradiction_score, 3),
                citation_coverage=round(citation_coverage, 3),
                cross_evidence_consistency=round(cross_evidence_consistency, 3),
                source_reliability=round(source_reliability, 3),
            ),
            signal_source="retrieval_static_jsonl",
            provenance=provenance,
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_keywords(
        question: str,
        action_type: str | None,
        risk_tier: str | None,
        target_environment: str | None,
    ) -> list[str]:
        """Extract meaningful tokens from query fields."""
        text = " ".join(filter(None, [question, action_type, risk_tier, target_environment]))
        # Tokenise: lower, strip punctuation, drop short stop-words
        stop = {
            "the", "a", "an", "to", "of", "and", "or", "in", "is",
            "for", "with", "this", "that", "be", "on", "by", "at",
        }
        tokens = re.findall(r"[a-z0-9_\-]{3,}", text.lower())
        return [t for t in tokens if t not in stop]

    @staticmethod
    def _infer_risk_tags(
        risk_tier: str | None,
        action_type: str | None,
        target_environment: str | None,
    ) -> list[str]:
        """Convert structured fields to risk-tag vocabulary."""
        tags: list[str] = []
        if risk_tier:
            tags.append(risk_tier.lower())
        if action_type:
            tags.extend(action_type.lower().replace("-", "_").split("_"))
        if target_environment:
            tags.append(target_environment.lower())
        return tags

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def store_size(self) -> int:
        """Number of successfully loaded evidence objects."""
        return len(self._store)

    @property
    def load_errors(self) -> list[str]:
        """List of non-fatal load errors (skipped lines)."""
        return list(self._load_errors)

    @property
    def jsonl_path(self) -> Path:
        """Resolved path to the evidence JSONL file."""
        return self._path

    def summary(self) -> dict:
        """Diagnostic summary for logging/inspection."""
        domains = {}
        for obj in self._store:
            d = str(obj.get("domain", "unknown"))
            domains[d] = domains.get(d, 0) + 1
        return {
            "store_size": self.store_size,
            "jsonl_path": str(self._path),
            "loaded": self._loaded,
            "load_errors": len(self._load_errors),
            "top_k": self._top_k,
            "min_relevance": self._min_relevance,
            "min_semantic": self._min_semantic,
            "rerank_pool_size": self._rerank_pool_size,
            "semantic_scorer_version": SEMANTIC_SCORER_VERSION,
            "reranker_version": RERANKER_VERSION,
            "domains": domains,
        }
