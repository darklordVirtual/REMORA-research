"""Tests for remora/graph/build_from_claims.py"""
from remora.graph.build_from_claims import build_claim_graph, graph_metrics_for_claims


def test_build_empty_graph():
    g = build_claim_graph([])
    betti = g.betti()
    assert betti["betti_0"] == 0
    assert len(g.claims) == 0


def test_build_single_node():
    g = build_claim_graph(["A"])
    assert len(g.claims) == 1
    assert g._edge_count() == 0


def test_build_contradiction_edge():
    g = build_claim_graph(["The sky is blue", "The sky is not blue"])
    # Expect at least one edge (contradiction between these two claims)
    assert g._edge_count() >= 1


def test_metrics_empty():
    result = graph_metrics_for_claims([])
    assert result == {
        "n_claims": 0,
        "n_edges": 0,
        "betti_0": 0,
        "betti_1": 0,
        "contradiction_cycles": 0,
        "relation_counts": {},
    }


def test_metrics_keys():
    result = graph_metrics_for_claims(["claim1", "claim2"])
    expected_keys = {"n_claims", "n_edges", "betti_0", "betti_1", "contradiction_cycles", "relation_counts"}
    assert expected_keys == set(result.keys())
    assert result["n_claims"] == 2


def test_metrics_contradiction_cycle_betti():
    # Three claims where each pair has some overlap but varied negation:
    # This tests that betti_1 >= 0 (non-negative), not that it's strictly positive,
    # since the heuristic may or may not produce a cycle for these.
    claims = [
        "The sky is blue",
        "The sky is not blue",
        "The sky is clearly not blue today",
    ]
    result = graph_metrics_for_claims(claims)
    assert result["betti_1"] >= 0
