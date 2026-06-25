from __future__ import annotations

from remora.adapters.storage.control_plane import InMemoryControlPlaneStore


def test_inmemory_control_plane_store_is_append_only_latest_read() -> None:
    store = InMemoryControlPlaneStore()

    store.save_decision(
        request_id="req-1",
        tenant_id="t1",
        envelope={"v": 1, "decision": "verify"},
        audit_record={"v": 1, "decision": "verify"},
    )
    store.save_decision(
        request_id="req-1",
        tenant_id="t1",
        envelope={"v": 2, "decision": "accept"},
        audit_record={"v": 2, "decision": "accept"},
    )

    # Reads should resolve to latest version.
    assert store.get_envelope(request_id="req-1", tenant_id="t1") == {
        "v": 2,
        "decision": "accept",
    }
    assert store.get_audit_record(request_id="req-1", tenant_id="t1") == {
        "v": 2,
        "decision": "accept",
    }

    # Internal storage keeps historical versions (append-only semantics).
    assert len(store._decisions[("t1", "req-1")]) == 2
    assert len(store._audit[("t1", "req-1")]) == 2


def test_inmemory_control_plane_store_tenant_isolation() -> None:
    store = InMemoryControlPlaneStore()

    store.save_decision(
        request_id="req-2",
        tenant_id="tenant-a",
        envelope={"decision": "accept"},
        audit_record={"decision": "accept"},
    )

    assert store.get_envelope(request_id="req-2", tenant_id="tenant-b") is None
    assert store.get_audit_record(request_id="req-2", tenant_id="tenant-b") is None


def test_inmemory_store_evidence_is_tenant_scoped() -> None:
    from remora.adapters.storage.control_plane import EvidenceRecord

    store = InMemoryControlPlaneStore()
    store.save_decision(
        request_id="req-ev",
        tenant_id="tenant-a",
        envelope={"decision": "verify"},
        audit_record={"decision": "verify"},
    )
    store.create_evidence(
        EvidenceRecord(
            request_id="req-ev",
            tenant_id="tenant-a",
            evidence_type="runbook",
            payload={"ref": "rb-1"},
            submitted_by="bot",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    assert store.get_evidence(request_id="req-ev", tenant_id="tenant-a") != []
    assert store.get_evidence(request_id="req-ev", tenant_id="tenant-b") == []


def test_inmemory_store_get_latest_audit_record_is_tenant_scoped() -> None:
    store = InMemoryControlPlaneStore()
    store.save_decision(
        request_id="req-audit-a",
        tenant_id="tenant-a",
        envelope={"decision": "accept"},
        audit_record={"tenant_id": "tenant-a", "decision": "accept"},
    )
    store.save_decision(
        request_id="req-audit-b",
        tenant_id="tenant-b",
        envelope={"decision": "escalate"},
        audit_record={"tenant_id": "tenant-b", "decision": "escalate"},
    )

    latest_a = store.get_latest_audit_record_for_tenant(tenant_id="tenant-a")
    assert latest_a is not None
    assert latest_a["tenant_id"] == "tenant-a"

    latest_b = store.get_latest_audit_record_for_tenant(tenant_id="tenant-b")
    assert latest_b is not None
    assert latest_b["tenant_id"] == "tenant-b"

    assert latest_a["decision"] != latest_b["decision"]


def test_inmemory_store_reviews_do_not_cross_tenants() -> None:
    from remora.adapters.storage.control_plane import ReviewRecord

    store = InMemoryControlPlaneStore()
    store.create_review(
        ReviewRecord(
            request_id="req-rev",
            tenant_id="tenant-a",
            reviewer_id="alice",
            decision="approved",
            reason="looks good",
            evidence_refs=[],
            created_at="2026-01-01T00:00:00Z",
        )
    )

    reviews_a = [r for r in store._reviews if r.tenant_id == "tenant-a"]
    reviews_b = [r for r in store._reviews if r.tenant_id == "tenant-b"]
    assert len(reviews_a) == 1
    assert len(reviews_b) == 0
