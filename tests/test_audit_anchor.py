"""Tests for remora.audit.anchor (PR-11)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone

from remora.adapters.audit import AuditEntry
from remora.adapters.audit.jsonl import JSONLAudit
from remora.audit.anchor import (
    AuditAnchor,
    anchor_from_jsonl,
    export_verify_command,
    verify_anchor_signature,
)


def test_anchor_empty_file_not_found() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = f"{td}/missing.jsonl"
        rec = anchor_from_jsonl(path)
        assert rec.entry_count == 0
        assert rec.chain_valid is True
        assert rec.error_message == "file_not_found"


def test_anchor_valid_chain() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = f"{td}/audit.jsonl"
        audit = JSONLAudit(path=path)
        for i in range(3):
            audit.append(
                AuditEntry(
                    timestamp=datetime.now(timezone.utc),
                    question_hash=f"q{i}",
                    action="ACCEPT",
                    trust_score=0.8,
                    phase="ordered",
                    oracle_count=3,
                    verdict="ACCEPT",
                    policy_version="v1",
                    metadata={},
                )
            )
        rec = anchor_from_jsonl(path)
        assert rec.entry_count == 3
        assert rec.chain_valid is True
        assert rec.root_hash


def test_anchor_detects_broken_chain() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = f"{td}/audit.jsonl"
        audit = JSONLAudit(path=path)
        for i in range(2):
            audit.append(
                AuditEntry(
                    timestamp=datetime.now(timezone.utc),
                    question_hash=f"q{i}",
                    action="ACCEPT",
                    trust_score=0.8,
                    phase="ordered",
                    oracle_count=3,
                    verdict="ACCEPT",
                    policy_version="v1",
                    metadata={},
                )
            )

        # Tamper entry[1].previous_hash
        with open(path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rows[1]["previous_hash"] = "deadbeef"
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        rec = AuditAnchor(path).anchor()
        assert rec.chain_valid is False
        assert rec.broken_at_index == 1
        assert "chain_broken" in (rec.error_message or "")


def test_root_fingerprint_stable_for_same_file() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = f"{td}/audit.jsonl"
        audit = JSONLAudit(path=path)
        audit.append(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                question_hash="q0",
                action="ACCEPT",
                trust_score=0.8,
                phase="ordered",
                oracle_count=3,
                verdict="ACCEPT",
                policy_version="v1",
                metadata={},
            )
        )
        a1 = AuditAnchor(path).root_fingerprint()
        a2 = AuditAnchor(path).root_fingerprint()
        assert a1 == a2
        assert len(a1) == 16


def test_anchor_signs_record_when_key_configured() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = f"{td}/audit.jsonl"
        audit = JSONLAudit(path=path)
        audit.append(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                question_hash="q0",
                action="ACCEPT",
                trust_score=0.8,
                phase="ordered",
                oracle_count=3,
                verdict="ACCEPT",
                policy_version="v1",
                metadata={},
            )
        )

        rec = AuditAnchor(path, signing_key="test-key").anchor()
        assert rec.signature is not None
        assert rec.signature_algorithm == "hmac-sha256"
        assert verify_anchor_signature(rec, signing_key="test-key") is True
        assert verify_anchor_signature(rec, signing_key="wrong-key") is False


def test_export_verify_command_contains_paths_and_key_env() -> None:
    cmd = export_verify_command(
        jsonl_path="audit/live.jsonl",
        anchor_record_path="artifacts/audit_anchor.json",
        key_env_var="REMORA_AUDIT_ANCHOR_KEY",
    )
    assert "scripts/verify_audit_anchor.py" in cmd
    assert "--audit-jsonl audit/live.jsonl" in cmd
    assert "--anchor-record artifacts/audit_anchor.json" in cmd
    assert "--key-env REMORA_AUDIT_ANCHOR_KEY" in cmd
