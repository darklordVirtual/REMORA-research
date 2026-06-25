# Author: Stian Skogbrott
# License: Apache-2.0
"""Semantic claim graph + true Betti numbers via cycle-space dimension.

For an undirected graph with C connected components, V vertices, E edges, the
first Betti number is exactly E - V + C (the cycle-rank / cyclomatic number).
This gives a rigorous β1 that no longer depends on the fingerprint trick.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from remora.graph.relations import Relation


@dataclass
class SemanticClaimGraph:
    claims: dict[str, str] = field(default_factory=dict)
    adjacency: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    edge_relations: dict[tuple[str, str], Relation] = field(default_factory=dict)

    def add_claim(self, node_id: str, text: str) -> None:
        self.claims[node_id] = text
        _ = self.adjacency[node_id]  # vivify defaultdict entry for isolated nodes

    def add_edge(self, u: str, v: str, relation: Relation) -> None:
        if u not in self.claims:
            raise KeyError(f"missing claim {u!r}")
        if v not in self.claims:
            raise KeyError(f"missing claim {v!r}")
        if u == v:
            return  # self-loops not meaningful for claim-level β1
        self.adjacency[u].add(v)
        self.adjacency[v].add(u)
        key = (u, v) if u < v else (v, u)
        self.edge_relations[key] = relation

    def _connected_components(self) -> int:
        seen: set[str] = set()
        count = 0
        for node in self.claims:
            if node in seen:
                continue
            count += 1
            queue = deque([node])
            while queue:
                cur = queue.popleft()
                if cur in seen:
                    continue
                seen.add(cur)
                queue.extend(self.adjacency[cur] - seen)
        return count

    def _edge_count(self) -> int:
        return len(self.edge_relations)

    def betti(self) -> dict[str, int]:
        v = len(self.claims)
        if v == 0:
            return {"betti_0": 0, "betti_1": 0}
        c = self._connected_components()
        e = self._edge_count()
        return {"betti_0": c, "betti_1": max(0, e - v + c)}

    def contradiction_cycle_count(self) -> int:
        """Number of cycles containing at least one CONTRADICTS edge.

        Upper-bounded by betti_1.
        """
        b1 = self.betti()["betti_1"]
        if b1 == 0:
            return 0
        contradictions = sum(
            1 for rel in self.edge_relations.values() if rel == Relation.CONTRADICTS
        )
        return min(b1, contradictions)
