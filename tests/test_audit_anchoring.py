# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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

import dataclasses
import hashlib
import hmac
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from remora.audit.checkpoint import (
    Checkpoint,
    envelope_chain_leaves,
    make_checkpoint,
    merkle_root_from_hex_leaves,
    sign_checkpoint,
    tenant_chain_leaves,
    verify_checkpoint_chain,
    verify_checkpoint_signature,
    verify_span,
)
from remora.audit.hash_chain import AuditHashChain, HashChainEntry
from remora.audit.merkle import (
    compute_merkle_root,
    export_daily_root,
    sign_root,
    verify_signed_root,
)
from remora.governance.tenant_chain import TenantAuditChain
from remora.shadow.replay import replay_action_log, verify_envelope_hash_chain

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_LOG = _REPO_ROOT / "artifacts" / "demo" / "shadow_mode_sample_agent_action_log.jsonl"
_SAMPLE_CHECKPOINTS = _REPO_ROOT / "artifacts" / "audit_anchoring" / "sample_checkpoints.jsonl"


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
        with open(hc.__file__, encoding="utf-8") as fh:
            src = fh.read()
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

    def test_merkle_doc_reference_exists(self):
        """merkle.py points at the anchoring guide — the file must exist (RF-08)."""
        assert (_REPO_ROOT / "docs" / "enterprise" / "audit-anchoring-guide.md").exists()

    def test_checkpoint_module_does_not_claim_tamper_proof(self):
        import remora.audit.checkpoint as cp
        with open(cp.__file__, encoding="utf-8") as fh:
            src = fh.read()
        assert "tamper-proof" not in src, (
            "checkpoint.py must not use the term 'tamper-proof'"
        )


# ---------------------------------------------------------------------------
# RF-08 checkpoint layer: leaf adapters
# ---------------------------------------------------------------------------

def _fake_leaves(n: int) -> list[str]:
    return [hashlib.sha256(f"leaf {i}".encode()).hexdigest() for i in range(n)]


class TestCheckpointLeafAdapters:

    def test_tenant_chain_adapter_roundtrip(self):
        """Tenant-chain entries -> leaves -> checkpoint -> verify_span True."""
        chain = TenantAuditChain()
        for i in range(5):
            chain.append("tenant-a", {"action": "accept", "index": i})
        entries = chain.entries("tenant-a")
        assert chain.verify("tenant-a")[0] is True

        leaves = tenant_chain_leaves(entries)
        assert leaves == [e.entry_hash for e in entries]
        checkpoint = make_checkpoint(leaves, 0)
        assert checkpoint.seq_start == 0
        assert checkpoint.seq_end == 4
        assert verify_span(leaves, checkpoint) is True

    def test_tenant_chain_adapter_rejects_malformed_entry_hash(self):
        chain = TenantAuditChain()
        chain.append("tenant-a", {"action": "accept"})
        bad = dataclasses.replace(chain.entries("tenant-a")[0], entry_hash="not-hex")
        with pytest.raises(ValueError):
            tenant_chain_leaves([bad])

    def test_envelope_chain_adapter_over_demo_log(self):
        """Demo shadow log replays into a verified chain the adapter can checkpoint."""
        result = replay_action_log(str(_DEMO_LOG))
        assert verify_envelope_hash_chain(result.envelopes) is True

        leaves = envelope_chain_leaves(result.envelopes)
        assert leaves == [env.audit.hash for env in result.envelopes]
        checkpoint = make_checkpoint(leaves, 0)
        assert checkpoint.seq_end == len(leaves) - 1
        assert verify_span(leaves, checkpoint) is True

    def test_envelope_chain_adapter_rejects_missing_audit_hash(self):
        result = replay_action_log(str(_DEMO_LOG))
        env = result.envelopes[0]
        stripped = dataclasses.replace(
            env, audit=dataclasses.replace(env.audit, hash=None)
        )
        with pytest.raises(ValueError):
            envelope_chain_leaves([stripped])

    def test_plain_hex_list_needs_no_adapter(self):
        leaves = _fake_leaves(3)
        checkpoint = make_checkpoint(leaves, 0)
        assert verify_span(leaves, checkpoint) is True


# ---------------------------------------------------------------------------
# RF-08 checkpoint layer: make_checkpoint / verify_span
# ---------------------------------------------------------------------------

class TestCheckpointSpans:

    def test_single_bit_tamper_anywhere_in_span_fails_verify(self):
        """Flipping one bit of any nibble of any leaf must break verify_span."""
        leaves = _fake_leaves(6)
        checkpoint = make_checkpoint(leaves, 0)
        for leaf_idx in range(len(leaves)):
            for char_idx in range(64):
                tampered = list(leaves)
                original = tampered[leaf_idx]
                flipped = format(int(original[char_idx], 16) ^ 1, "x")
                tampered[leaf_idx] = (
                    original[:char_idx] + flipped + original[char_idx + 1:]
                )
                assert verify_span(tampered, checkpoint) is False, (
                    f"tamper at leaf {leaf_idx} nibble {char_idx} went undetected"
                )

    def test_length_mismatch_fails_verify(self):
        leaves = _fake_leaves(4)
        checkpoint = make_checkpoint(leaves, 0)
        assert verify_span(leaves[:-1], checkpoint) is False
        assert verify_span(leaves + [leaves[-1]], checkpoint) is False
        assert verify_span([], checkpoint) is False

    def test_make_checkpoint_rejects_empty_span(self):
        with pytest.raises(ValueError):
            make_checkpoint([], 0)

    def test_make_checkpoint_rejects_non_contiguous_prev(self):
        first = make_checkpoint(_fake_leaves(4), 0)
        with pytest.raises(ValueError):
            make_checkpoint(_fake_leaves(4), 5, first)  # gap: expected seq_start=4

    def test_root_matches_hex_leaf_merkle_overload(self):
        """Checkpoint root is the hex-leaf Merkle root (same pairing rule as merkle.py)."""
        leaves = _fake_leaves(3)
        checkpoint = make_checkpoint(leaves, 0)
        assert checkpoint.root == merkle_root_from_hex_leaves(leaves)
        # Odd tree duplicates the last node, exactly like compute_merkle_root.
        l0, l1, l2 = leaves
        p01 = hashlib.sha256((l0 + l1).encode("utf-8")).hexdigest()
        p22 = hashlib.sha256((l2 + l2).encode("utf-8")).hexdigest()
        expected = hashlib.sha256((p01 + p22).encode("utf-8")).hexdigest()
        assert checkpoint.root == expected

    def test_signing_payload_format(self):
        leaves = _fake_leaves(2)
        first = make_checkpoint(leaves, 0)
        assert first.signing_payload() == (
            f"remora-ckpt-v1|0|1|{first.root}|".encode()
        )
        second = make_checkpoint(_fake_leaves(2), 2, first)
        assert second.signing_payload() == (
            f"remora-ckpt-v1|2|3|{second.root}|{first.root}".encode()
        )

    def test_sign_and_verify_checkpoint_signature(self):
        checkpoint = make_checkpoint(_fake_leaves(2), 0)
        sig = sign_checkpoint(checkpoint, key="ckpt-key")
        assert verify_checkpoint_signature(checkpoint, sig, key="ckpt-key") is True
        assert verify_checkpoint_signature(checkpoint, sig, key="other-key") is False


# ---------------------------------------------------------------------------
# RF-08 checkpoint layer: checkpoint-chain consistency
# ---------------------------------------------------------------------------

def _checkpoint_chain(n_leaves: int, interval: int) -> tuple[list[str], list[Checkpoint]]:
    leaves = _fake_leaves(n_leaves)
    checkpoints: list[Checkpoint] = []
    prev: Checkpoint | None = None
    for start in range(0, n_leaves, interval):
        prev = make_checkpoint(leaves[start:start + interval], start, prev)
        checkpoints.append(prev)
    return leaves, checkpoints


class TestCheckpointChainConsistency:

    def test_consecutive_checkpoints_verify(self):
        _, checkpoints = _checkpoint_chain(20, 8)
        assert len(checkpoints) == 3  # spans of 8, 8, 4
        ok, problems = verify_checkpoint_chain(checkpoints)
        assert ok is True
        assert problems == []

    def test_broken_linkage_is_reported(self):
        _, checkpoints = _checkpoint_chain(20, 8)
        forged = dataclasses.replace(checkpoints[1], prev_checkpoint_root="f" * 64)
        ok, problems = verify_checkpoint_chain([checkpoints[0], forged, checkpoints[2]])
        assert ok is False
        assert "linkage_break_at:1" in problems

    def test_span_gap_is_reported(self):
        _, checkpoints = _checkpoint_chain(20, 8)
        shifted = dataclasses.replace(checkpoints[1], seq_start=9)
        ok, problems = verify_checkpoint_chain([checkpoints[0], shifted, checkpoints[2]])
        assert ok is False
        assert "span_gap_at:1" in problems

    def test_roundtrip_through_dict(self):
        _, checkpoints = _checkpoint_chain(20, 8)
        reloaded = [Checkpoint.from_dict(c.to_dict()) for c in checkpoints]
        assert reloaded == checkpoints
        ok, problems = verify_checkpoint_chain(reloaded)
        assert ok is True


# ---------------------------------------------------------------------------
# RF-08 generator: scripts/generate_audit_checkpoints.py
# ---------------------------------------------------------------------------

def _run_generator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/generate_audit_checkpoints.py", *args],
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
    )


class TestCheckpointGenerator:

    def test_generator_is_deterministic(self, tmp_path):
        """Two runs over the demo log produce byte-identical output."""
        out1 = tmp_path / "run1.jsonl"
        out2 = tmp_path / "run2.jsonl"
        for out in (out1, out2):
            completed = _run_generator("--output", str(out))
            assert completed.returncode == 0, completed.stderr
        data1 = out1.read_bytes()
        assert data1 == out2.read_bytes()
        assert data1.endswith(b"\n")
        assert b"\r" not in data1  # LF endings on every platform

    def test_generator_fails_nonzero_on_missing_input(self, tmp_path):
        completed = _run_generator(
            "--input", str(tmp_path / "does_not_exist.jsonl"),
            "--output", str(tmp_path / "out.jsonl"),
        )
        assert completed.returncode == 1
        assert "not found" in completed.stderr

    def test_committed_sample_artifact_matches_regeneration(self, tmp_path):
        """The committed sample checkpoints stay in sync with the code path."""
        assert _SAMPLE_CHECKPOINTS.exists(), (
            "artifacts/audit_anchoring/sample_checkpoints.jsonl must be committed; "
            "regenerate with scripts/generate_audit_checkpoints.py"
        )
        out = tmp_path / "regen.jsonl"
        completed = _run_generator("--output", str(out))
        assert completed.returncode == 0, completed.stderr
        assert out.read_bytes() == _SAMPLE_CHECKPOINTS.read_bytes(), (
            "committed sample artifact drifted from the generator output; "
            "re-run scripts/generate_audit_checkpoints.py and commit the result"
        )

    def test_committed_sample_artifact_verifies_against_demo_chain(self):
        """Inclusion + consistency verification of the committed artifact."""
        checkpoints = [
            Checkpoint.from_dict(json.loads(line))
            for line in _SAMPLE_CHECKPOINTS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert checkpoints, "sample artifact must contain at least one checkpoint"
        ok, problems = verify_checkpoint_chain(checkpoints)
        assert ok is True, problems

        result = replay_action_log(str(_DEMO_LOG))
        assert verify_envelope_hash_chain(result.envelopes) is True
        leaves = envelope_chain_leaves(result.envelopes)
        assert checkpoints[-1].seq_end == len(leaves) - 1
        for checkpoint in checkpoints:
            span = leaves[checkpoint.seq_start:checkpoint.seq_end + 1]
            assert verify_span(span, checkpoint) is True
