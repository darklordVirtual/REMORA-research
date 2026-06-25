"""Tests for Decision Provenance DAG."""
import pytest

from remora.audit.provenance_dag import EdgeType, ProvenanceDAG


class TestProvenanceDAG:
    def test_add_root_node(self):
        dag = ProvenanceDAG()
        node = dag.add_node("hash_a", domain="finance", outcome="ACCEPTED")
        assert dag.size == 1
        assert node.node_id in dag.roots
        assert node.envelope_hash == "hash_a"

    def test_add_child_node(self):
        dag = ProvenanceDAG()
        parent = dag.add_node("hash_a")
        child = dag.add_node("hash_b", parent_ids=[parent.node_id], edge_types=[EdgeType.DELEGATION])
        assert dag.size == 2
        assert child.parent_ids == (parent.node_id,)
        assert child.node_id not in dag.roots

    def test_invalid_parent_raises(self):
        dag = ProvenanceDAG()
        with pytest.raises(ValueError, match="not found"):
            dag.add_node("hash_a", parent_ids=["nonexistent"])

    def test_get_ancestors(self):
        dag = ProvenanceDAG()
        a = dag.add_node("h1")
        b = dag.add_node("h2", parent_ids=[a.node_id])
        c = dag.add_node("h3", parent_ids=[b.node_id])
        ancestors = dag.get_ancestors(c.node_id)
        ancestor_ids = {n.node_id for n in ancestors}
        assert a.node_id in ancestor_ids
        assert b.node_id in ancestor_ids

    def test_get_descendants(self):
        dag = ProvenanceDAG()
        a = dag.add_node("h1")
        b = dag.add_node("h2", parent_ids=[a.node_id])
        c = dag.add_node("h3", parent_ids=[a.node_id])
        descendants = dag.get_descendants(a.node_id)
        desc_ids = {n.node_id for n in descendants}
        assert b.node_id in desc_ids
        assert c.node_id in desc_ids

    def test_merkle_root_changes_on_add(self):
        dag = ProvenanceDAG()
        dag.add_node("h1")
        root1 = dag.merkle_root()
        dag.add_node("h2")
        root2 = dag.merkle_root()
        assert root1 != root2

    def test_merkle_proof(self):
        dag = ProvenanceDAG()
        a = dag.add_node("h1")
        b = dag.add_node("h2", parent_ids=[a.node_id])
        proof = dag.merkle_proof(b.node_id)
        assert len(proof) >= 1
        assert proof[0]["node_id"] == b.node_id

    def test_merkle_proof_nonexistent_raises(self):
        dag = ProvenanceDAG()
        with pytest.raises(ValueError):
            dag.merkle_proof("nonexistent")

    def test_verify_integrity_clean(self):
        dag = ProvenanceDAG()
        a = dag.add_node("h1")
        dag.add_node("h2", parent_ids=[a.node_id])
        valid, errors = dag.verify_integrity()
        assert valid
        assert errors == []

    def test_extract_subtree(self):
        dag = ProvenanceDAG()
        a = dag.add_node("h1")
        b = dag.add_node("h2", parent_ids=[a.node_id])
        dag.add_node("h3", parent_ids=[b.node_id])
        dag.add_node("h4")  # unrelated

        sub = dag.extract_subtree(b.node_id)
        assert sub.size == 2  # b and c
        assert b.node_id in sub.roots

    def test_multiple_parents(self):
        dag = ProvenanceDAG()
        a = dag.add_node("h1")
        b = dag.add_node("h2")
        c = dag.add_node("h3", parent_ids=[a.node_id, b.node_id], edge_types=[EdgeType.EVIDENCE, EdgeType.POLICY_INHERIT])
        assert len(c.parent_ids) == 2
        assert len(c.edge_types) == 2

    def test_to_dict(self):
        dag = ProvenanceDAG()
        dag.add_node("h1")
        d = dag.to_dict()
        assert "merkle_root" in d
        assert "size" in d
        assert d["size"] == 1

    def test_empty_dag_merkle_root(self):
        dag = ProvenanceDAG()
        root = dag.merkle_root()
        assert root  # non-empty hash
