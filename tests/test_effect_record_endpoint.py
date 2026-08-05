# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A product hands its verification back, and REMORA records who said it.

The reader holds the credentials, so verification runs in the product's
process — REMORA never reaches into a customer's system of record. What
crosses back is the record. That makes the trust boundary explicit and
worth pinning:

    the chain stores an ATTESTATION by a named verifier, not an
    independent proof by REMORA.

So the endpoint refuses anything that would blur that: a record for
another tenant's proposal, a record for a proposal that does not exist, a
status outside the published five, and any attempt to submit a record
without saying who observed it. What it does NOT do is judge the verdict
— a product reporting a mismatch is reporting bad news about itself, and
an overlay that filtered those would be worse than useless.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "rec-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


def _record(**overrides) -> dict:
    payload = {
        "execution_id": "e-1",
        "tool_id": "store_artifact",
        "toolspec_hash": "d" * 64,
        "status": "EFFECT_VERIFIED",
        "reason_code": "postcondition_verified",
        "verifier_identity": "acme.reader/v1",
        "expected_sha256": "a" * 64,
        "observed_sha256": "a" * 64,
        "verified_at": "2026-08-05T12:00:00+00:00",
        "detail": "",
    }
    payload.update(overrides)
    return payload


def _make_client(monkeypatch, tmp_path, *, tenant="acme"):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "rec-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "rec-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE",
                       "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY",
                "REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
        monkeypatch.delenv(var, raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    state = {"tenant": tenant}
    monkeypatch.setattr(api_mod, "_authenticate",
                        lambda request: (state["tenant"], "reviewer"))
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
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app), state


@pytest.fixture()
def client(monkeypatch, tmp_path):
    client, _state = _make_client(monkeypatch, tmp_path)
    return client


@pytest.fixture()
def tenant_switch(monkeypatch, tmp_path):
    return _make_client(monkeypatch, tmp_path)


def _executed(client) -> str:
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    item_id = assessed["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    return str(r.json()["proposal_id"])


def _post(client, proposal_id: str, **overrides):
    return client.post(f"/v1/execution/proposals/{proposal_id}/effect",
                       json=_record(**overrides))


# ── The record lands ───────────────────────────────────────────────────────

def test_a_verification_is_recorded_and_returns_its_chain_position(
    client,
) -> None:
    proposal_id = _executed(client)
    r = _post(client, proposal_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "EFFECT_VERIFIED"
    assert body["audit"]["sequence_no"] > 0
    assert len(body["audit"]["entry_hash"]) == 64


def test_the_recorded_verdict_shows_on_the_proposal(client) -> None:
    proposal_id = _executed(client)
    _post(client, proposal_id)
    view = client.get(f"/v1/execution/proposals/{proposal_id}").json()
    assert view["current_state"] == "EFFECT_VERIFIED"
    assert view["effect"]["verifier_identity"] == "acme.reader/v1"


def test_a_mismatch_is_recorded_exactly_as_reported(client) -> None:
    """A product reporting a mismatch is reporting bad news about itself.
    An overlay that softened those would be worse than not having one."""
    proposal_id = _executed(client)
    r = _post(client, proposal_id, status="EFFECT_MISMATCH",
              reason_code="postcondition_field_mismatch",
              observed_sha256="b" * 64)
    assert r.status_code == 200, r.text
    view = client.get(f"/v1/execution/proposals/{proposal_id}").json()
    assert view["current_state"] == "EFFECT_MISMATCH"


def test_recording_appends_and_never_edits(client) -> None:
    proposal_id = _executed(client)
    first = _post(client, proposal_id, status="EFFECT_UNOBSERVABLE",
                  reason_code="postcondition_read_timeout").json()
    second = _post(client, proposal_id).json()
    assert second["audit"]["sequence_no"] > first["audit"]["sequence_no"]
    trail = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle"
    ).json()
    assert [e["event"] for e in trail["events"]].count("effect_verified") == 2


def test_the_chain_stays_verifiable_after_recording(client) -> None:
    proposal_id = _executed(client)
    _post(client, proposal_id)
    audit = client.get("/v1/execution/audit/verify").json()
    assert audit["valid"], audit


# ── The refusals ───────────────────────────────────────────────────────────

def test_an_unknown_proposal_is_refused(client) -> None:
    r = _post(client, "no-such-proposal")
    assert r.status_code == 404


def test_another_tenants_proposal_is_invisible(tenant_switch) -> None:
    """Tenant-scoped by construction: not a redacted 200 that leaks the
    proposal's existence, a 404."""
    client, state = tenant_switch
    proposal_id = _executed(client)
    state["tenant"] = "other-corp"
    r = _post(client, proposal_id)
    assert r.status_code == 404


def test_a_status_outside_the_published_five_is_refused(client) -> None:
    proposal_id = _executed(client)
    r = _post(client, proposal_id, status="EFFECT_PROBABLY_FINE")
    assert r.status_code == 422, r.text


def test_a_record_without_a_verifier_identity_is_refused(client) -> None:
    """The chain stores an attestation. An attestation nobody signed is
    not evidence — an auditor could not tell who claimed to have looked."""
    proposal_id = _executed(client)
    r = _post(client, proposal_id, verifier_identity="")
    assert r.status_code == 422, r.text
