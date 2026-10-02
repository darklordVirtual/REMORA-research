# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for AuditAnchor.anchor() tamper detection."""
from __future__ import annotations

import json

from remora.audit.anchor import AuditAnchor
from remora.audit.hash_chain import AuditHashChain


def _write(path, chain):
    path.write_text("\n".join(json.dumps(d) for d in chain.to_dicts()) + "\n", encoding="utf-8")


def _chain(n=4):
    chain = AuditHashChain()
    for i in range(n):
        chain.append(timestamp=f"2026-01-0{i + 1}T00:00:00", question_hash=f"q{i}",
                     action="accept", trust_score=0.9, phase="solid", metadata={})
    return chain


def test_valid_chain_stays_valid(tmp_path):
    p = tmp_path / "a.jsonl"
    _write(p, _chain())
    rec = AuditAnchor(str(p)).anchor()
    assert rec.chain_valid and rec.entry_count == 4


def test_edited_action_with_hashes_kept_is_detected(tmp_path):
    p = tmp_path / "a.jsonl"
    rows = _chain().to_dicts()
    rows[1]["action"] = "abstain"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    rec = AuditAnchor(str(p)).anchor()
    assert rec.chain_valid is False
    assert rec.broken_at_index == 1


def test_forged_genesis_previous_hash_is_detected(tmp_path):
    p = tmp_path / "a.jsonl"
    rows = _chain().to_dicts()
    rows[0]["previous_hash"] = "f" * 64
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert AuditAnchor(str(p)).anchor().chain_valid is False


def test_missing_file_is_not_a_valid_chain(tmp_path):
    rec = AuditAnchor(str(tmp_path / "gone.jsonl")).anchor()
    assert rec.chain_valid is False
    assert rec.error_message == "file_not_found"
