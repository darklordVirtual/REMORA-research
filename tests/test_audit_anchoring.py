# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for PR 5: Audit anchoring — Merkle root prototype + language fixes.

The audit found:
- The audit chain is tamper-DETECTABLE only (correct) but language in docs
  used "tamper-proof" incorrectly in places.
- No optional Merkle root export existed.
- No daily root hash file capability existed.
- No signed root capability existed.

This PR adds:
1. compute_merkle_root(entries) → deterministic Merkle root of a chain
2. export_daily_root(entries, directory) → appends root hash to a dated file
3. sign_root(root_hash, key) → HMAC-SHA256 signed root
4. Documentation strings corrected to say tamper-DETECTABLE

All tests RED initially.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date

from remora.audit.hash_chain import AuditHashChain, HashChainEntry
from remora.audit.merkle import (
    compute_merkle_root,
    export_daily_root,
    sign_root,
    verify_signed_root,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chain(n: int = 4) -> AuditHashChain:
    chain = AuditHashChain()
    for i in range(n):
        chain.append(
            timestamp=f"2026-06-09T10:00:0{i}+00:00",
            question_hash=hashlib.sha256(f"question {i}".encode()).hexdigest(),
            action="accept" if i % 2 == 0 else "verify",
            trust_score=0.8 + i * 0.01,
            phase="ordered",
            metadata={"index": i},
        )
    return chain


# ---------------------------------------------------------------------------
# compute_merkle_root
# ---------------------------------------------------------------------------

class TestComputeMerkleRoot:

    def test_single_entry_merkle_root_uses_canonical_json_leaf(self):
        """Single-entry root = SHA-256 of canonical JSON of that entry."""
        import dataclasses
        chain = _make_chain(1)
        entry = chain.entries()[0]
        canonical = json.dumps(dataclasses.asdict(entry), sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert compute_merkle_root(chain.entries()) == expected

    def test_two_entry_merkle_root_is_sha256_of_leaf_pair(self):
        """Two-entry root = SHA-256(leaf0 + leaf1) where leaf = SHA-256(canonical_json)."""
        import dataclasses
        chain = _make_chain(2)
        entries = chain.entries()

        def _leaf(e):
            c = json.dumps(dataclasses.asdict(e), sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(c.encode("utf-8")).hexdigest()

        l0, l1 = _leaf(entries[0]), _leaf(entries[1])
        expected = hashlib.sha256((l0 + l1).encode("utf-8")).hexdigest()
        assert compute_merkle_root(entries) == expected

    def test_merkle_root_is_deterministic(self):
        chain = _make_chain(4)
        root1 = compute_merkle_root(chain.entries())
        root2 = compute_merkle_root(chain.entries())
        assert root1 == root2

    def test_merkle_root_changes_when_entry_tampered(self):
        chain = _make_chain(4)
        original_root = compute_merkle_root(chain.entries())

        # Build tampered copy of entries
        entries = list(chain.entries())
        tampered = HashChainEntry(
            timestamp=entries[1].timestamp,
            question_hash=entries[1].question_hash,
            action="accept",  # changed from "verify"
            trust_score=entries[1].trust_score,
            phase=entries[1].phase,
            previous_hash=entries[1].previous_hash,
            entry_hash=entries[1].entry_hash,  # entry_hash unchanged — tampered data
            metadata=entries[1].metadata,
        )
        tampered_entries = [entries[0], tampered, entries[2], entries[3]]
        tampered_root = compute_merkle_root(tampered_entries)

        # Root should differ from original since entry data differs
        # (our Merkle implementation hashes entry fields, not just entry_hash)
        assert tampered_root != original_root

    def test_empty_chain_returns_empty_string_or_raises(self):
        """Empty chain: either return empty string or raise ValueError."""
        try:
            result = compute_merkle_root([])
            assert result == "" or result is None
        except ValueError:
            pass  # Also acceptable

    def test_merkle_root_is_64_char_hex(self):
        chain = _make_chain(4)
        root = compute_merkle_root(chain.entries())
        assert len(root) == 64
        assert all(c in "0123456789abcdef" for c in root)


# ---------------------------------------------------------------------------
# sign_root and verify_signed_root
# ---------------------------------------------------------------------------

class TestSignedRoot:

    def test_sign_root_returns_hex_string(self):
        chain = _make_chain(2)
        root = compute_merkle_root(chain.entries())
        signed = sign_root(root, key="test-key-abc")
        assert isinstance(signed, str)
        assert len(signed) == 64

    def test_sign_root_is_hmac_sha256(self):
        root_hash = "a" * 64
        key = "my-signing-key"
        expected = hmac.new(
            key.encode("utf-8"), root_hash.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        assert sign_root(root_hash, key=key) == expected

    def test_verify_signed_root_accepts_valid(self):
        chain = _make_chain(3)
        root = compute_merkle_root(chain.entries())
        key = "enterprise-key"
        sig = sign_root(root, key=key)
        assert verify_signed_root(root, sig, key=key) is True

    def test_verify_signed_root_rejects_wrong_key(self):
        chain = _make_chain(3)
        root = compute_merkle_root(chain.entries())
        sig = sign_root(root, key="key-a")
        assert verify_signed_root(root, sig, key="key-b") is False

    def test_verify_signed_root_rejects_tampered_root(self):
        chain = _make_chain(3)
        root = compute_merkle_root(chain.entries())
        key = "key"
        sig = sign_root(root, key=key)
        tampered_root = "0" * 64
        assert verify_signed_root(tampered_root, sig, key=key) is False


# ---------------------------------------------------------------------------
# export_daily_root
# ---------------------------------------------------------------------------

class TestExportDailyRoot:

    def test_creates_dated_file_in_directory(self, tmp_path):
        chain = _make_chain(3)
        root = compute_merkle_root(chain.entries())
        export_daily_root(root, directory=tmp_path)
        dated_file = tmp_path / f"audit-root-{date.today().isoformat()}.jsonl"
        assert dated_file.exists()

    def test_file_contains_json_with_root_hash(self, tmp_path):
        chain = _make_chain(3)
        root = compute_merkle_root(chain.entries())
        export_daily_root(root, directory=tmp_path)
        dated_file = tmp_path / f"audit-root-{date.today().isoformat()}.jsonl"
        lines = dated_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["merkle_root"] == root

    def test_appends_when_file_exists(self, tmp_path):
        chain1 = _make_chain(2)
        chain2 = _make_chain(3)
        root1 = compute_merkle_root(chain1.entries())
        root2 = compute_merkle_root(chain2.entries())
        export_daily_root(root1, directory=tmp_path)
        export_daily_root(root2, directory=tmp_path)
        dated_file = tmp_path / f"audit-root-{date.today().isoformat()}.jsonl"
        lines = dated_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_signed_root_exported_when_key_provided(self, tmp_path):
        chain = _make_chain(2)
        root = compute_merkle_root(chain.entries())
        export_daily_root(root, directory=tmp_path, signing_key="test-key")
        dated_file = tmp_path / f"audit-root-{date.today().isoformat()}.jsonl"
        record = json.loads(dated_file.read_text(encoding="utf-8").strip())
        assert "signature" in record
        assert verify_signed_root(root, record["signature"], key="test-key")

    def test_record_contains_n_entries(self, tmp_path):
        chain = _make_chain(5)
        root = compute_merkle_root(chain.entries())
        export_daily_root(root, directory=tmp_path, n_entries=len(chain.entries()))
        dated_file = tmp_path / f"audit-root-{date.today().isoformat()}.jsonl"
        record = json.loads(dated_file.read_text(encoding="utf-8").strip())
        assert record["n_entries"] == 5


# ---------------------------------------------------------------------------
# Language: tamper-evident not tamper-proof
# ---------------------------------------------------------------------------

class TestAuditLanguage:

    def test_hash_chain_module_says_tamper_detectable_not_proof(self):
        """The hash_chain module docstring must say detectable, not proof."""
        import remora.audit.hash_chain as hc
        docstring = hc.__doc__ or ""
        assert "tamper-evident" in docstring.lower() or "detects tampering" in docstring.lower(), (
            "Module docstring should mention tamper-evident or detecting tampering"
        )
        # Must NOT claim to prevent tampering
        assert "tamper-proof" not in docstring, (
            "Module docstring must not claim tamper-proof (use tamper-evident)"
        )

    def test_hash_chain_module_does_not_claim_prevent_tampering(self):
        import remora.audit.hash_chain as hc
        src = open(hc.__file__, encoding="utf-8").read()
        # Should not have uncaveated tamper-proof claims
        assert "tamper-proof" not in src, (
            "hash_chain.py must not use the term 'tamper-proof' without qualification"
        )

    def test_merkle_module_docstring_is_accurate(self):
        import remora.audit.merkle as m
        docstring = m.__doc__ or ""
        assert "tamper-proof" not in docstring, (
            "merkle.py must not claim tamper-proof"
        )
