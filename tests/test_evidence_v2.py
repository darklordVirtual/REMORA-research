# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for EvidenceOracleV2."""
from __future__ import annotations

from remora.oracles.evidence_v2 import (
    EvidenceOracleV2,
    EvidenceVerdict,
    detect_contradictions,
    extract_claims,
)
from remora.oracles.sources import Source, SourceCorpus


def _src(url: str, text: str) -> Source:
    return Source(url=url, text=text)


def test_extract_claims_splits_on_sentence_boundaries():
    text = "Paris is the capital of France. Berlin is the capital of Germany."
    claims = extract_claims(text)
    assert any("Paris" in c for c in claims)
    assert any("Berlin" in c for c in claims)
    assert len(claims) == 2


def test_detect_contradictions_flags_polarity_conflict():
    pos = ["The vaccine reduces transmission by 60%."]
    neg = ["The vaccine does not reduce transmission."]
    conflicts = detect_contradictions(pos + neg)
    assert conflicts >= 1


def test_evidence_oracle_abstains_without_supporting_source():
    corpus = SourceCorpus(sources=(
        _src("https://blog.example/a", "Unrelated content " * 50),
    ))
    oracle = EvidenceOracleV2(min_reliability=0.5, min_support=1)
    verdict = oracle.answer("Is the moon made of cheese?", corpus)
    assert isinstance(verdict, EvidenceVerdict)
    assert verdict.action == "abstain"
    assert verdict.cited_sources == ()


def test_evidence_oracle_answers_with_supporting_high_tier_source():
    text = (
        "The Eiffel Tower is located in Paris, France. "
        "It was completed in 1889 and stands 330 metres tall."
    ) * 10
    corpus = SourceCorpus(sources=(_src("https://www.gov.uk/eiffel", text),))
    oracle = EvidenceOracleV2(min_reliability=0.5, min_support=1)
    verdict = oracle.answer("Where is the Eiffel Tower located?", corpus)
    assert verdict.action == "answer"
    assert any("gov.uk" in s for s in verdict.cited_sources)


def test_evidence_oracle_abstains_under_contradiction():
    pos_text = "Drug X reduces blood pressure. " * 40
    neg_text = "Drug X does not reduce blood pressure. " * 40
    corpus = SourceCorpus(sources=(
        _src("https://www.nih.gov/p", pos_text),
        _src("https://www.nih.gov/n", neg_text),
    ))
    oracle = EvidenceOracleV2(min_reliability=0.5, min_support=1, max_contradictions=0)
    verdict = oracle.answer("Does Drug X reduce blood pressure?", corpus)
    assert verdict.action == "abstain"
    assert verdict.contradictions >= 1
