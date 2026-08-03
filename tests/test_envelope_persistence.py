# SPDX-License-Identifier: BUSL-1.1
"""DecisionEnvelope persistence: durability, retrieval, and chain verification.

These tests pin the property the governance story depends on: a decision that
was made can still be produced, and proven unmodified, after the process that
made it is gone. Anything less is a call log, not an audit trail.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.adapters.storage import (
    EvidenceRecord,
    FollowUpRecord,
    InMemoryControlPlaneStore,
    ReviewRecord,
    SQLiteControlPlaneStore,
    verify_audit_record_chain,
)
from remora.shadow.replay import (
    describe_envelope_hash_chain_breaks,
    load_envelopes_jsonl,
    replay_action_log,
    verify_envelope_file,
    verify_envelope_hash_chain,
)

SAMPLE_LOG = "artifacts/demo/shadow_mode_sample_agent_action_log.jsonl"


# ── Durability ────────────────────────────────────────────────────────────────


def test_sqlite_store_survives_reopen(tmp_path: Path) -> None:
    """The whole point: envelopes outlive the process that wrote them."""
    db = str(tmp_path / "cp.db")
    SQLiteControlPlaneStore(db_path=db).save_decision(
        request_id="req-1",
        tenant_id="t1",
        envelope={"gate": {"outcome": "escalate"}},
        audit_record={"request_id": "req-1", "decision": "escalate"},
    )

    # A new store object over the same file stands in for a restarted process.
    reopened = SQLiteControlPlaneStore(db_path=db)
    assert reopened.get_envelope(request_id="req-1", tenant_id="t1") == {
        "gate": {"outcome": "escalate"}
    }
    assert reopened.get_audit_record(request_id="req-1", tenant_id="t1") == {
        "request_id": "req-1",
        "decision": "escalate",
    }


def test_in_memory_store_declares_itself_non_durable() -> None:
    """A volatile store must never be mistaken for an audit store."""
    assert InMemoryControlPlaneStore().durable is False


def test_sqlite_store_declares_itself_durable(tmp_path: Path) -> None:
    assert SQLiteControlPlaneStore(db_path=str(tmp_path / "cp.db")).durable is True


def test_sqlite_store_is_append_only(tmp_path: Path) -> None:
    """Re-deciding a request adds a version; it never overwrites the old one."""
    store = SQLiteControlPlaneStore(db_path=str(tmp_path / "cp.db"))
    for version, outcome in ((1, "verify"), (2, "accept")):
        store.save_decision(
            request_id="req-1",
            tenant_id="t1",
            envelope={"v": version, "decision": outcome},
            audit_record={"v": version, "decision": outcome},
        )

    assert store.get_envelope(request_id="req-1", tenant_id="t1") == {
        "v": 2,
        "decision": "accept",
    }
    # Both versions are still on disk.
    rows = store._conn().execute(
        "SELECT COUNT(*) FROM remora_control_plane_decision_versions "
        "WHERE request_id='req-1' AND tenant_id='t1'"
    ).fetchone()
    assert rows[0] == 2


def test_sqlite_store_is_tenant_scoped(tmp_path: Path) -> None:
    store = SQLiteControlPlaneStore(db_path=str(tmp_path / "cp.db"))
    store.save_decision(
        request_id="req-1",
        tenant_id="tenant-a",
        envelope={"decision": "accept"},
        audit_record={"decision": "accept"},
    )
    assert store.get_envelope(request_id="req-1", tenant_id="tenant-b") is None
    assert store.get_audit_record(request_id="req-1", tenant_id="tenant-b") is None
    assert store.list_audit_records_for_tenant(tenant_id="tenant-b") == []


def test_sqlite_store_round_trips_review_followup_evidence(tmp_path: Path) -> None:
    store = SQLiteControlPlaneStore(db_path=str(tmp_path / "cp.db"))
    store.save_decision(
        request_id="req-1", tenant_id="t1", envelope={}, audit_record={}
    )
    store.create_review(
        ReviewRecord(
            request_id="req-1",
            tenant_id="t1",
            reviewer_id="reviewer@example.test",
            decision="approved",
            reason="checked source",
            evidence_refs=["ref-1"],
            created_at="2026-08-03T10:00:00+00:00",
        )
    )
    store.create_follow_up(
        FollowUpRecord(
            request_id="req-1",
            tenant_id="t1",
            follow_up_type="human_review",
            requested_by="ops",
            payload={"note": "escalated"},
            created_at="2026-08-03T10:01:00+00:00",
        )
    )
    store.create_evidence(
        EvidenceRecord(
            request_id="req-1",
            tenant_id="t1",
            evidence_type="document",
            payload={"url": "https://example.test/doc"},
            submitted_by="ops",
            created_at="2026-08-03T10:02:00+00:00",
        )
    )

    reopened = SQLiteControlPlaneStore(db_path=str(tmp_path / "cp.db"))
    evidence = reopened.get_evidence(request_id="req-1", tenant_id="t1")
    assert len(evidence) == 1
    assert evidence[0]["payload"] == {"url": "https://example.test/doc"}
    # Reviews and follow-ups persisted alongside.
    conn = reopened._conn()
    assert conn.execute("SELECT COUNT(*) FROM remora_control_plane_reviews").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM remora_control_plane_followups").fetchone()[0] == 1


def test_sqlite_store_lists_audit_records_in_write_order(tmp_path: Path) -> None:
    store = SQLiteControlPlaneStore(db_path=str(tmp_path / "cp.db"))
    for i in range(3):
        store.save_decision(
            request_id=f"req-{i}",
            tenant_id="t1",
            envelope={},
            audit_record={"request_id": f"req-{i}"},
        )
    records = store.list_audit_records_for_tenant(tenant_id="t1")
    assert [r["request_id"] for r in records] == ["req-0", "req-1", "req-2"]


# ── Audit-record chain linkage ────────────────────────────────────────────────


def _linked_records() -> list[dict]:
    return [
        {"request_id": "r0", "envelope_previous_hash": None, "envelope_audit_hash": "h0"},
        {"request_id": "r1", "envelope_previous_hash": "h0", "envelope_audit_hash": "h1"},
        {"request_id": "r2", "envelope_previous_hash": "h1", "envelope_audit_hash": "h2"},
    ]


def test_audit_record_chain_accepts_intact_trail() -> None:
    ok, breaks = verify_audit_record_chain(_linked_records())
    assert ok is True
    assert breaks == []


def test_audit_record_chain_detects_a_removed_decision() -> None:
    """Deleting a middle record must be detectable, not silently plausible."""
    records = _linked_records()
    del records[1]
    ok, breaks = verify_audit_record_chain(records)
    assert ok is False
    assert any("r2" in b for b in breaks)


def test_audit_record_chain_flags_a_record_with_no_hash() -> None:
    records = _linked_records()
    records[1]["envelope_audit_hash"] = None
    ok, breaks = verify_audit_record_chain(records)
    assert ok is False
    assert any("missing envelope_audit_hash" in b for b in breaks)


def test_empty_trail_verifies_but_proves_nothing() -> None:
    # Documented behaviour, not an accident: callers must check the count too.
    assert verify_audit_record_chain([]) == (True, [])


# ── Shadow-mode envelopes: persist, reload, verify ────────────────────────────


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("shadow")
    replay_action_log(
        SAMPLE_LOG,
        output_envelopes_jsonl=str(out_dir / "decision_envelopes.jsonl"),
        output_report_json=str(out_dir / "report.json"),
    )
    return out_dir / "decision_envelopes.jsonl"


def test_replayed_envelopes_reload_from_disk(replayed: Path) -> None:
    envelopes = load_envelopes_jsonl(str(replayed))
    assert envelopes, "sample log must produce envelopes"
    # Round-trip fidelity: reloaded envelopes verify with the same rule the
    # in-memory ones do.
    assert verify_envelope_hash_chain(envelopes) is True


def test_persisted_envelope_file_verifies(replayed: Path) -> None:
    ok, breaks = verify_envelope_file(str(replayed))
    assert ok is True
    assert breaks == []


def test_tampering_with_a_persisted_envelope_is_detected(
    replayed: Path, tmp_path: Path
) -> None:
    """Editing a stored verdict must break verification, and say where."""
    lines = replayed.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["gate"]["outcome"] = "accept"
    lines[1] = json.dumps(record, sort_keys=True)

    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, breaks = verify_envelope_file(str(tampered))
    assert ok is False
    assert any("does not match the recomputed payload hash" in b for b in breaks)


def test_chain_break_report_names_every_failure(replayed: Path) -> None:
    envelopes = load_envelopes_jsonl(str(replayed))
    from dataclasses import replace

    from remora.governance.envelope import AuditBlock

    broken = list(envelopes)
    broken[1] = replace(
        broken[1], audit=AuditBlock(**{**broken[1].audit.__dict__, "hash": "deadbeef"})
    )
    breaks = describe_envelope_hash_chain_breaks(broken)
    # Both the corrupted entry and its now-orphaned successor are reported.
    assert len(breaks) >= 2


def test_unparseable_line_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    """A short trail that verifies is worse than a loud failure."""
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json at all\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_envelopes_jsonl(str(bad))


def test_non_envelope_line_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"request": {}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not a DecisionEnvelope"):
        load_envelopes_jsonl(str(bad))


def test_replay_persists_envelopes_to_a_durable_store(tmp_path: Path) -> None:
    """Shadow-mode decisions land in the same queryable control plane as live ones."""
    db = str(tmp_path / "shadow.db")
    store = SQLiteControlPlaneStore(db_path=db)
    result = replay_action_log(SAMPLE_LOG, envelope_store=store, store_tenant_id="shadow")

    reopened = SQLiteControlPlaneStore(db_path=db)
    records = reopened.list_audit_records_for_tenant(tenant_id="shadow")
    assert len(records) == len(result.envelopes)
    assert all(r["source"] == "shadow_replay" for r in records)

    # Every replayed envelope is retrievable by its own request_id...
    first = result.envelopes[0]
    stored = reopened.get_envelope(
        request_id=first.request.request_id, tenant_id="shadow"
    )
    assert stored is not None
    assert stored["gate"]["outcome"] == first.gate.outcome

    # ...and the persisted records form an unbroken chain.
    ok, breaks = verify_audit_record_chain(records)
    assert ok is True, breaks


def test_shadow_envelopes_do_not_leak_into_another_tenant(tmp_path: Path) -> None:
    db = str(tmp_path / "shadow.db")
    store = SQLiteControlPlaneStore(db_path=db)
    replay_action_log(SAMPLE_LOG, envelope_store=store, store_tenant_id="shadow")
    assert store.list_audit_records_for_tenant(tenant_id="live") == []
