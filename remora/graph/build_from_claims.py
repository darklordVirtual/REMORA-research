from __future__ import annotations
from remora.graph.claim_graph import SemanticClaimGraph
from remora.graph.relations import infer_relation, Relation

def build_claim_graph(claims: list[str], relation_fn=infer_relation) -> SemanticClaimGraph:
    g = SemanticClaimGraph()
    for i, text in enumerate(claims):
        g.add_claim(str(i), text)
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            rel = relation_fn(claims[i], claims[j])
            if rel != Relation.UNRELATED:
                g.add_edge(str(i), str(j), rel)
    return g

def graph_metrics_for_claims(claims: list[str]) -> dict:
    if not claims:
        return {"n_claims": 0, "n_edges": 0, "betti_0": 0, "betti_1": 0,
                "contradiction_cycles": 0, "relation_counts": {}}
    g = build_claim_graph(claims)
    betti = g.betti()
    rel_counts: dict[str, int] = {}
    for rel in g.edge_relations.values():
        rel_counts[rel.value] = rel_counts.get(rel.value, 0) + 1
    return {
        "n_claims": len(claims),
        "n_edges": g._edge_count(),
        "betti_0": betti["betti_0"],
        "betti_1": betti["betti_1"],
        "contradiction_cycles": g.contradiction_cycle_count(),
        "relation_counts": rel_counts,
    }
