# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Binary SHA-256 Merkle tree with inclusion proofs, versioned (AACP-X-02).

``MERKLE_V2`` (the default): a leaf hashes as ``SHA-256(0x00 || leaf_bytes)``
and an internal node as ``SHA-256(0x01 || left || right)`` over the children's
raw 32-byte digests; an odd node at the end of a level is promoted unchanged
(RFC 6962 style), never duplicated. Leaves and nodes cannot stand in for each
other, and ``[a, b, c]`` and ``[a, b, c, c]`` have different roots. A v2 proof
carries ``leaf_count``; the verifier checks the sibling sides against the
path ``(leaf_index, leaf_count)`` implies, so the index is bound.

``MERKLE_V1`` (legacy, for traces recorded before the fix): SHA-256 of the
leaf bytes; nodes hash the concatenated *hex* strings of their children; an
odd node is paired with a copy of itself. It is ambiguous on both counts and
is kept only so historical roots still verify. It is used only when named.

Hashes are lowercase hex strings throughout, so equality and JSON
serialisation stay trivial. Verification never falls back from one version
to another: an unknown version, or an expected version that differs from the
proof's, is rejected.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

MERKLE_V1 = "remora-assurance-merkle-v1"
MERKLE_V2 = "remora-assurance-merkle-v2"
SUPPORTED_MERKLE_VERSIONS = frozenset({MERKLE_V1, MERKLE_V2})
#: Construction used when none is named. Historical v1 data must name v1.
DEFAULT_MERKLE_VERSION = MERKLE_V2

_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"
_HEX = frozenset("0123456789abcdef")


class UnsupportedMerkleVersion(ValueError):
    """A Merkle version this module does not implement."""


def _require_version(version: object) -> str:
    if not isinstance(version, str) or version not in SUPPORTED_MERKLE_VERSIONS:
        raise UnsupportedMerkleVersion(f"unsupported merkle version {version!r}")
    return version


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


# --- v1 (legacy, ambiguous) --------------------------------------------------

def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pair(left: str, right: str) -> str:
    return _h((left + right).encode("utf-8"))


# --- v2 ---------------------------------------------------------------------

def _leaf_v2(data: bytes) -> bytes:
    return hashlib.sha256(_LEAF_PREFIX + data).digest()


def _node_v2(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(_NODE_PREFIX + left + right).digest()


def _path_sides(index: int, count: int, version: str) -> list[str]:
    """The sibling sides a proof for ``index`` in a tree of ``count`` leaves has."""
    sides: list[str] = []
    idx, n = index, count
    while n > 1:
        if idx % 2 == 1:
            sides.append("L")
        elif idx + 1 < n or version == MERKLE_V1:
            sides.append("R")  # v1 pairs a trailing odd node with itself
        # v2: a trailing odd node is promoted; that level has no sibling
        idx //= 2
        n = (n + 1) // 2
    return sides


@dataclass(frozen=True)
class MerkleProof:
    leaf_index: int
    siblings: tuple[tuple[str, str], ...]  # each: (sibling_hash, side) side in {"L","R"}
    version: str = DEFAULT_MERKLE_VERSION
    #: Number of leaves in the tree. Required for v2 (it fixes the path the
    #: siblings must follow); optional for v1, whose historical proofs lack it.
    leaf_count: int | None = None


@dataclass
class MerkleTree:
    leaves: list[str] = field(default_factory=list)
    levels: list[list[str]] = field(default_factory=list)
    root: str = ""
    version: str = DEFAULT_MERKLE_VERSION

    def proof(self, index: int) -> MerkleProof:
        if index < 0 or index >= len(self.leaves):
            raise IndexError(f"leaf index {index} out of range")
        siblings: list[tuple[str, str]] = []
        idx = index
        for level in self.levels[:-1]:
            if idx % 2 == 1:
                siblings.append((level[idx - 1], "L"))
            elif idx + 1 < len(level):
                siblings.append((level[idx + 1], "R"))
            elif self.version == MERKLE_V1:
                siblings.append((level[idx], "R"))  # v1: paired with itself
            idx //= 2
        return MerkleProof(leaf_index=index, siblings=tuple(siblings),
                           version=self.version, leaf_count=len(self.leaves))


def _build_v1(items: list[bytes]) -> MerkleTree:
    leaves = [_h(it) for it in items]
    levels: list[list[str]] = [list(leaves)]
    current = list(leaves)
    while len(current) > 1:
        if len(current) % 2 == 1:
            current.append(current[-1])  # duplicate last (v1, ambiguous)
        nxt = [_pair(current[i], current[i + 1]) for i in range(0, len(current), 2)]
        levels.append(nxt)
        current = nxt
    return MerkleTree(leaves=leaves, levels=levels, root=current[0], version=MERKLE_V1)


def _build_v2(items: list[bytes]) -> MerkleTree:
    level = [_leaf_v2(it) for it in items]
    levels: list[list[str]] = [[d.hex() for d in level]]
    while len(level) > 1:
        nxt = [_node_v2(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])  # promote the odd node unchanged
        levels.append([d.hex() for d in nxt])
        level = nxt
    return MerkleTree(leaves=levels[0], levels=levels, root=level[0].hex(), version=MERKLE_V2)


def build_merkle_tree(items: list[bytes], *, version: str = DEFAULT_MERKLE_VERSION) -> MerkleTree:
    """Build a tree over ``items``; v2 unless ``version`` names v1."""
    version = _require_version(version)
    if not items:
        raise ValueError("build_merkle_tree requires at least one leaf")
    return _build_v1(list(items)) if version == MERKLE_V1 else _build_v2(list(items))


def _well_formed_siblings(siblings: object) -> list[tuple[str, str]] | None:
    if not isinstance(siblings, tuple | list):
        return None
    out: list[tuple[str, str]] = []
    for item in siblings:
        if not isinstance(item, tuple | list) or len(item) != 2:
            return None
        digest, side = item
        if not _is_hex64(digest) or side not in ("L", "R"):
            return None
        out.append((digest, side))
    return out


def verify_inclusion(leaf_bytes: bytes, proof: MerkleProof, root: str, *,
                     version: str | None = None) -> bool:
    """True when ``leaf_bytes`` is in the tree with ``root`` under ``proof``.

    The construction is the proof's ``version``. ``version``, when given, is
    the one the caller expects; a proof of another version is rejected rather
    than checked under the version it names. Rejected outright: an unknown
    version, a malformed root, index or sibling, a v2 proof without a valid
    ``leaf_count``, and siblings whose sides do not follow the path
    ``(leaf_index, leaf_count)`` implies.
    """
    if not isinstance(proof, MerkleProof) or not isinstance(leaf_bytes, bytes | bytearray):
        return False
    v = proof.version
    if not isinstance(v, str) or v not in SUPPORTED_MERKLE_VERSIONS:
        return False
    if version is not None and version != v:
        return False
    if not _is_hex64(root):
        return False
    index = proof.leaf_index
    if type(index) is not int or index < 0:
        return False
    siblings = _well_formed_siblings(proof.siblings)
    if siblings is None:
        return False
    count = proof.leaf_count
    if count is None:
        if v == MERKLE_V2:
            return False  # a v2 path is only defined with the leaf count
    elif type(count) is not int or count < 1 or index >= count:
        return False
    elif [side for _, side in siblings] != _path_sides(index, count, v):
        return False

    if v == MERKLE_V1:
        h = _h(bytes(leaf_bytes))
        for sib, side in siblings:
            h = _pair(sib, h) if side == "L" else _pair(h, sib)
        return h == root
    d = _leaf_v2(bytes(leaf_bytes))
    for sib, side in siblings:
        s = bytes.fromhex(sib)
        d = _node_v2(s, d) if side == "L" else _node_v2(d, s)
    return d.hex() == root


def merkle_root(items: Sequence[bytes], *, version: str = DEFAULT_MERKLE_VERSION) -> str:
    """The root of ``items`` under ``version`` (``""`` for no items)."""
    _require_version(version)
    return build_merkle_tree(list(items), version=version).root if items else ""
