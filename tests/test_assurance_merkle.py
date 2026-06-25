# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for binary Merkle tree + inclusion proofs."""
from __future__ import annotations

import pytest

from remora.assurance.merkle import (
    MerkleProof,
    build_merkle_tree,
    verify_inclusion,
)


def test_single_leaf_root_equals_leaf_hash():
    tree = build_merkle_tree([b"hello"])
    assert tree.root == tree.leaves[0]


def test_two_leaves_root_is_hash_of_pair():
    tree = build_merkle_tree([b"a", b"b"])
    import hashlib
    expected = hashlib.sha256((tree.leaves[0] + tree.leaves[1]).encode("utf-8")).hexdigest()
    assert tree.root == expected


def test_proof_for_each_leaf_verifies_against_root():
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    tree = build_merkle_tree(leaves)
    for i, leaf in enumerate(leaves):
        proof = tree.proof(i)
        assert isinstance(proof, MerkleProof)
        assert verify_inclusion(leaf, proof, tree.root)


def test_proof_fails_on_tampered_leaf():
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    tree = build_merkle_tree(leaves)
    proof = tree.proof(3)
    assert not verify_inclusion(b"different", proof, tree.root)


def test_odd_leaves_pad_correctly():
    leaves = [f"leaf-{i}".encode() for i in range(5)]
    tree = build_merkle_tree(leaves)
    for i, leaf in enumerate(leaves):
        proof = tree.proof(i)
        assert verify_inclusion(leaf, proof, tree.root)


def test_proof_index_out_of_range():
    tree = build_merkle_tree([b"a", b"b"])
    with pytest.raises(IndexError):
        tree.proof(5)
