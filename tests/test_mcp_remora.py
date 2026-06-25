from __future__ import annotations
import sys
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, str(Path(__file__).parent.parent / "servers"))
import mcp_remora


def _rag_verdict(conf=0.88, models_agreed=True):
    return {
        "answer": True,
        "claim": "GDPR Article 17 grants right to erasure under defined conditions",
        "confidence": conf,
        "sources": ["GDPR-Article-17"],
        "retrieved_chunks": 3,
        "reranked": True,
        "cache_hit": False,
        "multilingual": False,
        "model": "@cf/meta/llama-3.3-70b-instruct",
        "dual_consensus": True,
        "models_agreed": models_agreed,
    }


def _remora_verdict():
    return {
        "verdict": True,
        "confidence": 0.82,
        "claim": "Clause is valid under EU law",
        "summary": "2/3 oracles agreed",
        "oracle_calls": 3,
        "routed_fast": False,
    }


def fake_post_legal(url, payload, timeout=90):
    if "rag-oracle" in url:
        return _rag_verdict()
    return _remora_verdict()


class TestLegalAnalysisBugFix:

    def test_calls_rag_post_query_not_get(self):
        """Bug 2: must use POST /query, not GET /search."""
        post_calls, get_calls = [], []

        with mock.patch.object(mcp_remora, "_post",
                               lambda u, p, **k: (post_calls.append((u, p)), fake_post_legal(u, p))[1]), \
             mock.patch.object(mcp_remora, "_get",
                               lambda u, **k: get_calls.append(u) or {}):
            mcp_remora.handle_remora_legal_analysis({
                "document_text": "Contract states clause 15 applies.",
                "analysis_question": "Is clause 15 valid under GDPR?",
                "jurisdiction": "EU",
            })

        rag_query_calls = [u for u, _ in post_calls if "rag-oracle" in u and "/query" in u]
        assert len(rag_query_calls) == 1, "Must POST to RAG /query"
        assert len(get_calls) == 0, "Must NOT call GET /search"

    def test_rag_call_uses_legal_use_case(self):
        """use_case=legal triggers dual_consensus in worker."""
        rag_payload = {}

        def fake_post(url, payload, timeout=90):
            if "rag-oracle" in url:
                rag_payload.update(payload)
                return _rag_verdict()
            return _remora_verdict()

        with mock.patch.object(mcp_remora, "_post", fake_post), \
             mock.patch.object(mcp_remora, "_get", lambda *a, **k: {}):
            mcp_remora.handle_remora_legal_analysis({
                "document_text": "Some contract.",
                "analysis_question": "Is this compliant?",
            })

        assert rag_payload.get("use_case") == "legal"

    def test_domain_forwarded_to_rag(self):
        """Bug 1/3: user-supplied domain reaches RAG /query."""
        rag_payload = {}

        def fake_post(url, payload, timeout=90):
            if "rag-oracle" in url:
                rag_payload.update(payload)
                return _rag_verdict()
            return _remora_verdict()

        with mock.patch.object(mcp_remora, "_post", fake_post), \
             mock.patch.object(mcp_remora, "_get", lambda *a, **k: {}):
            mcp_remora.handle_remora_legal_analysis({
                "document_text": "Text.",
                "analysis_question": "Question?",
                "domain": "science",
            })

        assert rag_payload.get("domain") == "science"

    def test_output_shows_rag_synthesis_and_models_agreed(self):
        with mock.patch.object(mcp_remora, "_post", fake_post_legal), \
             mock.patch.object(mcp_remora, "_get", lambda *a, **k: {}):
            result = mcp_remora.handle_remora_legal_analysis({
                "document_text": "Contract.",
                "analysis_question": "Valid?",
                "jurisdiction": "EU",
            })

        assert "Knowledge Base" in result or "88%" in result
        assert "agreed" in result.lower()

    def test_graceful_on_remora_error(self):
        def fake_post(url, payload, timeout=90):
            if "rag-oracle" in url:
                return _rag_verdict()
            return {"error": "Worker timeout"}

        with mock.patch.object(mcp_remora, "_post", fake_post), \
             mock.patch.object(mcp_remora, "_get", lambda *a, **k: {}):
            result = mcp_remora.handle_remora_legal_analysis({
                "document_text": "text",
                "analysis_question": "question",
            })

        assert "error" in result.lower()


class TestOutputImprovements:

    def test_analyze_document_shows_domain(self):
        def fake_post(url, payload, timeout=90):
            return {
                "verdict": True, "confidence": 0.90,
                "claim": "Text confirms claim",
                "summary": "3/3 agreed", "oracle_calls": 3, "routed_fast": True,
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            result = mcp_remora.handle_remora_analyze_document({
                "text": "Document text.",
                "question": "Is this accurate?",
                "domain": "science",
            })

        assert "science" in result

    def test_analyze_document_shows_dual_consensus(self):
        def fake_post(url, payload, timeout=90):
            return {
                "verdict": True, "confidence": 0.92,
                "claim": "Confirmed", "summary": "agreed",
                "oracle_calls": 2, "routed_fast": False,
                "dual_consensus": True, "models_agreed": True,
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            result = mcp_remora.handle_remora_analyze_document({
                "text": "text", "question": "valid?",
            })

        assert "agreed" in result.lower()

    def test_verify_claim_shows_domain(self):
        def fake_post(url, payload, timeout=90):
            return {
                "verdict": True, "confidence": 0.85,
                "claim": "GDPR applies", "summary": "2/3 agreed",
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            result = mcp_remora.handle_remora_verify_claim({
                "claim": "GDPR Article 17 gives right to erasure?",
                "domain": "legal",
            })

        assert "legal" in result

    def test_verify_claim_shows_models_disagreed(self):
        def fake_post(url, payload, timeout=90):
            return {
                "verdict": None, "confidence": 0.55,
                "claim": "Uncertain", "summary": "split",
                "dual_consensus": True, "models_agreed": False,
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            result = mcp_remora.handle_remora_verify_claim({"claim": "claim?"})

        assert "disagreed" in result.lower()


class TestNorwegianLawSearch:

    def test_posts_to_law_search(self):
        post_calls = []

        def fake_post(url, payload, timeout=90):
            post_calls.append((url, payload))
            return {
                "query": "oppsigelse",
                "matches": [{
                    "score": 0.91,
                    "law_id": "aml-2005-06-17-62",
                    "title": "Arbeidsmiljøloven",
                    "section": "§ 15-7",
                    "paragraph_ref": "§ 15-7",
                    "content": "Arbeidstaker kan ikke sies opp uten saklig grunn.",
                    "url": "https://lovdata.no/lov/2005-06-17-62/§15-7",
                }],
                "total": 1,
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            result = mcp_remora.handle_remora_norwegian_law_search({
                "query": "oppsigelse arbeidsmiljøloven",
            })

        law_calls = [u for u, _ in post_calls if "law-search" in u]
        assert len(law_calls) == 1
        assert "Arbeidsmiljøloven" in result or "15-7" in result

    def test_no_results_returns_helpful_message(self):
        with mock.patch.object(mcp_remora, "_post",
                               lambda *a, **k: {"matches": [], "total": 0}):
            result = mcp_remora.handle_remora_norwegian_law_search({"query": "xyz"})

        assert "ingen" in result.lower() or "Ingen" in result

    def test_requires_query(self):
        result = mcp_remora.handle_remora_norwegian_law_search({})
        assert "Error" in result

    def test_tool_in_tools_list(self):
        names = [t["name"] for t in mcp_remora.TOOLS]
        assert "remora_norwegian_law_search" in names

    def test_handler_in_handlers(self):
        assert "remora_norwegian_law_search" in mcp_remora.HANDLERS


class TestRagQuery:

    def test_posts_to_rag_query(self):
        post_calls = []

        def fake_post(url, payload, timeout=90):
            post_calls.append((url, payload))
            return {
                "answer": True,
                "claim": "GDPR Article 17 grants right to erasure.",
                "confidence": 0.91,
                "sources": ["GDPR-Article-17", "GDPR-Recital-65"],
                "retrieved_chunks": 4, "reranked": True,
                "cache_hit": False, "multilingual": False,
                "model": "@cf/meta/llama-3.3-70b-instruct",
                "dual_consensus": True, "models_agreed": True,
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            result = mcp_remora.handle_remora_rag_query({
                "query": "Does GDPR Article 17 grant right to erasure?",
                "domain": "specialised",
                "dual_consensus": True,
            })

        rag_calls = [u for u, _ in post_calls if "rag-oracle" in u and "/query" in u]
        assert len(rag_calls) == 1
        assert "91%" in result or "GDPR" in result

    def test_passes_use_case_when_provided(self):
        seen = {}

        def fake_post(url, payload, timeout=90):
            if "rag-oracle" in url:
                seen.update(payload)
            return {
                "answer": None, "claim": "none", "confidence": 0.0,
                "sources": [], "retrieved_chunks": 0, "reranked": False,
                "cache_hit": False, "multilingual": False, "model": "x",
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            mcp_remora.handle_remora_rag_query({"query": "Q?", "use_case": "legal"})

        assert seen.get("use_case") == "legal"

    def test_omits_use_case_when_not_provided(self):
        seen = {}

        def fake_post(url, payload, timeout=90):
            if "rag-oracle" in url:
                seen.update(payload)
            return {
                "answer": None, "claim": "none", "confidence": 0.0,
                "sources": [], "retrieved_chunks": 0, "reranked": False,
                "cache_hit": False, "multilingual": False, "model": "x",
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            mcp_remora.handle_remora_rag_query({"query": "question"})

        assert "use_case" not in seen

    def test_shows_models_disagreed(self):
        def fake_post(url, payload, timeout=90):
            return {
                "answer": True, "claim": "Confirmed",
                "confidence": 0.75, "sources": [],
                "retrieved_chunks": 2, "reranked": False,
                "cache_hit": False, "multilingual": False,
                "model": "8b+70b",
                "dual_consensus": True, "models_agreed": False,
            }

        with mock.patch.object(mcp_remora, "_post", fake_post):
            result = mcp_remora.handle_remora_rag_query({
                "query": "Test?", "dual_consensus": True,
            })

        assert "disagreed" in result.lower()

    def test_tool_and_handler_registered(self):
        names = [t["name"] for t in mcp_remora.TOOLS]
        assert "remora_rag_query" in names
        assert "remora_rag_query" in mcp_remora.HANDLERS

    def test_requires_query(self):
        result = mcp_remora.handle_remora_rag_query({})
        assert "Error" in result
