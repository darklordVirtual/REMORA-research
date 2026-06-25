from __future__ import annotations

# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for EvidenceOracleV3.

All tests use synthetic sources so no live network access is required.

URL tiers used:
  - "https://www.nih.gov/..."  → base=0.95 → score >= 0.665 even for short text (passes min_reliability=0.5)
  - "https://unknown.xyz/..."  → base=0.35 → score <= 0.35 for short text (fails min_reliability=0.5)
"""

import pytest

from remora.oracles.evidence_v3 import (
    EvidenceOracleV3,
    _lexical_score,
    _has_negation,
    _is_contradiction,
    _extract_sentences,
    _tokens,
)
from remora.oracles.sources import Source, SourceCorpus
from remora.oracles.evidence_verifier import EvidenceRelation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reliable_source(url_path: str, text: str) -> Source:
    """Return a source that passes min_reliability=0.5 (nih.gov tier)."""
    return Source(url=f"https://www.nih.gov/{url_path}", text=text)


def _unreliable_source(url_path: str, text: str) -> Source:
    """Return a source that fails min_reliability=0.5 (unknown domain)."""
    return Source(url=f"https://unknown.xyz/{url_path}", text=text)


def _oracle(**kwargs) -> EvidenceOracleV3:
    defaults = dict(min_reliability=0.5, min_support=2, lexical_threshold=0.15,
                    contradiction_threshold=0.30, top_k_per_source=5)
    defaults.update(kwargs)
    return EvidenceOracleV3(**defaults)


# ---------------------------------------------------------------------------
# Unit tests for private helpers
# ---------------------------------------------------------------------------

def test_tokens_filters_short_and_lowercases():
    result = _tokens("Hello WORLD a bc 123")
    assert "hello" in result
    assert "world" in result
    # single-char 'a' excluded
    assert "a" not in result
    # 'bc' length 2 — included
    assert "bc" in result


def test_lexical_score_identical_texts():
    assert _lexical_score("foo bar baz", "foo bar baz") == pytest.approx(1.0)


def test_lexical_score_disjoint_texts():
    assert _lexical_score("apple orange", "zebra mango") == pytest.approx(0.0)


def test_lexical_score_partial_overlap():
    score = _lexical_score("cat sat on the mat", "the cat sat")
    assert 0.0 < score < 1.0


def test_lexical_score_empty_strings():
    assert _lexical_score("", "some text") == pytest.approx(0.0)
    assert _lexical_score("some text", "") == pytest.approx(0.0)


def test_has_negation_positive():
    assert _has_negation("The drug does not reduce fever")
    assert _has_negation("There is no evidence")
    assert _has_negation("It cannot be confirmed")


def test_has_negation_negative():
    assert not _has_negation("The drug reduces fever significantly")


def test_is_contradiction_detects_negation_mismatch():
    claim = "The vaccine reduces transmission"
    snippet = "The vaccine does not reduce transmission"
    assert _is_contradiction(claim, snippet, overlap_threshold=0.20)


def test_is_contradiction_same_polarity_not_contradiction():
    claim = "The vaccine reduces transmission"
    snippet = "The vaccine reduces spread"
    assert not _is_contradiction(claim, snippet, overlap_threshold=0.20)


def test_extract_sentences_splits_correctly():
    text = "Paris is the capital. Berlin is also a capital! Is Rome a capital?"
    sentences = _extract_sentences(text)
    assert len(sentences) == 3
    assert any("Paris" in s for s in sentences)
    assert any("Berlin" in s for s in sentences)
    assert any("Rome" in s for s in sentences)


def test_extract_sentences_filters_empty():
    text = "One sentence."
    sentences = _extract_sentences(text)
    assert len(sentences) == 1
    assert sentences[0] == "One sentence"


# ---------------------------------------------------------------------------
# Integration tests for EvidenceOracleV3
# ---------------------------------------------------------------------------

# Test 1: answer with two independent support sources and no contradiction
def test_answer_with_two_independent_support_sources():
    claim_text = "Aspirin reduces inflammation in the body"
    src1 = _reliable_source(
        "aspirin1",
        ("Aspirin reduces inflammation in the body and is widely used as an "
         "anti-inflammatory agent. It works by inhibiting prostaglandins. " * 5),
    )
    src2 = _reliable_source(
        "aspirin2",
        ("Clinical studies show aspirin reduces inflammation in patients. "
         "The anti-inflammatory effect is well documented. " * 5),
    )
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle(min_support=2)
    decision = oracle.evaluate("Does aspirin reduce inflammation?", claim_text, corpus)
    assert decision.action == "answer"


# Test 2: abstain when no source meets reliability
def test_abstain_when_no_source_meets_reliability():
    src = _unreliable_source("page1", "Aspirin reduces inflammation in the body. " * 3)
    corpus = SourceCorpus(sources=(src,))
    oracle = _oracle(min_reliability=0.5)
    decision = oracle.evaluate("Does aspirin reduce inflammation?",
                               "Aspirin reduces inflammation.", corpus)
    assert decision.action == "abstain"
    assert "no_reliable_sources" in decision.reason


# Test 3: verify/abstain when the majority of atomic claims are unsupported
# Uses 3 claims: 1 supported + 2 unsupported → 2 > 3/2 = 1.5 triggers verify/abstain
def test_verify_or_abstain_when_one_claim_unsupported():
    supported_text = "Water boils at one hundred degrees Celsius"
    unsupported_text1 = "Unicorns are real creatures that fly through space"
    unsupported_text2 = "Dragons breathe purple fire every Tuesday morning"
    candidate = f"{supported_text}. {unsupported_text1}. {unsupported_text2}."

    src1 = _reliable_source(
        "water1",
        ("Water boils at one hundred degrees Celsius under standard pressure. "
         "This temperature threshold is a physical constant. " * 5),
    )
    src2 = _reliable_source(
        "water2",
        ("The boiling point of water is one hundred degrees Celsius. "
         "Water transitions to steam at this temperature. " * 5),
    )
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle(min_support=2)
    decision = oracle.evaluate("At what temperature does water boil?", candidate, corpus)
    assert decision.action in ("verify", "abstain")


# Test 4: abstain when contradiction exists
def test_abstain_when_contradiction_exists():
    claim = "Drug X reduces blood pressure effectively"
    # Source with matching but negated content
    src1 = _reliable_source(
        "drugx1",
        ("Drug X reduces blood pressure effectively in clinical trials. "
         "Patients show improved outcomes. " * 5),
    )
    src2 = _reliable_source(
        "drugx2",
        ("Drug X does not reduce blood pressure effectively. "
         "Studies show no significant improvement. " * 5),
    )
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle(min_support=1, contradiction_threshold=0.20)
    decision = oracle.evaluate("Does Drug X reduce blood pressure?", claim, corpus)
    assert decision.action == "abstain"
    assert "contradiction" in decision.reason


# Test 5: multiple claims produce per-claim evidence rows
def test_multiple_claims_produce_per_claim_evidence_rows():
    candidate = (
        "Water is a molecule. "
        "Oxygen is a gas. "
        "Hydrogen is the lightest element."
    )
    src1 = _reliable_source(
        "chemistry1",
        "Water is a molecule consisting of hydrogen and oxygen. " * 10,
    )
    src2 = _reliable_source(
        "chemistry2",
        "Oxygen is a gas at room temperature. Hydrogen is the lightest element. " * 10,
    )
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle()
    decision = oracle.evaluate("Basic chemistry facts?", candidate, corpus)
    assert len(decision.per_claim_evidence) == 3


# Test 6: cited_sources are stable and sorted
def test_cited_sources_are_sorted():
    src1 = _reliable_source(
        "zzz",
        "Aspirin reduces inflammation and pain. " * 10,
    )
    src2 = _reliable_source(
        "aaa",
        "Aspirin is an anti-inflammatory medication. Reduces pain and inflammation. " * 10,
    )
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle(min_support=1)
    decision = oracle.evaluate(
        "What does aspirin do?",
        "Aspirin reduces inflammation.",
        corpus,
    )
    assert decision.cited_sources == tuple(sorted(decision.cited_sources))


# Test 7: empty corpus → abstain
def test_empty_corpus_abstains():
    corpus = SourceCorpus(sources=())
    oracle = _oracle()
    decision = oracle.evaluate("Any question?", "Any answer.", corpus)
    assert decision.action == "abstain"


# Test 8: single-word answer produces at least one atomic claim
def test_single_word_answer_produces_at_least_one_claim():
    src1 = _reliable_source("yes1", "Yes this is confirmed. " * 10)
    src2 = _reliable_source("yes2", "Yes that is correct. " * 10)
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle()
    decision = oracle.evaluate("Is this true?", "Yes.", corpus)
    assert len(decision.per_claim_evidence) >= 1


# Test 9: unsupported_claims contains the unsupported claim text
def test_unsupported_claims_contains_the_unsupported_claim_text():
    unsupported_sentence = "Invisible dragons guard the moon from all intruders"
    supported_sentence = "Water boils at one hundred degrees Celsius"
    candidate = f"{supported_sentence}. {unsupported_sentence}."

    src1 = _reliable_source(
        "w1",
        ("Water boils at one hundred degrees Celsius under standard conditions. "
         "This is a fundamental physical property. " * 5),
    )
    src2 = _reliable_source(
        "w2",
        ("The boiling point of water is one hundred degrees Celsius. "
         "Temperature causes water to evaporate. " * 5),
    )
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle(min_support=2)
    decision = oracle.evaluate("Temperature question?", candidate, corpus)
    # The unsupported sentence text should appear somewhere in unsupported_claims
    assert any(unsupported_sentence in c for c in decision.unsupported_claims)


# Test 10: lexical_support_score is between 0 and 1 for all snippets
def test_lexical_support_score_in_unit_interval():
    candidate = "Aspirin reduces pain and inflammation in patients."
    src1 = _reliable_source(
        "asp1",
        "Aspirin reduces pain and inflammation. It is widely used. " * 10,
    )
    src2 = _reliable_source(
        "asp2",
        "Aspirin is an analgesic that reduces inflammation effectively. " * 10,
    )
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle(min_support=1)
    decision = oracle.evaluate("What does aspirin do?", candidate, corpus)

    for ce in decision.per_claim_evidence:
        for snippet in ce.supporting_snippets + ce.contradicting_snippets:
            assert 0.0 <= snippet.lexical_support_score <= 1.0, (
                f"Score out of range: {snippet.lexical_support_score}"
            )


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

def test_pluggable_relation_fn_is_used():
    """When a custom relation_fn always returns True, all snippets are contradictions."""
    candidate = "Water is wet."
    src1 = _reliable_source("wet1", "Water is wet and flows freely. " * 10)
    src2 = _reliable_source("wet2", "Water is a liquid substance. " * 10)
    corpus = SourceCorpus(sources=(src1, src2))

    def always_contradict(claim: str, snippet: str, threshold: float) -> bool:  # noqa: ARG001
        return True

    oracle = EvidenceOracleV3(
        min_reliability=0.5,
        min_support=2,
        relation_fn=always_contradict,
    )
    decision = oracle.evaluate("Is water wet?", candidate, corpus)
    # All snippets flagged as contradictions → abstain
    assert decision.action == "abstain"
    assert "contradiction" in decision.reason


def test_decision_is_frozen_dataclass():
    """EvidenceDecision is frozen (immutable)."""
    src1 = _reliable_source("fr1", "Paris is the capital of France. " * 10)
    src2 = _reliable_source("fr2", "France is a country in Europe with capital Paris. " * 10)
    corpus = SourceCorpus(sources=(src1, src2))
    oracle = _oracle(min_support=1)
    decision = oracle.evaluate("Capital of France?", "Paris is the capital of France.", corpus)
    with pytest.raises((AttributeError, TypeError)):
        decision.action = "mutated"  # type: ignore[misc]


class _ForcedVerifier:
    def __init__(self, relation: EvidenceRelation) -> None:
        self.relation = relation

    def classify(self, claim: str, snippet: str) -> EvidenceRelation:
        return self.relation


def test_custom_verifier_can_force_supports():
    corpus = SourceCorpus(sources=(
        _reliable_source("force1", "Unrelated but reliable text from a clinical public source. " * 30),
        _reliable_source("force2", "Another unrelated reliable text from a clinical public source. " * 30),
    ))
    oracle = _oracle(min_support=2, verifier=_ForcedVerifier("supports"))
    decision = oracle.evaluate("q", "A claim with no lexical support.", corpus)
    assert decision.action == "answer"


def test_custom_verifier_can_force_contradiction():
    corpus = SourceCorpus(sources=(
        _reliable_source("forcec1", "Reliable text. " * 10),
    ))
    oracle = _oracle(min_support=1, verifier=_ForcedVerifier("contradicts"))
    decision = oracle.evaluate("q", "A claim.", corpus)
    assert decision.action == "abstain"
    assert decision.reason == "contradiction_detected"
