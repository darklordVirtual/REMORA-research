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
    assert verify_signed_root(
        root, record["signature"], key="k", n_entries=2, version=2,
    ) is True
    # Tampering with the count must invalidate the signature.
    assert verify_signed_root(
        root, record["signature"], key="k", n_entries=3, version=2,
    ) is False
    # And a v2 signature must never verify under the legacy rule.
    assert verify_signed_root(root, record["signature"], key="k") is False


def test_v1_export_still_possible_for_legacy_anchors(tmp_path) -> None:
    root = compute_merkle_root(_entries(2), version=1)
    path = export_daily_root(root, directory=tmp_path, version=1)
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert "v" not in record  # legacy record shape


# ── Review follow-up: unknown versions and non-canonical v2 leaves ──────────

from remora.audit.checkpoint import (  # noqa: E402
    Checkpoint,
    sign_checkpoint,
    verify_checkpoint_chain,
    verify_checkpoint_signature,
)
from remora.audit.merkle import sign_root, verify_root_record  # noqa: E402


@pytest.mark.parametrize("bad", [0, 3, -1, "2", 2.0, True, None])
def test_from_dict_rejects_unsupported_version(bad) -> None:
    """A record claiming v=3 must not parse and then sign under the v1 prefix."""
    record = make_checkpoint(_LEAVES[:3], 0).to_dict()
    record["v"] = bad
    with pytest.raises(ValueError):
        Checkpoint.from_dict(record)


def test_from_dict_without_version_is_v1() -> None:
    record = make_checkpoint(_LEAVES[:3], 0, version=1).to_dict()
    del record["v"]
    assert Checkpoint.from_dict(record).v == 1


def test_unknown_version_checkpoint_never_verifies() -> None:
    """Constructed directly (bypassing from_dict), an unknown version must fail
    every verifier with False, never fall back to the v1 construction."""
    good_v1 = make_checkpoint(_LEAVES[:3], 0, version=1)
    sig_v1 = sign_checkpoint(good_v1, key="k")
    forged = Checkpoint(good_v1.seq_start, good_v1.seq_end, good_v1.root,
                        good_v1.prev_checkpoint_root, v=3)
    assert verify_span(_LEAVES[:3], forged) is False
    assert verify_checkpoint_signature(forged, sig_v1, key="k") is False
    with pytest.raises(ValueError):
        forged.signing_payload()
    ok, problems = verify_checkpoint_chain([forged])
    assert ok is False and problems == ["unsupported_version_at:0"]


@pytest.mark.parametrize("mangle", [
    str.upper,
    lambda h: " " + h,
    lambda h: h[:32] + " " + h[32:],
    lambda h: h + "\n",
])
def test_v2_rejects_non_canonical_leaves(mangle) -> None:
    """bytes.fromhex ignores case and whitespace, so without a check two
    distinct leaf strings would share one v2 root."""
    leaves = list(_LEAVES[:3])
    ckpt = make_checkpoint(leaves, 0)
    leaves[1] = mangle(leaves[1])
    with pytest.raises(ValueError):
        merkle_root_from_hex_leaves(leaves)
    assert verify_span(leaves, ckpt) is False


def test_v2_rejects_non_string_leaf_with_value_error() -> None:
    with pytest.raises(ValueError):
        merkle_root_from_hex_leaves([_LEAVES[0], 123])  # type: ignore[list-item]


def test_root_signature_rejects_unsupported_version() -> None:
    root = _LEAVES[0]
    with pytest.raises(ValueError):
        sign_root(root, key="k", n_entries=3, version=3)
    legacy = sign_root(root, key="k")
    assert verify_signed_root(root, legacy, key="k", version=3) is False


def test_verify_root_record_dispatches_on_version(tmp_path) -> None:
    root = compute_merkle_root(_entries(3))
    path = export_daily_root(root, directory=tmp_path, signing_key="k", n_entries=3)
    record = json.loads(path.read_text().splitlines()[-1])
    assert verify_root_record(record, key="k") is True
    assert verify_root_record(dict(record, n_entries=4), key="k") is False
    assert verify_root_record({k: v for k, v in record.items() if k != "n_entries"},
                              key="k") is False
    assert verify_root_record(dict(record, n_entries=True), key="k") is False
    assert verify_root_record(dict(record, v=3), key="k") is False
    assert verify_root_record({k: v for k, v in record.items() if k != "signature"},
                              key="k") is False
    assert verify_root_record(record, key="other") is False
    # A v2 record stripped of its version must not verify as a v1 record.
    assert verify_root_record({k: v for k, v in record.items() if k != "v"},
                              key="k") is False

    legacy_root = compute_merkle_root(_entries(3), version=1)
    path = export_daily_root(legacy_root, directory=tmp_path / "v1", signing_key="k",
                             version=1)
    legacy = json.loads(path.read_text().splitlines()[-1])
    assert "v" not in legacy
    assert verify_root_record(legacy, key="k") is True


def test_make_checkpoint_rejects_trailing_newline_leaf() -> None:
    """``^...$`` matches before a final newline; leaf validation must not."""
    with pytest.raises(ValueError):
        make_checkpoint([_LEAVES[0] + "\n"], 0)
