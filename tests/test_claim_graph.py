# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for SemanticClaimGraph cycle / Betti computation."""
from __future__ import annotations

import pytest

from remora.graph.claim_graph import SemanticClaimGraph
from remora.graph.relations import Relation


def test_empty_graph_has_zero_betti():
    g = SemanticClaimGraph()
    b = g.betti()
    assert b["betti_0"] == 0
    assert b["betti_1"] == 0


def test_single_isolated_node_has_one_component():
    g = SemanticClaimGraph()
    g.add_claim("a", "Coffee improves memory.")
    b = g.betti()
    assert b["betti_0"] == 1
    assert b["betti_1"] == 0


def test_two_connected_nodes_have_one_component_and_no_cycle():
    g = SemanticClaimGraph()
    g.add_claim("a", "Coffee improves memory.")
    g.add_claim("b", "Coffee enhances memory recall.")
    g.add_edge("a", "b", Relation.SUPPORTS)
    b = g.betti()
    assert b["betti_0"] == 1
    assert b["betti_1"] == 0


def test_triangle_with_contradiction_yields_one_cycle():
    g = SemanticClaimGraph()
    g.add_claim("a", "X causes Y.")
    g.add_claim("b", "Y causes Z.")
    g.add_claim("c", "X does not cause Z.")
    g.add_edge("a", "b", Relation.ENTAILS)
    g.add_edge("b", "c", Relation.ENTAILS)
    g.add_edge("a", "c", Relation.CONTRADICTS)
    b = g.betti()
    assert b["betti_0"] == 1
    assert b["betti_1"] == 1
    assert g.contradiction_cycle_count() >= 1


def test_two_disconnected_components():
    g = SemanticClaimGraph()
    g.add_claim("a", "A1")
    g.add_claim("b", "B1")
    g.add_claim("c", "C1")
    g.add_claim("d", "D1")
    g.add_edge("a", "b", Relation.SUPPORTS)
    g.add_edge("c", "d", Relation.SUPPORTS)
    b = g.betti()
    assert b["betti_0"] == 2
    assert b["betti_1"] == 0


def test_add_edge_unknown_node_raises_key_error():
    g = SemanticClaimGraph()
    g.add_claim("a", "A claim.")
    with pytest.raises(KeyError):
        g.add_edge("a", "missing", Relation.SUPPORTS)


def test_add_edge_self_loop_is_silently_ignored():
    g = SemanticClaimGraph()
    g.add_claim("a", "A claim.")
    g.add_edge("a", "a", Relation.SUPPORTS)
    b = g.betti()
    assert b["betti_0"] == 1
    assert b["betti_1"] == 0


def test_contradiction_cycle_count_zero_with_no_contradicts_edge():
    g = SemanticClaimGraph()
    g.add_claim("a", "A.")
    g.add_claim("b", "B.")
    g.add_claim("c", "C.")
    g.add_edge("a", "b", Relation.SUPPORTS)
    g.add_edge("b", "c", Relation.SUPPORTS)
    g.add_edge("a", "c", Relation.ENTAILS)
    b = g.betti()
    assert b["betti_1"] == 1
    assert g.contradiction_cycle_count() == 0
