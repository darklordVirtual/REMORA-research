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

from datetime import UTC, datetime, timedelta

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
        # Fresh, not fixed. A hardcoded past timestamp dated the observation
        # weeks before the dispatch it claims to describe, and the receipt is
        # now refused for exactly that (observation_precedes_dispatch). The
        # fixture was asserting a receipt no deployment should accept.
        "verified_at": datetime.now(UTC).isoformat(),
        "detail": "",
    }
    payload.update(overrides)
    return payload


def _make_client(monkeypatch, tmp_path, *, tenant="acme"):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "rec-pdp-key")
    # The deployment declares which authenticated principal may submit
    # receipts under which verifier identity. Without it the identity must
    # equal the principal, which is fail-closed: before this binding existed
    # the verifier name arrived in the request body, so anyone authorised to
    # record receipts could type a permitted name.
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_BINDINGS",
                       "employee-1=acme.reader/v1")
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


def _dispatch_binding(client, proposal_id: str) -> dict:
    """The dispatch identity a settled verdict must name.

    Read from the proposal's own lifecycle, as the SDK does. The server still
    compares these against its chain, so echoing them proves nothing by itself
    -- what it prevents is a receipt being applied to whichever dispatch
    happens to be latest.
    """
    trail = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle").json()
    out = {"tool_call_hash": "", "grant_jti": ""}
    for event in trail.get("events") or []:
        if event.get("event") != "execution_result":
            continue
        payload = event.get("payload") or event
        out["tool_call_hash"] = payload.get("tool_call_hash") or out["tool_call_hash"]
        out["grant_jti"] = payload.get("grant_jti") or out["grant_jti"]
    return out


def _post(client, proposal_id: str, **overrides):
    body = {**_dispatch_binding(client, proposal_id), **_record(**overrides)}
    return client.post(f"/v1/execution/proposals/{proposal_id}/effect",
                       json=body)


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


# ── RMR-002: a receipt must be about a dispatch that happened ───────────────

def _assessed_only(client) -> str:
    """A proposal that reached review and was never approved or executed."""
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    assert assessed["review_item_id"], "expected this call to need review"
    return str(assessed["proposal_id"])


def test_a_never_executed_proposal_cannot_be_recorded_verified(client) -> None:
    """The reported reproduction, end to end through the recorder API.

    Assess a write, do not approve it, do not execute it, then POST
    EFFECT_VERIFIED. Previously 200, and the lifecycle then reported
    EFFECT_VERIFIED for a proposal whose dispatch is null.
    """
    proposal_id = _assessed_only(client)
    response = _post(client, proposal_id)
    assert response.status_code == 409, response.text
    assert "no_dispatch" in response.json()["detail"]

    view = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle").json()
    assert view["current_state"] != "EFFECT_VERIFIED"


def test_a_receipt_for_another_proposals_call_is_refused(client) -> None:
    """Right format, wrong subject."""
    executed = _executed(client)
    response = _post(client, executed, tool_call_hash="f" * 64)
    assert response.status_code == 409
    assert "tool_call_hash_mismatch" in response.json()["detail"]


def test_a_stale_observation_is_refused(client) -> None:
    """An observation dated before the dispatch cannot evidence it."""
    proposal_id = _executed(client)
    response = _post(client, proposal_id,
                     verified_at="2020-01-01T00:00:00+00:00")
    assert response.status_code == 409
    assert "observation_precedes_dispatch" in response.json()["detail"]


def test_verified_without_a_recorded_observation_is_refused(client) -> None:
    """A verdict that records neither side of its own comparison.

    Not re-running the comparison -- REMORA holds the digests, not the maps or
    the rules. What it refuses is a VERIFIED an auditor could never re-check.
    """
    proposal_id = _executed(client)
    response = _post(client, proposal_id,
                     status="EFFECT_VERIFIED",
                     expected_sha256="a" * 64, observed_sha256="")
    assert response.status_code == 409
    assert "settled_without_observation" in response.json()["detail"]


def test_a_settled_verdict_cannot_be_re_verified(client) -> None:
    proposal_id = _executed(client)
    assert _post(client, proposal_id).status_code == 200
    second = _post(client, proposal_id)
    assert second.status_code == 409
    assert "receipt_replayed" in second.json()["detail"]


def test_an_unresolved_verdict_can_still_be_settled(client) -> None:
    """UNOBSERVABLE then VERIFIED: how an unknown is closed honestly."""
    proposal_id = _executed(client)
    assert _post(client, proposal_id, status="EFFECT_UNOBSERVABLE",
                 reason_code="postcondition_read_timeout").status_code == 200
    settled = _post(client, proposal_id)
    assert settled.status_code == 200, settled.text
    assert settled.json()["status"] == "EFFECT_VERIFIED"


def test_a_verifier_identity_the_principal_may_not_claim_is_refused(
        client, monkeypatch) -> None:
    """The name is bound to the authenticated principal, not merely allowlisted.

    An allowlist of NAMES was not enough: the name arrives in the request body,
    so a submitter authorised to record receipts could type a permitted one.
    """
    proposal_id = _executed(client)
    response = _post(client, proposal_id, verifier_identity="attacker/v1")
    assert response.status_code == 403, response.text
    assert "verifier_not_bound" in response.json()["detail"]


def test_the_response_reports_both_claimed_and_derived_status(client) -> None:
    """An operator needs to see that the two agreed, not just the outcome."""
    proposal_id = _executed(client)
    body = _post(client, proposal_id).json()
    assert body["status"] == "EFFECT_VERIFIED"
    assert body["claimed_status"] == "EFFECT_VERIFIED"
    assert body["dispatch_id"], "the receipt is bound to a dispatch identity"


# ── The forgeable receipt the reviewer constructed ─────────────────────────

def test_the_reviewers_forged_receipt_is_refused(client) -> None:
    """The exact request from the second review, against a REAL dispatch.

    Every field that would have bound it is empty or unchecked:

        tool_call_hash: ""      -> skipped the comparison
        grant_jti:      ""      -> skipped the comparison
        verified_at:    ""      -> replaced by the server clock
        expected/observed: "a"/"b" -> not validated as SHA-256

    It was accepted, because none of the emptiness was treated as missing
    evidence. It is now refused before any of the digest checks are reached.
    """
    proposal_id = _executed(client)
    forged = {
        "execution_id": "e-forged",
        "tool_id": "store_artifact",
        "status": "EFFECT_VERIFIED",
        "reason_code": "postcondition_verified",
        "verifier_identity": "acme.reader/v1",
        "tool_call_hash": "",
        "grant_jti": "",
        "verified_at": "",
        "expected_sha256": "",
        "observed_sha256": "",
    }
    response = client.post(
        f"/v1/execution/proposals/{proposal_id}/effect", json=forged)
    assert response.status_code == 409, response.text
    assert "binding_incomplete" in response.json()["detail"]

    view = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle").json()
    assert view["current_state"] != "EFFECT_VERIFIED"


def test_a_non_sha256_digest_is_refused_on_the_wire(client) -> None:
    """"a" and "b" are not digests. The model says so before the handler runs."""
    proposal_id = _executed(client)
    response = client.post(
        f"/v1/execution/proposals/{proposal_id}/effect",
        json={**_dispatch_binding(client, proposal_id),
              **_record(expected_sha256="a", observed_sha256="b")})
    assert response.status_code == 422, response.text


def test_a_settled_verdict_without_an_observation_time_is_refused(
        client) -> None:
    """The server's clock must not stand in for when the verifier looked."""
    proposal_id = _executed(client)
    response = _post(client, proposal_id, verified_at="")
    assert response.status_code == 409
    assert "observation_time_missing" in response.json()["detail"]


def test_an_observation_dated_far_ahead_is_refused(client) -> None:
    """Clock drift is bounded; an hour into the future is not drift."""
    proposal_id = _executed(client)
    ahead = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = _post(client, proposal_id, verified_at=ahead)
    assert response.status_code == 409
    assert "observation_in_the_future" in response.json()["detail"]


def test_a_mismatch_also_needs_an_observation(client) -> None:
    """Equal burden. A MISMATCH takes the terminal slot too."""
    proposal_id = _executed(client)
    response = _post(client, proposal_id, status="EFFECT_MISMATCH",
                     reason_code="postcondition_mismatch",
                     expected_sha256="a" * 64, observed_sha256="")
    assert response.status_code == 409
    assert "settled_without_observation" in response.json()["detail"]


def test_the_provenance_is_stored_not_merely_accepted(client) -> None:
    """Received-but-discarded fields suggest a binding that is not there."""
    proposal_id = _executed(client)
    assert _post(client, proposal_id,
                 observed_state_hash="s" * 64,
                 verifier_version="reader-2.1.0").status_code == 200

    trail = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle").json()
    recorded = [e for e in trail["events"] if e["event"] == "effect_verified"]
    assert recorded, "the receipt should be in the trail"
    payload = recorded[-1].get("payload") or recorded[-1]
    assert payload["observed_state_hash"] == "s" * 64
    assert payload["verifier_version"] == "reader-2.1.0"
    assert payload["dispatch_id"], "the dispatch it attests to"
    assert payload["tool_call_hash"], "the call it attests to"
    assert payload["submitted_by"] == "employee-1", (
        "who submitted, kept separate from who observed")
