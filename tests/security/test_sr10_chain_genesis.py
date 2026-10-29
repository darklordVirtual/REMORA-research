"""SR-10 / SEC-02: the audit-trail verifier must anchor both ends of the chain.

On HEAD the verifier accepts ANY first record (``if index == 0: continue``),
so deleting the oldest N records still returns chain_valid: true, and it
returns no head hash or count, so deleting the newest N records is invisible
to an external anchor too.

The rule: the first record must be a genesis record (no predecessor) unless
the caller supplies a verified retention-checkpoint predecessor, and the
result carries head_hash and count for anchor comparison.
"""

from __future__ import annotations

from remora.adapters.storage.control_plane import verify_audit_record_chain


def _chain(n: int) -> list[dict]:
    records = []
    previous = None
    for i in range(n):
        current = f"h{i}"
        records.append({
            "request_id": f"r{i}",
            "envelope_audit_hash": current,
            "envelope_previous_hash": previous,
        })
        previous = current
    return records


def test_intact_chain_reports_genesis_head_and_count() -> None:
    result = verify_audit_record_chain(_chain(3))

    assert result.valid is True
    assert result.genesis_ok is True
    assert result.head_hash == "h2"
    assert result.count == 3
    assert result.breaks == ()


def test_dropping_the_oldest_records_breaks_genesis() -> None:
    """The review's attack: delete the first record; verification must fail."""
    trimmed = _chain(3)[1:]
    result = verify_audit_record_chain(trimmed)

    assert result.valid is False
    assert result.genesis_ok is False
    assert any(b.kind == "genesis_missing" for b in result.breaks)


def test_dropping_the_newest_record_moves_the_head_anchor() -> None:
    """Truncation at the tail is invisible to linkage but must move the
    anchor a caller compares against."""
    full = verify_audit_record_chain(_chain(3))
    trimmed = verify_audit_record_chain(_chain(3)[:2])

    assert trimmed.valid is True  # linkage among survivors is intact
    assert trimmed.head_hash != full.head_hash
    assert trimmed.count != full.count


def test_first_record_with_foreign_predecessor_is_genesis_missing() -> None:
    record = [{
        "request_id": "r0",
        "envelope_audit_hash": "h0",
        "envelope_previous_hash": "someone-elses-hash",
    }]
    result = verify_audit_record_chain(record)

    assert result.valid is False
    assert any(b.kind == "genesis_missing" for b in result.breaks)


def test_verified_retention_checkpoint_allows_a_mid_stream_start() -> None:
    """The one legitimate non-genesis start: a caller-supplied predecessor
    from a verified signed retention checkpoint."""
    trimmed = _chain(3)[1:]
    result = verify_audit_record_chain(
        trimmed, allow_genesis_predecessor="h0",
    )

    assert result.valid is True
    assert result.genesis_ok is True

    wrong = verify_audit_record_chain(trimmed, allow_genesis_predecessor="h9")
    assert wrong.valid is False


def test_link_break_still_reported_with_kind() -> None:
    records = _chain(3)
    records[2]["envelope_previous_hash"] = "wrong"
    result = verify_audit_record_chain(records)

    assert result.valid is False
    assert any(b.kind == "link_mismatch" for b in result.breaks)


def test_backward_compatible_unpacking() -> None:
    """Existing callers unpack (ok, breaks); keep that working."""
    ok, breaks = verify_audit_record_chain(_chain(2))
    assert ok is True
    assert list(breaks) == []


def test_missing_first_hash_does_not_report_a_verified_genesis() -> None:
    records = _chain(2)
    records[0]["envelope_audit_hash"] = None
    result = verify_audit_record_chain(records)

    assert result.valid is False
    assert result.genesis_ok is False
    assert any(b.kind == "missing_hash" for b in result.breaks)


def test_missing_last_hash_does_not_report_an_older_head() -> None:
    records = _chain(2)
    records[-1]["envelope_audit_hash"] = None
    result = verify_audit_record_chain(records)

    assert result.valid is False
    assert result.head_hash is None
    assert result.count == 2


def test_sqlite_cli_json_contains_machine_readable_anchors(tmp_path, monkeypatch, capsys) -> None:
    import json

    from remora.adapters.storage import SQLiteControlPlaneStore
    from scripts.verify_envelope_chain import main

    db = tmp_path / "audit.db"
    store = SQLiteControlPlaneStore(db_path=str(db))
    for record in _chain(2):
        store.save_decision(
            request_id=record["request_id"], tenant_id="shadow",
            envelope={"audit": {}}, audit_record=record,
        )
    monkeypatch.setattr("sys.argv", ["verify_envelope_chain.py", "--store-db", str(db), "--json"])

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["chain_valid"] is True
    assert result["genesis_ok"] is True
    assert result["head_hash"] == "h1"
    assert result["records_checked"] == 2
