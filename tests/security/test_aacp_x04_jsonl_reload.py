# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AACP-X-04: a persisted JSONL audit log must verify after a reload.

``JSONLAudit.append`` hashes the entry with ``oracle_count``, ``verdict`` and
``policy_version`` merged into the metadata, but writes the caller's metadata
without them. Before the fix, ``_load_existing_chain`` rebuilt each entry from
the written metadata, so every reloaded log failed ``verify()``, untouched or
not, and a tampered log could not be told from an honest one.

The fixture ``LEGACY_LOG`` was written by the code at 06c2f8f (the revision
AACP assessed) and must keep verifying: logs on disk are not rewritten.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.adapters.audit import AuditEntry
from remora.adapters.audit.jsonl import JSONLAudit, JSONLAuditIntegrityError

# Three records written by remora/adapters/audit/jsonl.py at 06c2f8f0 (before
# this fix) with the entries built by _entry(i) below. Do not regenerate.
LEGACY_LOG = Path(__file__).parent / "fixtures" / "jsonl_audit_06c2f8f.jsonl"


def _entry(i: int, metadata: dict | None = None) -> AuditEntry:
    return AuditEntry(
        timestamp=datetime(2026, 11, 8, 0, 0, i, tzinfo=UTC),
        question_hash=f"q{i}",
        action="accept",
        trust_score=0.9,
        phase="stable",
        oracle_count=3,
        verdict="ok",
        policy_version="v1",
        metadata={"n": i} if metadata is None else metadata,
    )


def _write(path: Path, n: int = 3) -> JSONLAudit:
    log = JSONLAudit(str(path))
    for i in range(n):
        log.append(_entry(i))
    return log


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def test_untouched_log_verifies_after_reload(tmp_path):
    path = tmp_path / "audit.jsonl"
    assert _write(path).verify()
    reloaded = JSONLAudit(str(path))
    assert reloaded.verify()
    assert reloaded.load_problems == ()


def test_reloaded_log_keeps_extending_and_verifying(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path, 2)
    log = JSONLAudit(str(path))
    log.append(_entry(2))
    assert JSONLAudit(str(path)).verify()


def test_caller_metadata_with_colliding_keys_round_trips(tmp_path):
    # The augmented keys override caller metadata at append; the reload must
    # apply the same precedence or the hash differs.
    path = tmp_path / "audit.jsonl"
    log = JSONLAudit(str(path))
    log.append(_entry(0, metadata={"verdict": "caller", "oracle_count": 99}))
    log.append(_entry(1, metadata=None))
    assert JSONLAudit(str(path)).verify()


def test_none_metadata_round_trips(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = JSONLAudit(str(path))
    log.append(dataclasses.replace(_entry(0), metadata=None))
    assert JSONLAudit(str(path)).verify()


def test_log_written_before_the_fix_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_bytes(LEGACY_LOG.read_bytes())
    log = JSONLAudit(str(path))
    assert log.verify()
    # Loading never rewrites evidence.
    assert path.read_bytes() == LEGACY_LOG.read_bytes()


@pytest.mark.parametrize("field,value", [
    ("trust_score", 0.1),
    ("action", "escalate"),
    ("verdict", "tampered"),
    ("oracle_count", 1),
    ("policy_version", "v9"),
    ("metadata", {"n": 42}),
])
def test_edited_record_fails_verification(tmp_path, field, value):
    path = tmp_path / "audit.jsonl"
    _write(path)
    lines = _lines(path)
    rec = json.loads(lines[1])
    rec[field] = value
    lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    assert not JSONLAudit(str(path)).verify()


def test_reordered_records_fail_verification(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path)
    lines = _lines(path)
    lines[1], lines[2] = lines[2], lines[1]
    path.write_text("\n".join(lines) + "\n")
    assert not JSONLAudit(str(path)).verify()


def test_removed_middle_record_fails_verification(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path)
    lines = _lines(path)
    del lines[1]
    path.write_text("\n".join(lines) + "\n")
    assert not JSONLAudit(str(path)).verify()


def test_removed_first_record_fails_verification(tmp_path):
    # The new first record still names its predecessor; a genesis record has
    # previous_hash null, so the cut is visible.
    path = tmp_path / "audit.jsonl"
    _write(path)
    path.write_text("\n".join(_lines(path)[1:]) + "\n")
    assert not JSONLAudit(str(path)).verify()


def test_removed_last_record_needs_an_external_head(tmp_path):
    # A hash chain alone cannot see its own tail cut off (AACP-X-01 for JSONL).
    # The local check still passes; an anchor held elsewhere catches it.
    path = tmp_path / "audit.jsonl"
    log = _write(path)
    head = log.head()
    assert head == (2, log._chain.entries()[-1].entry_hash)
    path.write_text("\n".join(_lines(path)[:-1]) + "\n")
    truncated = JSONLAudit(str(path))
    assert truncated.verify()  # documented limit: local consistency only
    assert not truncated.verify(expected_head=head)
    assert JSONLAudit(str(path)).head() == (1, json.loads(_lines(path)[-1])["entry_hash"])


def test_expected_head_matches_intact_log(tmp_path):
    path = tmp_path / "audit.jsonl"
    head = _write(path).head()
    assert JSONLAudit(str(path)).verify(expected_head=head)


def test_empty_log_head_and_anchor(tmp_path):
    log = JSONLAudit(str(tmp_path / "audit.jsonl"))
    assert log.head() is None
    assert log.verify()
    assert log.verify(expected_head=None)
    assert not log.verify(expected_head=(0, "0" * 64))


def test_truncated_final_line_fails_safely_and_is_not_rewritten(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path)
    damaged = path.read_bytes()[:-20]  # a crash mid-write
    path.write_bytes(damaged)
    log = JSONLAudit(str(path))
    assert not log.verify()
    assert any(p.startswith("unreadable_record_at:3") for p in log.load_problems)
    with pytest.raises(JSONLAuditIntegrityError):
        log.append(_entry(9))
    assert path.read_bytes() == damaged


@pytest.mark.parametrize("missing", [
    "timestamp", "question_hash", "action", "trust_score", "phase",
    "entry_hash", "oracle_count", "verdict", "policy_version",
])
def test_missing_required_field_fails_safely(tmp_path, missing):
    path = tmp_path / "audit.jsonl"
    _write(path)
    lines = _lines(path)
    rec = json.loads(lines[0])
    del rec[missing]
    lines[0] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    log = JSONLAudit(str(path))
    assert not log.verify()
    assert any(p.startswith("malformed_record_at:1") for p in log.load_problems)


@pytest.mark.parametrize("bad", ['[1,2,3]', '"a string"', '{"metadata": "x"}'])
def test_non_object_or_badly_typed_record_fails_safely(tmp_path, bad):
    path = tmp_path / "audit.jsonl"
    _write(path)
    with open(path, "a") as f:
        f.write(bad + "\n")
    log = JSONLAudit(str(path))
    assert not log.verify()
    assert log.load_problems


def test_bad_metadata_type_fails_safely(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path)
    lines = _lines(path)
    rec = json.loads(lines[2])
    rec["metadata"] = ["not", "a", "dict"]
    lines[2] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    log = JSONLAudit(str(path))
    assert not log.verify()
    assert any(p.startswith("malformed_record_at:3") for p in log.load_problems)


def test_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path)
    path.write_text(path.read_text().replace("\n", "\n\n"))
    assert JSONLAudit(str(path)).verify()


def test_query_still_reads_the_persisted_records(tmp_path):
    path = tmp_path / "audit.jsonl"
    _write(path)
    rows = JSONLAudit(str(path)).query()
    assert [r.question_hash for r in rows] == ["q2", "q1", "q0"]
    assert rows[0].metadata["n"] == 2
    assert "_hash" in rows[0].metadata


def test_persisted_record_format_is_unchanged(tmp_path):
    # Serialisation stays as it was so existing readers keep working: the
    # record carries the caller's metadata, not the augmented copy.
    path = tmp_path / "audit.jsonl"
    _write(path, 1)
    rec = json.loads(_lines(path)[0])
    assert rec["metadata"] == {"n": 0}
    assert set(rec) == {
        "timestamp", "question_hash", "action", "trust_score", "phase",
        "oracle_count", "verdict", "policy_version", "metadata",
        "previous_hash", "entry_hash", "hash_algorithm", "signature_status",
    }
