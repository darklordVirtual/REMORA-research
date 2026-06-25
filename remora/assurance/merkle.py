# Author: Stian Skogbrott
# License: Apache-2.0
"""Binary SHA-256 Merkle tree with inclusion proofs.

Padding rule: odd levels duplicate the last node (Bitcoin-style). Hashes are
hex strings throughout to keep equality / JSON serialisation trivial.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pair(left: str, right: str) -> str:
    return _h((left + right).encode("utf-8"))


@dataclass(frozen=True)
class MerkleProof:
    leaf_index: int
    siblings: tuple[tuple[str, str], ...]  # each: (sibling_hash, side) side in {"L","R"}


@dataclass
class MerkleTree:
    leaves: list[str] = field(default_factory=list)
    levels: list[list[str]] = field(default_factory=list)
    root: str = ""

    def proof(self, index: int) -> MerkleProof:
        if index < 0 or index >= len(self.leaves):
            raise IndexError(f"leaf index {index} out of range")
        siblings: list[tuple[str, str]] = []
        idx = index
        for level in self.levels[:-1]:
            if idx % 2 == 0:
                sib_idx = idx + 1 if idx + 1 < len(level) else idx
                siblings.append((level[sib_idx], "R"))
            else:
                siblings.append((level[idx - 1], "L"))
            idx //= 2
        return MerkleProof(leaf_index=index, siblings=tuple(siblings))


def build_merkle_tree(items: list[bytes]) -> MerkleTree:
    if not items:
        raise ValueError("build_merkle_tree requires at least one leaf")
    leaves = [_h(it) for it in items]
    levels: list[list[str]] = [list(leaves)]
    current = list(leaves)
    while len(current) > 1:
        if len(current) % 2 == 1:
            current.append(current[-1])  # duplicate last
        nxt = [_pair(current[i], current[i + 1]) for i in range(0, len(current), 2)]
        levels.append(nxt)
        current = nxt
    return MerkleTree(leaves=leaves, levels=levels, root=current[0])


def verify_inclusion(leaf_bytes: bytes, proof: MerkleProof, root: str) -> bool:
    h = _h(leaf_bytes)
    for sib, side in proof.siblings:
        h = _pair(sib, h) if side == "L" else _pair(h, sib)
    return h == root
