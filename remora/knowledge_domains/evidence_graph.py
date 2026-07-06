# Author: Stian Skogbrott
# License: Apache-2.0
"""Evidence-as-a-graph integrity for a claim register.

Claims, artifacts, literature and docs are nodes; binds/backed_by/cites are
edges. Once evidence is a graph you can ask structural questions a flat register
cannot — is any claim an orphan (bound in a doc, backed by no artifact)? what is
the deepest evidence chain? Operates on a committed fixture so results are
stable; the same builder runs on a real register exported to the same shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Committed fixture (6 claims, all backed -> 0 orphans).
FIXTURE: tuple[dict, ...] = (
    {"id": "CLAIM-A", "artifacts": ["a.json"], "literature": ["doi:10.1/x"], "docs": ["a.md"]},
    {"id": "CLAIM-B", "artifacts": ["b.json"], "literature": [], "docs": ["a.md"]},
    {"id": "CLAIM-C", "artifacts": ["c.json", "c2.json"], "literature": [], "docs": ["c.md"]},
    {"id": "CLAIM-D", "artifacts": ["d.json"], "literature": ["doi:10.1/y"], "docs": ["d.md"]},
    {"id": "CLAIM-E", "artifacts": ["a.json"], "literature": [], "docs": ["e.md"]},
    {"id": "CLAIM-F", "artifacts": ["f.json"], "literature": [], "docs": ["d.md"]},
)

Node = tuple[str, str]


@dataclass
class Graph:
    nodes: set[Node] = field(default_factory=set)
    edges: set[tuple[Node, str, Node]] = field(default_factory=set)

    def add_node(self, kind: str, ident: str) -> Node:
        node = (kind, ident)
        self.nodes.add(node)
        return node

    def add_edge(self, src: Node, rel: str, dst: Node) -> None:
        self.edges.add((src, rel, dst))


def build_graph(claims: tuple[dict, ...]) -> Graph:
    g = Graph()
    for c in claims:
        claim = g.add_node("claim", c["id"])
        for art in c.get("artifacts", []):
            g.add_edge(claim, "backed_by", g.add_node("artifact", art))
        for lit in c.get("literature", []):
            g.add_edge(claim, "cites", g.add_node("literature", lit))
        for doc in c.get("docs", []):
            g.add_edge(g.add_node("doc", doc), "binds", claim)
    return g


def orphan_claims(g: Graph) -> list[str]:
    backed = {src[1] for src, rel, _ in g.edges if rel == "backed_by"}
    return sorted(
        ident for kind, ident in g.nodes if kind == "claim" and ident not in backed
    )


def max_evidence_depth(g: Graph) -> int:
    succ: dict[Node, list[Node]] = {}
    for src, _rel, dst in g.edges:
        succ.setdefault(src, []).append(dst)

    def depth(node: Node, seen: frozenset[Node]) -> int:
        if node in seen:
            return 0
        return max((1 + depth(n, seen | {node}) for n in succ.get(node, ())), default=0)

    return max((depth(n, frozenset()) for n in g.nodes), default=0)


def metrics(g: Graph) -> dict[str, int]:
    return {
        "n_nodes": len(g.nodes),
        "n_edges": len(g.edges),
        "n_claims": sum(1 for k, _ in g.nodes if k == "claim"),
        "orphan_claims": len(orphan_claims(g)),
        "max_evidence_depth": max_evidence_depth(g),
    }
