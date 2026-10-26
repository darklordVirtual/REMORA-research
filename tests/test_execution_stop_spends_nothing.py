# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A stop refuses an approved item and an ACCEPT token before either is spent.

The stop switch (SDD unified capability execution v1.1, P0 item 7) promises
that a governed dispatch refuses "before anything is spent". The dispatcher
kept that promise for a presented lease (``tests/test_execution_stop.py``).
``/v1/execution/execute`` and ``/v1/execution/execute-accepted`` did not: the
OT pilot's fault-injection run on 2026-10-26 found that an approved item
executed while stopped was consumed and recorded as REFUSED, so after
``/resume`` the same approval answered 409 and the work had to be proposed
and approved again. The routes now read the flag before they touch the
approval or the token: 409 ``execution_stopped``, 503
``execution_stop_unverifiable``, and the approval or token still runs after
the resume.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.review_queue import ItemStatus  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from tests.test_execute_accepted import READ_CALL, _mint_token  # noqa: E402

WRITE_CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "stop-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "stop-spends-nothing-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    # The stop flag lives in durable authority state; without it there is no stop.
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    for name in ("REMORA_SEMANTIC_BUNDLE_MODULE", "REMORA_PG_DSN", "REMORA_STATE_ENDPOINT",
                 "REMORA_OUTBOX_STALE_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    monkeypatch.setattr(exec_mod, "_STOP_EPOCHS", None)
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    yield TestClient(api_mod.app)
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()


def _exec_mod():
    import servers.execution_api as exec_mod

    return exec_mod


def _approved_item(client) -> str:
    r = client.post("/v1/execution/assess", json=WRITE_CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert item_id
    assert client.post("/v1/execution/approve", json={"item_id": item_id}).status_code == 200
    return item_id


def _item_status(item_id: str) -> ItemStatus:
    with _exec_mod().db_transaction_state("acme") as q:
        return q.item(item_id).status


def _set_stop(client, stopped: bool) -> None:
    r = client.post(f"/v1/execution/{'stop' if stopped else 'resume'}", json={"reason": "test"})
    assert r.status_code == 200, r.text


def _execute(client, item_id: str):
    return client.post("/v1/execution/execute", json={"item_id": item_id, "tool_call": WRITE_CALL})


def test_a_stopped_execute_leaves_the_approval_unspent_and_runs_after_resume(client):
    item_id = _approved_item(client)
    _set_stop(client, True)

    refused = _execute(client, item_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "execution_stopped"
    assert _item_status(item_id) is ItemStatus.APPROVED
    assert _exec_mod()._outbox().pending("acme") == []

    _set_stop(client, False)
    ran = _execute(client, item_id)
    assert ran.status_code == 200, ran.text
    assert ran.json()["tool_execution"]["executed"] is True
    # Still one approval, one effect: the replay is refused as before.
    assert _execute(client, item_id).status_code == 409


def test_an_unanswerable_stop_store_refuses_execute_with_503_and_spends_nothing(
        client, monkeypatch):
    item_id = _approved_item(client)

    def down(tenant: str) -> bool:
        raise RuntimeError("authority store unreachable")

    monkeypatch.setattr(_exec_mod(), "_execution_stopped", down)
    r = _execute(client, item_id)
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "execution_stop_unverifiable"
    assert _item_status(item_id) is ItemStatus.APPROVED


def test_a_stopped_execute_accepted_leaves_the_token_unspent(client):
    token = _mint_token(client)
    _set_stop(client, True)
    refused = client.post("/v1/execution/execute-accepted",
                          json={"execution_token": token, "tool_call": READ_CALL})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "execution_stopped"

    _set_stop(client, False)
    ran = client.post("/v1/execution/execute-accepted",
                      json={"execution_token": token, "tool_call": READ_CALL})
    assert ran.status_code == 200, ran.text
    assert ran.json()["tool_execution"]["executed"] is True
