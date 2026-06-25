# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for StaticJsonlEvidenceProvider.

These tests use temporary JSONL files so they run independently of
whether the full dataset is present.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from remora.evidence.static_jsonl_provider import (
    StaticJsonlEvidenceProvider,
    _mean,
    _relevance_score,
    _std,
    _zero_result,
)
from remora.evidence.provider import EvidenceProviderResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_obj(**overrides) -> dict:
    base = {
        "evidence_id": "ev_001",
        "source": "NIST",
        "source_url": "https://example.com",
        "title": "AI Risk Management Framework",
        "content": "NIST AI RMF provides guidance for managing AI risk including governance.",
        "domain": "ai_governance",
        "risk_tags": ["high", "governance", "policy"],
        "authority_score": 0.9,
        "freshness_score": 0.85,
        "coverage_score": 0.80,
        "contradiction_score": 0.05,
    }
    base.update(overrides)
    return base


def _write_jsonl(path: Path, objects: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for obj in objects:
            fh.write(json.dumps(obj) + "\n")


# ---------------------------------------------------------------------------
# Unit: math helpers
# ---------------------------------------------------------------------------

class TestMathHelpers:
    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_mean_single(self):
        assert _mean([0.5]) == pytest.approx(0.5)

    def test_mean_multi(self):
        assert _mean([0.0, 1.0]) == pytest.approx(0.5)

    def test_std_empty(self):
        assert _std([]) == 0.0

    def test_std_single(self):
        assert _std([0.5]) == 0.0

    def test_std_uniform(self):
        assert _std([0.5, 0.5, 0.5]) == pytest.approx(0.0)

    def test_std_known(self):
        # std([0, 1]) = sqrt(0.25) = 0.5
        assert _std([0.0, 1.0]) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Unit: relevance scorer
# ---------------------------------------------------------------------------

class TestRelevanceScore:
    def test_domain_match_contributes(self):
        obj = _make_obj(domain="ai_governance", risk_tags=["high"])
        score = _relevance_score(obj, keywords=[], domain="ai_governance", risk_tags=[])
        assert score >= 0.38  # ~0.40

    def test_domain_mismatch_zero_base(self):
        obj = _make_obj(domain="kubernetes", risk_tags=[])
        score = _relevance_score(obj, keywords=[], domain="ai_governance", risk_tags=[])
        assert score < 0.05

    def test_keyword_match(self):
        obj = _make_obj(title="Kubernetes pod security", content="admission webhook policy")
        score = _relevance_score(obj, keywords=["kubernetes", "admission"], domain=None, risk_tags=[])
        assert score > 0.1

    def test_risk_tag_overlap(self):
        obj = _make_obj(risk_tags=["critical", "destructive", "production"])
        score = _relevance_score(obj, keywords=[], domain=None, risk_tags=["critical", "production"])
        # Jaccard = 2/3 ≈ 0.667; contribution = 0.30 * 0.667 ≈ 0.20
        assert score >= 0.18

    def test_max_score_capped_at_1(self):
        obj = _make_obj(domain="sec", risk_tags=["a", "b", "c"], title="a b c d e f g h i j")
        score = _relevance_score(
            obj,
            keywords=["a", "b", "c", "d", "e", "f", "g"],
            domain="sec",
            risk_tags=["a", "b", "c"],
        )
        assert score <= 1.0


# ---------------------------------------------------------------------------
# Unit: zero result
# ---------------------------------------------------------------------------

def test_zero_result_signal():
    r = _zero_result("test")
    assert r.signal.evidence_strength == 0.0
    assert r.signal.citation_coverage == 0.0
    assert "test" in r.signal_source
    assert r.provenance is None


# ---------------------------------------------------------------------------
# Integration: provider loading
# ---------------------------------------------------------------------------

class TestStaticJsonlProviderLoading:
    def test_missing_file_graceful(self, tmp_path):
        p = StaticJsonlEvidenceProvider(jsonl_path=tmp_path / "nonexistent.jsonl")
        assert p.store_size == 0
        assert len(p.load_errors) > 0

    def test_empty_file_graceful(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        assert p.store_size == 0

    def test_comment_lines_ignored(self, tmp_path):
        path = tmp_path / "objs.jsonl"
        _write_jsonl(path, [_make_obj()])
        with path.open("a") as fh:
            fh.write("# this is a comment\n")
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        assert p.store_size == 1

    def test_invalid_json_skipped(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        with path.open("w") as fh:
            fh.write(json.dumps(_make_obj()) + "\n")
            fh.write("NOT JSON\n")
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        assert p.store_size == 1
        assert len(p.load_errors) == 1

    def test_invalid_json_strict_raises(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        with path.open("w") as fh:
            fh.write("NOT JSON\n")
        with pytest.raises(ValueError):
            StaticJsonlEvidenceProvider(jsonl_path=path, strict_load=True)

    def test_missing_field_skipped(self, tmp_path):
        obj = _make_obj()
        del obj["authority_score"]
        path = tmp_path / "missing.jsonl"
        _write_jsonl(path, [obj])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        assert p.store_size == 0
        assert len(p.load_errors) == 1

    def test_missing_field_strict_raises(self, tmp_path):
        obj = _make_obj()
        del obj["authority_score"]
        path = tmp_path / "missing.jsonl"
        _write_jsonl(path, [obj])
        with pytest.raises(ValueError):
            StaticJsonlEvidenceProvider(jsonl_path=path, strict_load=True)

    def test_multiple_objects_loaded(self, tmp_path):
        objects = [_make_obj(evidence_id=f"ev_{i:03d}") for i in range(10)]
        path = tmp_path / "multi.jsonl"
        _write_jsonl(path, objects)
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        assert p.store_size == 10


# ---------------------------------------------------------------------------
# Integration: fetch signal
# ---------------------------------------------------------------------------

class TestFetchSignal:
    def _provider(self, objects: list[dict], **kwargs) -> StaticJsonlEvidenceProvider:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for obj in objects:
            tmp.write(json.dumps(obj) + "\n")
        tmp.close()
        return StaticJsonlEvidenceProvider(jsonl_path=tmp.name, **kwargs)

    def test_returns_evidence_provider_result(self, tmp_path):
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, [_make_obj()])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="Should agent access AI governance policies?",
            domain="ai_governance",
            risk_tier="high",
            action_type="read",
            target_environment="production",
            oracle_responses=[],
        )
        assert isinstance(result, EvidenceProviderResult)

    def test_signal_source_is_retrieval(self, tmp_path):
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, [_make_obj()])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="AI governance",
            domain="ai_governance",
            risk_tier="high",
            action_type="read",
            target_environment=None,
            oracle_responses=[],
        )
        assert result.signal_source == "retrieval_static_jsonl"
        assert result.provenance is not None
        assert result.provenance["retrieval_strategy"] == "lexical_plus_semantic_rerank"
        assert result.provenance["semantic_scorer_version"]
        assert result.provenance["reranker_version"]
        assert len(result.provenance["evidence"]) >= 1

    def test_provenance_respects_top_k(self, tmp_path):
        objects = [_make_obj(evidence_id=f"ev_{i:03d}", domain="ai_governance") for i in range(8)]
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, objects)
        p = StaticJsonlEvidenceProvider(jsonl_path=path, top_k=3)
        result = p.fetch(
            question="AI governance policy controls",
            domain="ai_governance",
            risk_tier="high",
            action_type="policy_review",
            target_environment="production",
            oracle_responses=[],
        )
        assert result.provenance is not None
        ranked = result.provenance["evidence"]
        assert len(ranked) == 3
        assert ranked[0]["rerank_score"] >= ranked[-1]["rerank_score"]

    def test_no_match_returns_zero_signal(self, tmp_path):
        obj = _make_obj(domain="kubernetes", risk_tags=["k8s"])
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, [obj])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="completely unrelated topic about pizza recipes",
            domain="finance",
            risk_tier="low",
            action_type="read",
            target_environment=None,
            oracle_responses=[],
        )
        # Should get no_relevant_evidence or very low scores
        assert result.signal.evidence_strength == 0.0 or "no_relevant" in result.signal_source

    def test_high_authority_obj_raises_strength(self, tmp_path):
        obj = _make_obj(
            domain="ai_governance",
            authority_score=0.95,
            freshness_score=0.95,
            risk_tags=["governance", "policy"],
        )
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, [obj])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="AI governance policy",
            domain="ai_governance",
            risk_tier="high",
            action_type="policy_review",
            target_environment=None,
            oracle_responses=[],
        )
        assert result.signal.evidence_strength > 0.5

    def test_citation_coverage_capped_at_1(self, tmp_path):
        objects = [_make_obj(evidence_id=f"ev_{i:03d}", domain="ai_governance") for i in range(20)]
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, objects)
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="AI governance",
            domain="ai_governance",
            risk_tier="high",
            action_type="read",
            target_environment=None,
            oracle_responses=[],
        )
        assert result.signal.citation_coverage <= 1.0

    def test_top_k_limits_results(self, tmp_path):
        objects = [_make_obj(evidence_id=f"ev_{i:03d}", domain="ai_governance") for i in range(20)]
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, objects)
        p = StaticJsonlEvidenceProvider(jsonl_path=path, top_k=3)
        result = p.fetch(
            question="AI governance",
            domain="ai_governance",
            risk_tier="high",
            action_type="read",
            target_environment=None,
            oracle_responses=[],
        )
        # With 3 hits and MAX_USEFUL_CITATIONS=5: coverage = 3/5 = 0.6
        assert result.signal.citation_coverage == pytest.approx(0.6)

    def test_scores_are_rounded_to_3dp(self, tmp_path):
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, [_make_obj()])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="AI governance",
            domain="ai_governance",
            risk_tier="high",
            action_type="read",
            target_environment=None,
            oracle_responses=[],
        )
        sig = result.signal
        for field in ("evidence_strength", "contradiction_score", "citation_coverage",
                      "cross_evidence_consistency", "source_reliability"):
            val = getattr(sig, field)
            assert round(val, 3) == val, f"{field}={val} has more than 3 decimal places"

    def test_empty_store_returns_zero(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="test",
            domain=None,
            risk_tier=None,
            action_type=None,
            target_environment=None,
            oracle_responses=[],
        )
        assert result.signal.evidence_strength == 0.0

    def test_contradiction_score_from_objects(self, tmp_path):
        """High per-object contradiction_score propagates to signal."""
        obj = _make_obj(domain="ai_governance", contradiction_score=0.9)
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, [obj])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        result = p.fetch(
            question="AI governance",
            domain="ai_governance",
            risk_tier="high",
            action_type="read",
            target_environment=None,
            oracle_responses=[],
        )
        assert result.signal.contradiction_score > 0.5


# ---------------------------------------------------------------------------
# Integration: summary / diagnostics
# ---------------------------------------------------------------------------

class TestDiagnostics:
    def test_summary_keys(self, tmp_path):
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, [_make_obj()])
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        s = p.summary()
        assert "store_size" in s
        assert "loaded" in s
        assert "domains" in s
        assert "semantic_scorer_version" in s
        assert "reranker_version" in s

    def test_summary_domain_count(self, tmp_path):
        objects = [
            _make_obj(evidence_id="ev_001", domain="ai_governance"),
            _make_obj(evidence_id="ev_002", domain="ai_governance"),
            _make_obj(evidence_id="ev_003", domain="kubernetes"),
        ]
        path = tmp_path / "ev.jsonl"
        _write_jsonl(path, objects)
        p = StaticJsonlEvidenceProvider(jsonl_path=path)
        s = p.summary()
        assert s["domains"]["ai_governance"] == 2
        assert s["domains"]["kubernetes"] == 1


# ---------------------------------------------------------------------------
# Integration: importable from remora package
# ---------------------------------------------------------------------------

def test_importable_from_remora_package():
    from remora import StaticJsonlEvidenceProvider as SP  # noqa: F401
    assert SP is not None


def test_importable_from_evidence_subpackage():
    from remora.evidence import StaticJsonlEvidenceProvider as SP  # noqa: F401
    assert SP is not None


# ---------------------------------------------------------------------------
# Integration: against real dataset (skipped if file absent)
# ---------------------------------------------------------------------------

_DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "datasets"
    / "remora_knowledge_v1"
    / "evidence_packs"
    / "evidence_objects.jsonl"
)


@pytest.mark.skipif(not _DATASET_PATH.exists(), reason="Real dataset not present")
class TestRealDataset:
    def test_loads_without_errors(self):
        p = StaticJsonlEvidenceProvider()
        assert p.store_size > 0
        assert len(p.load_errors) == 0

    def test_kubernetes_query(self):
        p = StaticJsonlEvidenceProvider()
        result = p.fetch(
            question="Should agent execute kubectl delete namespace kube-system?",
            domain="kubernetes",
            risk_tier="critical",
            action_type="destructive_write",
            target_environment="production",
            oracle_responses=[],
        )
        assert result.signal_source == "retrieval_static_jsonl"

    def test_all_signals_in_range(self):
        p = StaticJsonlEvidenceProvider()
        result = p.fetch(
            question="Agent governance policy review",
            domain="ai_governance",
            risk_tier="medium",
            action_type="read",
            target_environment="staging",
            oracle_responses=[],
        )
        sig = result.signal
        for field in ("evidence_strength", "citation_coverage", "source_reliability",
                      "cross_evidence_consistency", "contradiction_score"):
            val = getattr(sig, field)
            assert 0.0 <= val <= 1.0, f"{field}={val} out of [0, 1]"
