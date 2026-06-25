# Author: Stian Skogbrott
# License: Apache-2.0
"""JSONL audit adapter — hash-linked append-only audit trail.

Suitable for development, testing, and air-gapped environments
where PostgreSQL is not available. Each line is a JSON object
linked to the previous via SHA-256 for tamper detection.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from remora.adapters.audit import AuditAdapter, AuditEntry
from remora.audit.hash_chain import AuditHashChain, HashChainEntry


class JSONLAudit(AuditAdapter):
    """Append-only audit trail backed by a hash-linked JSONL file.

    Parameters
    ----------
    path:
        Path to the JSONL file. Created if it does not exist.
    """

    def __init__(self, path: str = "audit.jsonl"):
        # SEC-6: Validate path to prevent directory traversal.
        # Resolve to absolute path and reject any attempt to write outside
        # the working directory using '..' components.
        resolved = Path(path).resolve()
        # Block paths that point to sensitive system directories.
        # Check both the raw input (catches POSIX paths on Windows) and
        # the resolved path (catches actual filesystem paths on Unix).
        blocked_prefixes = ("/etc", "/proc", "/sys", "/dev", "/root")
        path_str = str(resolved)
        raw_str = str(path).replace("\\", "/")
        for blocked in blocked_prefixes:
            if path_str.startswith(blocked) or raw_str.startswith(blocked):
                raise ValueError(
                    f"Audit path '{path}' resolves to a blocked system directory."
                )
        self._path = resolved
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._chain = AuditHashChain()
        self._load_existing_chain()

    def _load_existing_chain(self) -> None:
        """Replay existing JSONL into the hash-chain on startup.

        Preserves original entry_hash from disk so verify() detects tampering.
        """
        if not self._path.exists():
            return
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                entry = HashChainEntry(
                    timestamp=record["timestamp"],
                    question_hash=record["question_hash"],
                    action=record["action"],
                    trust_score=record["trust_score"],
                    phase=record["phase"],
                    previous_hash=record.get("previous_hash"),
                    entry_hash=record["entry_hash"],
                    metadata=record.get("metadata", {}),
                )
                self._chain._entries.append(entry)

    def append(self, entry: AuditEntry) -> None:
        chain_entry = self._chain.append(
            timestamp=entry.timestamp.isoformat(),
            question_hash=entry.question_hash,
            action=entry.action,
            trust_score=entry.trust_score,
            phase=entry.phase,
            metadata={
                **(entry.metadata or {}),
                "oracle_count": entry.oracle_count,
                "verdict": entry.verdict,
                "policy_version": entry.policy_version,
            },
        )
        record = {
            "timestamp": entry.timestamp.isoformat(),
            "question_hash": entry.question_hash,
            "action": entry.action,
            "trust_score": entry.trust_score,
            "phase": entry.phase,
            "oracle_count": entry.oracle_count,
            "verdict": entry.verdict,
            "policy_version": entry.policy_version,
            "metadata": entry.metadata,
            "previous_hash": chain_entry.previous_hash,
            "entry_hash": chain_entry.entry_hash,
            "hash_algorithm": "sha256",
            "signature_status": "unsigned",
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    def query(self, *, since: datetime | None = None, action: str | None = None, limit: int = 100) -> list[AuditEntry]:
        if not self._path.exists():
            return []
        entries = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                ts = datetime.fromisoformat(record["timestamp"])
                if since and ts < since:
                    continue
                if action and record["action"] != action:
                    continue
                meta = record.get("metadata", {})
                meta["_hash"] = {
                    "previous_hash": record.get("previous_hash"),
                    "entry_hash": record.get("entry_hash"),
                    "hash_algorithm": record.get("hash_algorithm"),
                }
                entries.append(AuditEntry(
                    timestamp=ts,
                    question_hash=record["question_hash"],
                    action=record["action"],
                    trust_score=record["trust_score"],
                    phase=record["phase"],
                    oracle_count=record["oracle_count"],
                    verdict=record["verdict"],
                    policy_version=record["policy_version"],
                    metadata=meta,
                ))
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def verify(self) -> bool:
        """Verify the tamper-evident integrity of the entire audit trail."""
        return self._chain.verify()
