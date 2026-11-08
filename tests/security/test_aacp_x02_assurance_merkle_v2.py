# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AACP-X-02: the assurance Merkle tree must be unambiguous.

The v1 construction (kept for historical traces) duplicates an odd node, so
``[a, b, c]`` and ``[a, b, c, c]`` share a root, and hashes leaves and nodes
in one domain, so an internal node's preimage verifies as a leaf. v2 hashes
a leaf as ``SHA-256(0x00 || leaf)``, a node as ``SHA-256(0x01 || L || R)`` over
raw digests, and promotes an odd node unchanged.

``assurance_merkle_v1_06c2f8f.json`` was produced by the code at 06c2f8f; it
must keep verifying under v1 and must never verify under v2.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from remora.assurance.merkle import (
    MERKLE_V1,
    MERKLE_V2,
    MerkleProof,
    UnsupportedMerkleVersion,
    build_merkle_tree,
    verify_inclusion,
)
from remora.assurance.trace import (
    TRACE_STANDARD_V1,
    TRACE_STANDARD_V2,
    AssuranceTrace,
    generate_assurance_trace,
    merkle_version_for,
    verify_assurance_trace,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "assurance_merkle_v1_06c2f8f.json").read_text())


def _leaves(n):
    return [f"leaf-{i}".encode() for i in range(n)]


def _proof(d, version):
    return MerkleProof(leaf_index=d["leaf_index"],
                       siblings=tuple((s, side) for s, side in d["siblings"]),
                       version=version)


# ---------------------------------------------------------------- v2 roots

def test_v2_is_the_default():
    t = build_merkle_tree([b"a", b"b"])
    assert t.version == MERKLE_V2
    assert t.proof(0).version == MERKLE_V2


def test_v2_leaf_and_node_hashes_are_domain_separated():
    t = build_merkle_tree([b"a", b"b"])
    la = hashlib.sha256(b"\x00a").digest()
    lb = hashlib.sha256(b"\x00b").digest()
    assert t.leaves == [la.hex(), lb.hex()]
    assert t.root == hashlib.sha256(b"\x01" + la + lb).hexdigest()


def test_v2_single_leaf_root_is_the_leaf_hash():
    t = build_merkle_tree([b"hello"])
    assert t.root == hashlib.sha256(b"\x00hello").hexdigest()
    assert verify_inclusion(b"hello", t.proof(0), t.root)


def test_odd_duplication_no_longer_collides():
    abc = build_merkle_tree([b"a", b"b", b"c"])
    abcc = build_merkle_tree([b"a", b"b", b"c", b"c"])
    assert abc.root != abcc.root


@pytest.mark.parametrize("n", range(1, 12))
def test_duplicating_the_last_leaf_always_changes_the_root(n):
    leaves = _leaves(n)
    assert build_merkle_tree(leaves).root != build_merkle_tree(leaves + leaves[-1:]).root


def test_odd_node_is_promoted_unchanged():
    t = build_merkle_tree([b"a", b"b", b"c"])
    assert t.levels[1][1] == t.levels[0][2]
    node_ab = hashlib.sha256(b"\x01" + bytes.fromhex(t.levels[0][0])
                             + bytes.fromhex(t.levels[0][1])).digest()
    assert t.root == hashlib.sha256(b"\x01" + node_ab + bytes.fromhex(t.levels[0][2])).hexdigest()


def test_v1_roots_are_reproduced_exactly():
    for tree in FIXTURE["trees"]:
        t = build_merkle_tree([x.encode() for x in tree["leaves"]], version=MERKLE_V1)
        assert t.root == tree["root"]


def test_v2_roots_differ_from_v1_roots():
    for tree in FIXTURE["trees"]:
        assert build_merkle_tree([x.encode() for x in tree["leaves"]]).root != tree["root"]


# ---------------------------------------------------------------- substitution

def test_internal_node_does_not_verify_as_a_leaf():
    t = build_merkle_tree([b"a", b"b", b"c", b"d"])
    # Every plausible encoding of the node's children, as the AACP probe tried.
    for fake in ((t.levels[0][0] + t.levels[0][1]).encode(),
                 bytes.fromhex(t.levels[0][0]) + bytes.fromhex(t.levels[0][1]),
                 b"\x01" + bytes.fromhex(t.levels[0][0]) + bytes.fromhex(t.levels[0][1])):
        proof = MerkleProof(leaf_index=0, siblings=((t.levels[1][1], "R"),))
        assert not verify_inclusion(fake, proof, t.root)


def test_leaf_hash_does_not_verify_as_a_node_one_level_up():
    t = build_merkle_tree([b"a", b"b", b"c", b"d"])
    # Present leaf a's digest as if it were a child-level node: still fails.
    proof = MerkleProof(leaf_index=0, siblings=((t.levels[0][1], "R"), (t.levels[1][1], "R")))
    assert not verify_inclusion(bytes.fromhex(t.levels[0][0]), proof, t.root)


def test_v1_remains_ambiguous_and_is_labelled_so():
    # The weakness is kept for v1 on purpose so historical roots still
    # verify; it is why v1 must be named explicitly to be used at all.
    t = build_merkle_tree([b"a", b"b", b"c", b"d"], version=MERKLE_V1)
    fake = (t.levels[0][0] + t.levels[0][1]).encode()
    proof = MerkleProof(leaf_index=0, siblings=((t.levels[1][1], "R"),), version=MERKLE_V1)
    assert verify_inclusion(fake, proof, t.root)
    assert build_merkle_tree([b"a", b"b", b"c"], version=MERKLE_V1).root == \
        build_merkle_tree([b"a", b"b", b"c", b"c"], version=MERKLE_V1).root


# ---------------------------------------------------------------- proofs

@pytest.mark.parametrize("n", range(1, 18))
def test_every_proof_verifies_for_odd_and_even_counts(n):
    leaves = _leaves(n)
    t = build_merkle_tree(leaves)
    for i, leaf in enumerate(leaves):
        p = t.proof(i)
        assert p.leaf_count == n
        assert verify_inclusion(leaf, p, t.root), (n, i)


@pytest.mark.parametrize("n", [3, 5, 7, 8])
def test_tampered_leaf_fails(n):
    leaves = _leaves(n)
    t = build_merkle_tree(leaves)
    for i in range(n):
        assert not verify_inclusion(leaves[i] + b"!", t.proof(i), t.root)


def test_proof_for_one_leaf_does_not_verify_another():
    leaves = _leaves(6)
    t = build_merkle_tree(leaves)
    assert not verify_inclusion(leaves[2], t.proof(3), t.root)


@pytest.mark.parametrize("bad_index", [-1, 7, 100])
def test_out_of_range_index_raises_at_proof(bad_index):
    with pytest.raises(IndexError):
        build_merkle_tree(_leaves(7)).proof(bad_index)


def test_proof_with_wrong_index_for_its_path_is_rejected():
    leaves = _leaves(7)
    t = build_merkle_tree(leaves)
    p = t.proof(2)
    for idx in (0, 3, 6, 7, -1):
        assert not verify_inclusion(leaves[2], replace(p, leaf_index=idx), t.root)


def test_proof_with_wrong_leaf_count_is_rejected():
    leaves = _leaves(7)
    t = build_merkle_tree(leaves)
    p = t.proof(6)  # the promoted leaf: its path depends on the count
    for count in (6, 8, 0, -3):
        assert not verify_inclusion(leaves[6], replace(p, leaf_count=count), t.root)


@pytest.mark.parametrize("siblings", [
    (("zz" * 32, "R"),),                       # not hex
    (("ab" * 31, "R"),),                       # too short
    (("AB" * 32, "R"),),                       # upper-case hex is not the canonical form
    (("ab" * 32, "X"),),                       # bad side
    (("ab" * 32,),),                           # missing side
    (("ab" * 32, "R", "extra"),),
    ((b"\xab" * 32, "R"),),                    # bytes, not hex string
    "not-a-tuple",
])
def test_malformed_siblings_are_rejected(siblings):
    t = build_merkle_tree([b"a", b"b"])
    p = MerkleProof(leaf_index=0, siblings=siblings)  # type: ignore[arg-type]
    assert not verify_inclusion(b"a", p, t.root)


@pytest.mark.parametrize("index", ["0", 0.0, True, None])
def test_non_integer_index_is_rejected(index):
    t = build_merkle_tree([b"a", b"b"])
    p = replace(t.proof(0), leaf_index=index)
    assert not verify_inclusion(b"a", p, t.root)


def test_malformed_root_is_rejected():
    t = build_merkle_tree([b"a", b"b"])
    assert not verify_inclusion(b"a", t.proof(0), t.root.upper())
    assert not verify_inclusion(b"a", t.proof(0), "")


def test_extra_or_missing_siblings_are_rejected():
    leaves = _leaves(8)
    t = build_merkle_tree(leaves)
    p = t.proof(5)
    assert not verify_inclusion(leaves[5], replace(p, siblings=p.siblings[:-1]), t.root)
    assert not verify_inclusion(leaves[5], replace(p, siblings=p.siblings + (p.siblings[0],)),
                                t.root)


# ---------------------------------------------------------------- versions

@pytest.mark.parametrize("version", ["v2", "remora-assurance-merkle-v3", "", None, 2])
def test_unsupported_version_is_rejected(version):
    with pytest.raises(UnsupportedMerkleVersion):
        build_merkle_tree([b"a"], version=version)  # type: ignore[arg-type]
    t = build_merkle_tree([b"a", b"b"])
    assert not verify_inclusion(b"a", replace(t.proof(0), version=version), t.root)


def test_expected_version_that_disagrees_with_the_proof_is_rejected():
    t = build_merkle_tree([b"a", b"b"])
    assert verify_inclusion(b"a", t.proof(0), t.root, version=MERKLE_V2)
    assert not verify_inclusion(b"a", t.proof(0), t.root, version=MERKLE_V1)


def test_historical_v1_proofs_verify_under_v1_only():
    for tree in FIXTURE["trees"]:
        for i, d in enumerate(tree["proofs"]):
            leaf = tree["leaves"][i].encode()
            assert verify_inclusion(leaf, _proof(d, MERKLE_V1), tree["root"])
            # The same proof read as v2 (the default) must not verify: an old
            # root is never silently reinterpreted.
            assert not verify_inclusion(leaf, _proof(d, MERKLE_V2), tree["root"])


def test_v2_proof_fails_against_v1_root_and_vice_versa():
    leaves = _leaves(5)
    v1 = build_merkle_tree(leaves, version=MERKLE_V1)
    v2 = build_merkle_tree(leaves)
    for i, leaf in enumerate(leaves):
        assert not verify_inclusion(leaf, v2.proof(i), v1.root)
        assert not verify_inclusion(leaf, v1.proof(i), v2.root)


# ---------------------------------------------------------------- traces

def _log(n=5):
    return [{"t": i, "winning_fp": f"fp{i}", "V": 0.0, "H": 0.0, "D": 0.0,
             "weighted_support": 0.5} for i in range(n)]


def test_new_traces_are_v2_and_verify():
    trace = generate_assurance_trace(_log(), final_V=0.0, betti_info={})
    assert trace.signature_standard == TRACE_STANDARD_V2
    assert merkle_version_for(trace.signature_standard) == MERKLE_V2
    assert all(p.version == MERKLE_V2 for p in trace.inclusion_proofs)
    assert verify_assurance_trace(trace)


def test_historical_v1_trace_verifies_under_v1():
    fx = FIXTURE["trace"]
    assert fx["signature_standard"] == TRACE_STANDARD_V1
    trace = AssuranceTrace(
        root_hash=fx["root_hash"], leaf_count=fx["leaf_count"], betti_0=1, betti_1=0,
        lyapunov_final_V=fx["final_V"],
        canonical_leaves=tuple(x.encode() for x in fx["canonical_leaves"]),
        inclusion_proofs=tuple(_proof(d, MERKLE_V1) for d in fx["inclusion_proofs"]),
        signature_standard=TRACE_STANDARD_V1,
    )
    assert verify_assurance_trace(trace)
    # Relabelled as v2 the same root is rejected, not reinterpreted.
    assert not verify_assurance_trace(replace(trace, signature_standard=TRACE_STANDARD_V2))


def test_trace_from_the_same_log_has_a_new_root_under_v2():
    fx = FIXTURE["trace"]
    trace = generate_assurance_trace(fx["consensus_log"], fx["final_V"], fx["betti_info"])
    assert trace.root_hash != fx["root_hash"]
    assert [b.decode() for b in trace.canonical_leaves] == fx["canonical_leaves"]


@pytest.mark.parametrize("standard", ["REMORA-Assurance-Trace-v3", "", "remora-assurance-trace-v2"])
def test_unknown_trace_standard_is_rejected(standard):
    trace = generate_assurance_trace(_log(), final_V=0.0, betti_info={})
    with pytest.raises(UnsupportedMerkleVersion):
        merkle_version_for(standard)
    assert not verify_assurance_trace(replace(trace, signature_standard=standard))


def test_trace_with_tampered_leaf_or_count_is_rejected():
    trace = generate_assurance_trace(_log(), final_V=0.0, betti_info={})
    leaves = list(trace.canonical_leaves)
    leaves[2] = leaves[2].replace(b"fp2", b"fpX")
    assert not verify_assurance_trace(replace(trace, canonical_leaves=tuple(leaves)))
    assert not verify_assurance_trace(replace(trace, leaf_count=trace.leaf_count + 1))
    assert not verify_assurance_trace(
        replace(trace, canonical_leaves=trace.canonical_leaves + trace.canonical_leaves[-1:]))


def test_trace_with_proof_of_another_version_is_rejected():
    trace = generate_assurance_trace(_log(), final_V=0.0, betti_info={})
    proofs = list(trace.inclusion_proofs)
    proofs[0] = replace(proofs[0], version=MERKLE_V1)
    assert not verify_assurance_trace(replace(trace, inclusion_proofs=tuple(proofs)))


def test_empty_trace_verifies_only_when_empty():
    trace = generate_assurance_trace([], final_V=0.0, betti_info={})
    assert trace.signature_standard == TRACE_STANDARD_V2
    assert verify_assurance_trace(trace)
    assert not verify_assurance_trace(replace(trace, root_hash="ab" * 32))
