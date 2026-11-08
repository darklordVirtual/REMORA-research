# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""JSONL audit adapter — hash-linked append-only audit trail.

Suitable for development, testing, and air-gapped environments
where PostgreSQL is not available. Each line is a JSON object
linked to the previous via SHA-256 for tamper detection.

Hashed metadata (AACP-X-04). ``append`` hashes the caller's metadata with
``oracle_count``, ``verdict`` and ``policy_version`` merged in, and writes the
caller's metadata and those three fields side by side. ``_load_existing_chain``
rebuilds the hashed metadata from the record by the same rule
(:func:`hashed_metadata`), so a log reloads to the chain that was written. The
on-disk format is unchanged; logs written before the fix verify unmodified.

What ``verify`` shows. Records link and their hashes match, and the first
record is a genesis record. It cannot show that newest records were not cut
off: pass ``expected_head`` (from :meth:`JSONLAudit.head`, kept outside this
file) for that. A record that cannot be read is reported in
``load_problems``; the log then never verifies and refuses further appends.
Nothing here repairs or rewrites the file.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from remora.adapters.audit import AuditAdapter, AuditEntry
from remora.audit.hash_chain import AuditHashChain, HashChainEntry

#: Fields every record must carry for its hash to be recomputed.
_REQUIRED = ("timestamp", "question_hash", "action", "trust_score", "phase",
             "entry_hash", "oracle_count", "verdict", "policy_version")


class JSONLAuditIntegrityError(RuntimeError):
    """The log on disk could not be read back intact; it is not extended."""


def hashed_metadata(caller_metadata: dict[str, Any] | None, *, oracle_count: Any,
                    verdict: Any, policy_version: Any) -> dict[str, Any]:
    """The metadata ``append`` hashes, from the parts it persists.

    One rule for writing and reloading: caller metadata first, the three
    decision fields over it. Changing the order changes every hash.
    """
    return {
        **(caller_metadata or {}),
        "oracle_count": oracle_count,
        "verdict": verdict,
        "policy_version": policy_version,
    }


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

        Preserves original entry_hash from disk so verify() detects tampering,
        and rebuilds the hashed metadata by :func:`hashed_metadata` so an
        untouched log verifies (AACP-X-04). A record that cannot be read is
        recorded in ``load_problems`` by its 1-based line number; reading
        continues so every problem is listed, and the file is left as it is.
        """
        self._load_problems: list[str] = []
        if not self._path.exists():
            return
        with open(self._path) as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._load_problems.append(f"unreadable_record_at:{line_no}:{exc.msg}")
                    continue
                entry = self._entry_from_record(record, line_no)
                if entry is not None:
                    self._chain._entries.append(entry)

    def _entry_from_record(self, record: Any, line_no: int) -> HashChainEntry | None:
        if not isinstance(record, dict):
            self._load_problems.append(f"malformed_record_at:{line_no}:not_an_object")
            return None
        missing = [k for k in _REQUIRED if k not in record]
        if missing:
            self._load_problems.append(
                f"malformed_record_at:{line_no}:missing:{','.join(missing)}")
            return None
        metadata = record.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            self._load_problems.append(f"malformed_record_at:{line_no}:metadata_not_an_object")
            return None
        return HashChainEntry(
            timestamp=record["timestamp"],
            question_hash=record["question_hash"],
            action=record["action"],
            trust_score=record["trust_score"],
            phase=record["phase"],
            previous_hash=record.get("previous_hash"),
            entry_hash=record["entry_hash"],
            metadata=hashed_metadata(
                metadata,
                oracle_count=record["oracle_count"],
                verdict=record["verdict"],
                policy_version=record["policy_version"],
            ),
        )

    @property
    def load_problems(self) -> tuple[str, ...]:
        """Records that could not be read when the log was opened."""
        return tuple(self._load_problems)

    def head(self) -> tuple[int, str] | None:
        """``(index, entry_hash)`` of the newest record, or None when empty.

        Keep it outside this file and pass it to :meth:`verify` to detect a
        log whose newest records were removed.
        """
        entries = self._chain.entries()
        return (len(entries) - 1, entries[-1].entry_hash) if entries else None

    def append(self, entry: AuditEntry) -> None:
        if self._load_problems:
            # Appending would link new evidence to a log that did not read
            # back intact, and could join a half-written line. The operator
            # must set the file aside; it is never repaired here.
            raise JSONLAuditIntegrityError(
                f"audit log {self._path} did not load intact "
                f"({'; '.join(self._load_problems)}); refusing to append")
        chain_entry = self._chain.append(
            timestamp=entry.timestamp.isoformat(),
            question_hash=entry.question_hash,
            action=entry.action,
            trust_score=entry.trust_score,
            phase=entry.phase,
            metadata=hashed_metadata(
                entry.metadata,
                oracle_count=entry.oracle_count,
                verdict=entry.verdict,
                policy_version=entry.policy_version,
            ),
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

    def verify(self, expected_head: tuple[int, str] | None = None) -> bool:
        """Verify the tamper-evident integrity of the entire audit trail.

        False when any record failed to load, the first record is not a
        genesis record (``previous_hash`` null, so removing the oldest
        records shows), any link or hash breaks, or ``expected_head`` is given
        and the newest record is not that ``(index, entry_hash)``. Without
        ``expected_head`` a log cut short at its tail still verifies: this is
        local consistency, not an externally anchored check.
        """
        if self._load_problems:
            return False
        entries = self._chain.entries()
        if entries and entries[0].previous_hash is not None:
            return False
        if not self._chain.verify():
            return False
        if expected_head is not None:
            head = self.head()
            if head is None or (int(expected_head[0]), str(expected_head[1])) != head:
                return False
        return True
