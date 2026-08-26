# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-02: the design doc's crash matrix, executed instead of asserted.

``docs/design/execution-lifecycle-outbox-v1.md`` §3.4 tabulates six crash
points and the recovery each should produce. A table is a claim; these
tests are the evidence. Each case injects a failure at the named point
and asserts the state the design promises.

Scope, declared: the synchronous v1 path (execute waits for the outcome).
Crashes are injected by making a step raise — the process is not actually
killed, so this validates the ORDERING and rollback semantics of the
recovery design, not operating-system-level durability. Rows 3, 4 and 6
of the matrix are deliberately indistinguishable by design (a claimed row
whose worker never reported cannot be told apart from one that did
invoke), and that conflation is asserted rather than papered over.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement.outbox import OutboxState  # noqa: E402
from remora.governance.review_queue import ItemStatus  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "fault-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "fault-injection-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.delenv("REMORA_OUTBOX_STALE_SECONDS", raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    return TestClient(api_mod.app, raise_server_exceptions=False)


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


def _approved_item(client) -> str:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert item_id
    assert client.post(
        "/v1/execution/approve", json={"item_id": item_id}
    ).status_code == 200
    return item_id


def _item_status(item_id: str):
    exec_mod = _mod()
    with exec_mod.db_transaction_state("acme") as q:
        return q.item(item_id).status


# ── Row 1: crash before the authorize+outbox transaction commits ───────────

def test_row1_crash_before_authorize_commit_leaves_nothing_behind(
    client, monkeypatch
) -> None:
    """Design: rolled back — item stays APPROVED, no outbox row. The client
    may safely re-call, because the approval was never consumed."""
    item_id = _approved_item(client)
    exec_mod = _mod()

    original = exec_mod._record_dispatch_intent
    crashing = {"on": True}

    def maybe_boom(**kwargs):
        # A flag rather than monkeypatch.undo(): undo() would also revert the
        # fixture's auth patches, and the follow-up call would run as a
        # different tenant and 404 on its own item.
        if crashing["on"]:
            raise RuntimeError("crash inside the authorize transaction")
        return original(**kwargs)

    monkeypatch.setattr(exec_mod, "_record_dispatch_intent", maybe_boom)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code >= 500, "an injected crash must not look like success"

    crashing["on"] = False
    assert _item_status(item_id) is ItemStatus.APPROVED, (
        "a rolled-back authorization must leave the item re-executable"
    )
    assert exec_mod._outbox().pending("acme") == []

    # And the re-call succeeds: the approval really was unconsumed.
    again = client.post("/v1/execution/execute",
                        json={"item_id": item_id, "tool_call": CALL})
    assert again.status_code == 200, again.text
    assert again.json()["outcome"] == "execute"


# ── Row 2: crash after commit, before the dispatch is claimed ──────────────

def test_row2_authorized_but_never_claimed_is_reconciled_as_failed(
    client, monkeypatch
) -> None:
    """Design: the intent must not linger unresolved.

    In the synchronous v1 path the claim strictly precedes dispatch, so a
    row that never reached DISPATCHING was never dispatched — the side
    effect provably did NOT happen, which makes FAILED the honest terminal
    rather than UNKNOWN.
    """
    item_id = _approved_item(client)
    exec_mod = _mod()

    outbox = exec_mod._outbox()
    original_claim = outbox.claim
    crashing = {"on": True}

    def crash_after_commit(*args, **kwargs):
        if crashing["on"]:
            raise RuntimeError("crash after authorize commit, before claim")
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(outbox, "claim", crash_after_commit)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code >= 500
    crashing["on"] = False

    orphan = exec_mod._outbox().pending("acme")
    assert len(orphan) == 1, "the authorize transaction did commit an intent"

    settled = exec_mod.reconcile_stale_dispatches(
        "acme", now=datetime.now(UTC) + timedelta(hours=2)
    )
    assert [r.outbox_id for r in settled] == [orphan[0].outbox_id]
    assert exec_mod._outbox().get(orphan[0].outbox_id).state is OutboxState.FAILED
    assert exec_mod._outbox().pending("acme") == []


# ── Rows 3, 4, 6: claimed, then silence — deliberately indistinguishable ───

def test_rows_3_4_6_claimed_then_silent_collapse_to_unknown(client) -> None:
    """Design: a claimed row whose worker never reported cannot be told
    apart from one that did invoke the tool, so all three rows collapse to
    UNKNOWN. Asserting the conflation keeps it a declared limitation."""
    exec_mod = _mod()
    outbox = exec_mod._outbox()
    row = outbox.record_intent(
        proposal_id="p-silent", tenant_id="acme", item_id="i",
        tool_name="store_artifact", tool_call_hash="d" * 64, grant_jti="j",
    )
    outbox.claim(row.outbox_id, worker_id="w",
                 now=datetime.now(UTC) - timedelta(hours=1))

    settled = exec_mod.reconcile_stale_dispatches("acme")
    assert [r.outbox_id for r in settled] == [row.outbox_id]
    assert outbox.get(row.outbox_id).state is OutboxState.UNKNOWN
    events = [e.payload for e in exec_mod._CHAIN.entries("acme")]
    assert any(e.get("event") == "dispatch_unknown" for e in events), (
        "an undeterminable outcome must be visible in the audit chain"
    )


# ── Row 5: crash after the terminal state, before downstream projection ────

def test_row5_terminal_row_is_authoritative_and_reconcile_is_idempotent(
    client
) -> None:
    """Design: the terminal outbox row is the source of truth; a repeated
    sweep must not disturb it (replay-safe, visibility lag only).

    Scope note (external review 2026-08-26, RMR-CR-001): this test covers
    the HAPPY path plus sweep-idempotence only. The actual row-5 crash —
    dying after settlement, before downstream projection — is injected and
    repaired in tests/test_terminal_projection.py."""
    item_id = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200
    exec_mod = _mod()
    rows = exec_mod._outbox().rows_for_proposal("acme", r.json()["proposal_id"])
    assert len(rows) == 1 and rows[0].is_terminal
    before = rows[0].state

    for _ in range(3):
        assert exec_mod.reconcile_stale_dispatches(
            "acme", now=datetime.now(UTC) + timedelta(days=1)
        ) == []
    assert exec_mod._outbox().get(rows[0].outbox_id).state is before
