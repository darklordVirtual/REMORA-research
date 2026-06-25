"""Decision Provenance DAG with Merkle verification for REMORA.

Upgrades from a linear hash chain to a directed acyclic graph (DAG) of
decision provenance. Each DecisionEnvelope becomes a node; edges represent
causal relationships (delegation, evidence dependency, policy inheritance).

This enables:
- Selective audit: verify any sub-tree without replaying the entire chain
- Cross-envelope verification: prove that envelope B depended on envelope A
- Parallel decision tracking: multiple independent decision streams merge
- Efficient incremental proofs: Merkle paths for any node in O(log n)

The DAG is append-only and tamper-evident via Merkle hashing.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class ProvenanceNode:
    """A node in the provenance DAG representing one decision."""

    node_id: str  # SHA-256 content hash
    envelope_hash: str  # hash of the associated DecisionEnvelope
    parent_ids: tuple[str, ...] = ()  # IDs of parent nodes (causal dependencies)
    edge_types: tuple[str, ...] = ()  # type of each parent edge
    timestamp: float = 0.0
    domain: str = ""
    outcome: str = ""  # ACCEPTED, VERIFIED, ABSTAINED, ESCALATED
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EdgeType:
    """Constants for edge types in the provenance DAG."""

    DELEGATION = "delegation"  # agent A delegated to agent B
    EVIDENCE = "evidence"  # decision depended on evidence from another decision
    POLICY_INHERIT = "policy_inherit"  # policy constraints inherited
    REVIEW = "review"  # human review of a prior decision
    REPLAY = "replay"  # shadow-mode replay of a prior decision
    CORRECTION = "correction"  # corrects a prior decision
    CONTINUATION = "continuation"  # sequential continuation


class ProvenanceDAG:
    """Append-only DAG of decision provenance with Merkle verification.

    Each node is content-addressed (SHA-256 of its serialized form).
    Parent references create edges. The DAG supports:
    - O(1) node lookup
    - O(depth) Merkle path generation for any node
    - O(n) full integrity verification
    - Sub-tree extraction for selective audit
    """

    def __init__(self) -> None:
        self._nodes: dict[str, ProvenanceNode] = {}
        self._children: dict[str, list[str]] = {}  # parent_id -> [child_ids]
        self._roots: set[str] = set()  # nodes with no parents
        self._merkle_cache: dict[str, str] = {}

    @property
    def size(self) -> int:
        return len(self._nodes)

    @property
    def roots(self) -> list[str]:
        return sorted(self._roots)

    def _content_hash(self, envelope_hash: str, parent_ids: tuple[str, ...], timestamp: float) -> str:
        content = json.dumps({
            "envelope_hash": envelope_hash,
            "parent_ids": list(parent_ids),
            "timestamp": timestamp,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()

    def _merkle_hash(self, node_id: str) -> str:
        """Compute Merkle hash for a node (hash of self + children)."""
        if node_id in self._merkle_cache:
            return self._merkle_cache[node_id]

        node = self._nodes[node_id]
        child_hashes = sorted(self._merkle_hash(c) for c in self._children.get(node_id, []))
        combined = json.dumps({
            "node": node.node_id,
            "envelope": node.envelope_hash,
            "children": child_hashes,
        }, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(combined.encode()).hexdigest()
        self._merkle_cache[node_id] = h
        return h

    def add_node(
        self,
        envelope_hash: str,
        *,
        parent_ids: tuple[str, ...] | list[str] = (),
        edge_types: tuple[str, ...] | list[str] = (),
        domain: str = "",
        outcome: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProvenanceNode:
        """Add a new decision node to the DAG.

        Raises ValueError if any parent_id doesn't exist (enforces DAG integrity).
        """
        parent_ids = tuple(parent_ids)
        edge_types = tuple(edge_types)

        # Validate parents exist
        for pid in parent_ids:
            if pid not in self._nodes:
                raise ValueError(f"Parent node {pid!r} not found in DAG")

        ts = time.time()
        node_id = self._content_hash(envelope_hash, parent_ids, ts)

        node = ProvenanceNode(
            node_id=node_id,
            envelope_hash=envelope_hash,
            parent_ids=parent_ids,
            edge_types=edge_types,
            timestamp=ts,
            domain=domain,
            outcome=outcome,
            metadata=metadata or {},
        )

        self._nodes[node_id] = node

        # Update children index
        for pid in parent_ids:
            self._children.setdefault(pid, []).append(node_id)

        if not parent_ids:
            self._roots.add(node_id)

        # Invalidate Merkle cache up the chain
        self._merkle_cache.clear()

        return node

    def get_node(self, node_id: str) -> ProvenanceNode | None:
        return self._nodes.get(node_id)

    def get_ancestors(self, node_id: str) -> list[ProvenanceNode]:
        """Get all ancestors of a node (transitive parents)."""
        visited: set[str] = set()
        result: list[ProvenanceNode] = []
        stack = [node_id]
        while stack:
            nid = stack.pop()
            node = self._nodes.get(nid)
            if node is None:
                continue
            for pid in node.parent_ids:
                if pid not in visited:
                    visited.add(pid)
                    result.append(self._nodes[pid])
                    stack.append(pid)
        return result

    def get_descendants(self, node_id: str) -> list[ProvenanceNode]:
        """Get all descendants of a node."""
        visited: set[str] = set()
        result: list[ProvenanceNode] = []
        stack = list(self._children.get(node_id, []))
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            result.append(self._nodes[nid])
            stack.extend(self._children.get(nid, []))
        return result

    def merkle_root(self) -> str:
        """Compute the Merkle root of the entire DAG.

        Combines Merkle hashes of all root nodes.
        """
        if not self._roots:
            return hashlib.sha256(b"empty_dag").hexdigest()
        root_hashes = sorted(self._merkle_hash(r) for r in self._roots)
        combined = json.dumps(root_hashes, separators=(",", ":"))
        return hashlib.sha256(combined.encode()).hexdigest()

    def merkle_proof(self, node_id: str) -> list[dict[str, str]]:
        """Generate a Merkle inclusion proof for a node.

        Returns a list of {node_id, hash} pairs from the node to a root.
        """
        if node_id not in self._nodes:
            raise ValueError(f"Node {node_id!r} not in DAG")

        proof = [{"node_id": node_id, "hash": self._merkle_hash(node_id)}]
        node = self._nodes[node_id]
        for pid in node.parent_ids:
            proof.append({"node_id": pid, "hash": self._merkle_hash(pid)})

        return proof

    def verify_integrity(self) -> tuple[bool, list[str]]:
        """Verify full DAG integrity.

        Returns (is_valid, list_of_errors).
        """
        errors: list[str] = []
        for nid, node in self._nodes.items():
            # Verify parent references exist
            for pid in node.parent_ids:
                if pid not in self._nodes:
                    errors.append(f"Node {nid}: parent {pid} not found")
            # Verify no cycles (simple check via ancestors)
            ancestors = {a.node_id for a in self.get_ancestors(nid)}
            if nid in ancestors:
                errors.append(f"Node {nid}: cycle detected")

        return len(errors) == 0, errors

    def extract_subtree(self, node_id: str) -> "ProvenanceDAG":
        """Extract a sub-DAG rooted at the given node (for selective audit)."""
        sub = ProvenanceDAG()
        descendants = [self._nodes[node_id]] + self.get_descendants(node_id)
        node_ids_in_sub = {d.node_id for d in descendants}

        for d in descendants:
            # Only include parent refs that are in the subtree
            filtered_parents = tuple(p for p in d.parent_ids if p in node_ids_in_sub)
            filtered_edges = tuple(
                e for p, e in zip(d.parent_ids, d.edge_types) if p in node_ids_in_sub
            ) if d.edge_types else ()

            node = ProvenanceNode(
                node_id=d.node_id,
                envelope_hash=d.envelope_hash,
                parent_ids=filtered_parents,
                edge_types=filtered_edges,
                timestamp=d.timestamp,
                domain=d.domain,
                outcome=d.outcome,
                metadata=d.metadata,
            )
            sub._nodes[node.node_id] = node
            if not filtered_parents:
                sub._roots.add(node.node_id)
            for pid in filtered_parents:
                sub._children.setdefault(pid, []).append(node.node_id)

        return sub

    def to_dict(self) -> dict[str, Any]:
        """Serialize the DAG for persistence or API response."""
        return {
            "merkle_root": self.merkle_root(),
            "size": self.size,
            "roots": self.roots,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
        }
