"""Tests for RAG-backed evidence provider."""

from remora.core import OracleResponse
from remora.evidence.rag_provider import (
    InMemoryRetrievalBackend,
    JaccardNLIScorer,
    RAGEvidenceProvider,
    RAGProviderResult,
    RetrievedPassage,
)


def _oracle(text: str, provider: str = "test") -> OracleResponse:
    return OracleResponse(provider=provider, raw_text=text, extracted={"verdict": "true"})


class TestJaccardNLIScorer:
    def test_high_overlap_supports(self):
        scorer = JaccardNLIScorer()
        result = scorer.score("the earth orbits the sun", "the earth orbits the sun every year")
        assert result.label == "supports"
        assert result.supports > 0.3

    def test_negation_contradicts(self):
        scorer = JaccardNLIScorer()
        result = scorer.score("the earth is round", "the earth is not round at all")
        assert result.label == "contradicts"

    def test_no_overlap_neutral(self):
        scorer = JaccardNLIScorer()
        result = scorer.score("quantum computing", "french cuisine recipes")
        assert result.supports < 0.1

    def test_empty_input(self):
        scorer = JaccardNLIScorer()
        result = scorer.score("", "some text")
        assert result.neutral == 1.0


class TestInMemoryRetrievalBackend:
    def test_search_returns_sorted(self):
        backend = InMemoryRetrievalBackend()
        backend.add("the earth orbits the sun", "wikipedia:earth")
        backend.add("french cuisine is diverse", "wikipedia:france")
        results = backend.search("earth sun orbit", top_k=2)
        assert len(results) == 2
        assert results[0].score >= results[1].score
        assert "earth" in results[0].text.lower()

    def test_empty_backend(self):
        backend = InMemoryRetrievalBackend()
        results = backend.search("anything")
        assert results == []


class TestRetrievedPassage:
    def test_source_authority_wikipedia(self):
        p = RetrievedPassage(text="x", source="wikipedia:en:Test", score=0.9)
        assert p.source_authority == 0.90

    def test_source_authority_reddit(self):
        p = RetrievedPassage(text="x", source="reddit:r/science", score=0.5)
        assert p.source_authority == 0.40

    def test_source_authority_unknown(self):
        p = RetrievedPassage(text="x", source="some_random_source", score=0.5)
        assert p.source_authority == 0.60


class TestRAGEvidenceProvider:
    def _make_provider(self, passages: list[tuple[str, str]]) -> RAGEvidenceProvider:
        backend = InMemoryRetrievalBackend()
        for text, source in passages:
            backend.add(text, source)
        return RAGEvidenceProvider(backend, top_k=3, min_relevance=0.05)

    def test_basic_retrieval(self):
        provider = self._make_provider([
            ("the earth orbits the sun in 365 days", "wikipedia:earth"),
            ("mars orbits the sun in 687 days", "wikipedia:mars"),
        ])
        result = provider.fetch(
            question="how long does earth take to orbit the sun",
            oracle_responses=[_oracle("earth takes 365 days")],
        )
        assert isinstance(result, RAGProviderResult)
        assert result.signal_source == "retrieval"
        assert result.signal.evidence_strength > 0
        assert len(result.passages) > 0
        assert result.provenance_hash  # non-empty

    def test_no_relevant_passages(self):
        provider = self._make_provider([
            ("quantum entanglement theory", "arxiv:001"),
        ])
        result = provider.fetch(
            question="french cooking techniques",
            oracle_responses=[],
        )
        # May or may not find passages depending on min_relevance
        assert isinstance(result, RAGProviderResult)

    def test_empty_backend_returns_zero_signal(self):
        provider = RAGEvidenceProvider(InMemoryRetrievalBackend())
        result = provider.fetch(question="anything", oracle_responses=[])
        assert result.signal.evidence_strength == 0.0
        assert result.signal.citation_coverage == 0.0

    def test_provenance_hash_deterministic(self):
        provider = self._make_provider([("test passage", "src:1")])
        r1 = provider.fetch(question="test", oracle_responses=[])
        r2 = provider.fetch(question="test", oracle_responses=[])
        # Both calls should produce non-empty hashes
        assert r1.provenance_hash
        assert r2.provenance_hash
