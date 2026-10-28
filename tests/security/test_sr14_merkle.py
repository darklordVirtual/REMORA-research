"""SR-14 / SEC-03: Merkle construction needs RFC 6962 domain separation, and a
root must commit to its leaf count.

On HEAD both merkle builders hash hex-string pairs with no leaf/node domain
separation and duplicate the last node on odd levels (the CVE-2012-2459
pattern): [a,b,c] and [a,b,c,c] share a root, and an interior node is
indistinguishable from a leaf. The exported root did not have to name its
entry count, and the HMAC input excluded it.

v2 keeps v1 available for anchors recorded before 2026-10-28.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from remora.audit.checkpoint import (
    make_checkpoint,
    merkle_root_from_hex_leaves,
    verify_span,
)
from remora.audit.hash_chain import AuditHashChain
from remora.audit.merkle import (
    compute_merkle_root,
    export_daily_root,
    sign_root,
    verify_signed_root,
)


def _entries(n: int):
    chain = AuditHashChain()
    for i in range(n):
        chain.append(timestamp="t", question_hash=f"q{i}", action="accept",
                     trust_score=0.5, phase="p", metadata={})
    return chain.entries()


_LEAVES = [hashlib.sha256(f"leaf-{i}".encode()).hexdigest() for i in range(4)]


def test_v2_odd_leaf_duplication_changes_the_root() -> None:
    """The CVE-2012-2459 pattern: [a,b,c] and [a,b,c,c] must NOT share a root."""
    a, b, c = _entries(3)
    assert compute_merkle_root([a, b, c]) != compute_merkle_root([a, b, c, c])
    assert merkle_root_from_hex_leaves(_LEAVES[:3]) != (
        merkle_root_from_hex_leaves([_LEAVES[0], _LEAVES[1], _LEAVES[2], _LEAVES[2]])
    )


def test_v2_matches_rfc6962_reference_computation() -> None:
    """Pin the exact v2 construction: 0x00 leaf prefix, 0x01 node prefix over
    raw digest bytes, odd node promoted unchanged."""
    l0, l1, l2 = _LEAVES[:3]
    h0 = hashlib.sha256(b"\x00" + bytes.fromhex(l0)).digest()
    h1 = hashlib.sha256(b"\x00" + bytes.fromhex(l1)).digest()
    h2 = hashlib.sha256(b"\x00" + bytes.fromhex(l2)).digest()
    n01 = hashlib.sha256(b"\x01" + h0 + h1).digest()
    root = hashlib.sha256(b"\x01" + n01 + h2).hexdigest()  # odd node promoted
    assert merkle_root_from_hex_leaves([l0, l1, l2]) == root


def test_v2_differs_from_v1() -> None:
    """Domain separation must move every root; v1 stays for old anchors."""
    a, b, c = _entries(3)
    assert compute_merkle_root([a, b, c], version=1) != compute_merkle_root([a, b, c])
    assert merkle_root_from_hex_leaves(_LEAVES[:3], version=1) != (
        merkle_root_from_hex_leaves(_LEAVES[:3])
    )
    # The documented v1 ambiguity is unchanged under version=1.
    assert compute_merkle_root([a, b, c], version=1) == (
        compute_merkle_root([a, b, c, c], version=1)
    )


def test_v1_checkpoint_still_verifies() -> None:
    """Anchors recorded under v1 remain verifiable under v1."""
    root_v1 = merkle_root_from_hex_leaves(_LEAVES[:3], version=1)
    ckpt = make_checkpoint(_LEAVES[:3], 0, version=1)
    assert ckpt.root == root_v1
    assert ckpt.signing_payload().startswith(b"remora-ckpt-v1|")
    assert verify_span(_LEAVES[:3], ckpt) is True


def test_v2_checkpoint_carries_v2_payload_prefix() -> None:
    ckpt = make_checkpoint(_LEAVES[:3], 0)
    assert ckpt.v == 2
    assert ckpt.signing_payload().startswith(b"remora-ckpt-v2|")
    assert verify_span(_LEAVES[:3], ckpt) is True
    # A v2 root must not verify against v1 recomputation.
    assert merkle_root_from_hex_leaves(_LEAVES[:3], version=1) != ckpt.root


def test_export_requires_n_entries(tmp_path) -> None:
    root = compute_merkle_root(_entries(2))
    with pytest.raises((TypeError, ValueError)):
        export_daily_root(root, directory=tmp_path)


def test_export_signature_binds_n_entries(tmp_path) -> None:
    root = compute_merkle_root(_entries(2))
    path = export_daily_root(root, directory=tmp_path, signing_key="k", n_entries=2)
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    assert record["v"] == 2
    assert record["n_entries"] == 2
    assert verify_signed_root(root, record["signature"], key="k", n_entries=2) is True
    # Tampering with the count must invalidate the signature.
    assert verify_signed_root(root, record["signature"], key="k", n_entries=3) is False


def test_v1_export_still_possible_for_legacy_anchors(tmp_path) -> None:
    root = compute_merkle_root(_entries(2), version=1)
    path = export_daily_root(root, directory=tmp_path, version=1)
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert "v" not in record  # legacy record shape
