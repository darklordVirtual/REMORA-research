# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for claim-relation inference primitives."""
from __future__ import annotations

from remora.graph.relations import Relation, infer_relation


def test_infer_relation_returns_contradicts_for_polarity_flip():
    a = "Coffee improves memory."
    b = "Coffee does not improve memory."
    rel = infer_relation(a, b)
    assert rel == Relation.CONTRADICTS


def test_infer_relation_returns_supports_for_similar_polarity():
    a = "Coffee improves memory."
    b = "Coffee enhances memory recall."
    rel = infer_relation(a, b)
    assert rel == Relation.SUPPORTS


def test_infer_relation_returns_unrelated_for_disjoint_topics():
    a = "The Eiffel Tower is in Paris."
    b = "Photosynthesis converts light to chemical energy."
    rel = infer_relation(a, b)
    assert rel == Relation.UNRELATED


def test_infer_relation_entailment_for_subset_phrasing():
    a = "All mammals are vertebrates."
    b = "All mammals are vertebrates with backbones."
    rel = infer_relation(a, b)
    assert rel in (Relation.ENTAILS, Relation.SUPPORTS)


def test_infer_relation_empty_string_returns_unrelated():
    rel = infer_relation("", "Something")
    assert rel == Relation.UNRELATED


def test_infer_relation_returns_refutes_for_negated_subset():
    a = "No mammals are not vertebrates."
    b = "No mammals are not vertebrates with backbones."
    rel = infer_relation(a, b)
    assert rel == Relation.REFUTES
