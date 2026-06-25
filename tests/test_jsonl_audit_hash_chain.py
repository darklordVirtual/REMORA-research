"""Tests for JSONL audit adapter with integrated hash-chain."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone

from remora.adapters.audit.jsonl import JSONLAudit
from remora.adapters.audit import AuditEntry


def test_append_writes_hash_fields() -> None:
    with tempfile.TemporaryDirectory() as td:
        audit = JSONLAudit(path=f"{td}/audit.jsonl")
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            question_hash="abc123",
            action="ACCEPT",
            trust_score=0.85,
            phase="ordered",
            oracle_count=3,
            verdict="ACCEPT",
            policy_version="v1.2",
            metadata={"domain": "well_engineering"},
        )
        audit.append(entry)

        with open(f"{td}/audit.jsonl") as f:
            record = __import__("json").loads(f.readline())

        assert "previous_hash" in record
        assert "entry_hash" in record
        assert record["hash_algorithm"] == "sha256"
        assert record["signature_status"] == "unsigned"
        # Genesis entry has None previous_hash
        assert record["previous_hash"] is None
        assert len(record["entry_hash"]) == 64  # SHA-256 hex


def test_second_entry_links_to_first() -> None:
    with tempfile.TemporaryDirectory() as td:
        audit = JSONLAudit(path=f"{td}/audit.jsonl")
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

        with open(f"{td}/audit.jsonl") as f:
            lines = f.readlines()

        first = __import__("json").loads(lines[0])
        second = __import__("json").loads(lines[1])

        assert second["previous_hash"] == first["entry_hash"]
        assert second["entry_hash"] != first["entry_hash"]


def test_verify_passes_for_valid_chain() -> None:
    with tempfile.TemporaryDirectory() as td:
        audit = JSONLAudit(path=f"{td}/audit.jsonl")
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
        assert audit.verify() is True


def test_verify_fails_after_tamper() -> None:
    import json
    with tempfile.TemporaryDirectory() as td:
        path = f"{td}/audit.jsonl"
        audit = JSONLAudit(path=path)
        audit.append(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                question_hash="q1",
                action="ACCEPT",
                trust_score=0.8,
                phase="ordered",
                oracle_count=3,
                verdict="ACCEPT",
                policy_version="v1",
                metadata={},
            )
        )
        # Tamper with the file
        with open(path) as f:
            record = json.loads(f.readline())
        record["trust_score"] = 0.99
        with open(path, "w") as f:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

        # Reload adapter — chain replay will detect tamper on verify
        audit2 = JSONLAudit(path=path)
        assert audit2.verify() is False


def test_query_returns_hash_in_metadata() -> None:
    with tempfile.TemporaryDirectory() as td:
        audit = JSONLAudit(path=f"{td}/audit.jsonl")
        audit.append(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                question_hash="q1",
                action="ACCEPT",
                trust_score=0.8,
                phase="ordered",
                oracle_count=3,
                verdict="ACCEPT",
                policy_version="v1",
                metadata={"key": "val"},
            )
        )
        entries = audit.query(limit=1)
        assert len(entries) == 1
        assert "_hash" in entries[0].metadata
        assert entries[0].metadata["_hash"]["hash_algorithm"] == "sha256"
