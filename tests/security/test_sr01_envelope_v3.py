"""SR-01 / SEC-01: the DecisionEnvelope audit hash and HMAC must bind every
recorded audit field.

Pre-fix behaviour pinned by the 2026-10 security review: ``_finalize_envelope_audit``
computed ``audit.hash`` and the HMAC signature BEFORE ``tenant_id``,
``actor_identity``, ``policy_bundle_hash``, ``policy_components``,
``tool_args_hash`` and ``tool_args_binding`` were written, and
``_assess_semantic_overlay`` mutated the block after sealing. A stored envelope
could have its actor, tenant or argument binding rewritten and still "verify".

The v3 rule: populate every audit field first, seal once, and a verifier can
recompute ``audit.hash`` from the stored envelope alone. Any post-seal write
is a pipeline bug and must raise.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # type: ignore[import-not-found]  # noqa: E402

_SIGNING_KEY = "sr01-test-signing-key"


def _load_api_module(monkeypatch: pytest.MonkeyPatch, token: str | None = "test-token"):
    # Mirrors tests/test_api_server.py::_load_api_module.
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)
    monkeypatch.delenv("REMORA_API_TOKENS", raising=False)
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    if token is None:
        monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("REMORA_API_BEARER_TOKEN", token)
    import servers.api as api

    return importlib.reload(api)


def _post_assess(client: TestClient, question: str, tenant: str) -> dict:
    resp = client.post(
        "/v1/assess",
        json={"question": question, "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": tenant,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["envelope"]


def _recompute(api, envelope: dict) -> str:
    audit = envelope["audit"]
    return api._compute_envelope_chain_hash(
        previous_hash=audit.get("previous_hash"),
        envelope_payload=envelope,
    )


def _hmac_of(audit_hash: str) -> str:
    return hmac.new(
        _SIGNING_KEY.encode("utf-8"), audit_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def test_stored_envelope_hash_recomputes_from_recorded_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-01 core: the stored envelope alone must reproduce its audit hash."""
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", _SIGNING_KEY)
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)

    envelope = _post_assess(client, "Approve maintenance action A?", "tenant-sr01")

    assert _recompute(api, envelope) == envelope["audit"]["hash"], (
        "audit.hash does not cover the recorded audit fields: the stored "
        "envelope cannot reproduce its own hash"
    )


def test_schema_version_is_3(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)

    envelope = _post_assess(client, "Approve maintenance action B?", "tenant-sr01-v3")

    assert envelope["audit"]["schema_version"] == "3"


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_identity", "mallory"),
        ("tenant_id", "other-tenant"),
        ("tool_args_hash", "0" * 64),
        ("policy_bundle_hash", "0" * 64),
    ],
)
def test_field_mutation_breaks_hash_and_hmac(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    """The SR-01 attack: rewriting actor/tenant/policy/args on a stored
    envelope must invalidate both the recomputed hash and the HMAC."""
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", _SIGNING_KEY)
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)

    envelope = _post_assess(client, "Approve maintenance action C?", "tenant-sr01-mut")
    audit = envelope["audit"]
    assert audit["signature"], "test requires a signed envelope"

    mutated = copy.deepcopy(envelope)
    mutated["audit"][field] = value

    recomputed = _recompute(api, mutated)
    assert recomputed != audit["hash"], (
        f"mutating audit.{field} left the recomputed hash unchanged"
    )
    assert _hmac_of(recomputed) != mutated["audit"]["signature"], (
        f"mutating audit.{field} left the HMAC signature valid"
    )


def test_chain_linkage_still_holds_under_v3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: v3 changes the preimage, not the chain structure."""
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)

    first = _post_assess(client, "Action D1?", "tenant-sr01-chain")
    second = _post_assess(client, "Action D2?", "tenant-sr01-chain")

    assert first["audit"]["previous_hash"] is None
    assert first["audit"]["genesis"] is True
    assert second["audit"]["previous_hash"] == first["audit"]["hash"]
    assert second["audit"]["genesis"] is False


def test_audit_block_rejects_post_seal_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """After sealing, the audit block is frozen: the semantic overlay (or any
    later pipeline stage) writing to it is a bug and must raise, never pass
    silently. The sealed block must stay JSON-serialisable for persistence."""
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)

    captured: dict[str, dict] = {}
    store = api._CONTROL_PLANE_STORE
    original_save = store.save_decision

    def _spy(*, request_id, tenant_id, envelope, audit_record):
        captured["envelope"] = envelope
        return original_save(
            request_id=request_id,
            tenant_id=tenant_id,
            envelope=envelope,
            audit_record=audit_record,
        )

    monkeypatch.setattr(store, "save_decision", _spy)

    _post_assess(client, "Approve maintenance action E?", "tenant-sr01-seal")
    envelope = captured["envelope"]
    audit = envelope["audit"]

    with pytest.raises(RuntimeError, match="sealed"):
        audit["actor_identity"] = "mallory"

    # Persistence and verification paths must keep working on a sealed block.
    json.dumps(envelope)
    copied = copy.deepcopy(envelope)
    assert copied["audit"]["hash"] == audit["hash"]


def test_verify_stored_envelope_recompute_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-2: verify_stored_envelope recomputes v3 and checks the HMAC."""
    from remora.governance.envelope_verify import verify_stored_envelope

    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", _SIGNING_KEY)
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)

    envelope = _post_assess(client, "Approve maintenance action F?", "tenant-sr01-verify")
    result = verify_stored_envelope(envelope, signing_key=_SIGNING_KEY)

    assert result.mode == "recompute"
    assert result.schema_version == "3"
    assert result.hash_ok is True
    assert result.signature_ok is True


def test_verify_stored_envelope_detects_post_store_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from remora.governance.envelope_verify import verify_stored_envelope

    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", _SIGNING_KEY)
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)

    envelope = _post_assess(client, "Approve maintenance action G?", "tenant-sr01-verify2")
    mutated = copy.deepcopy(envelope)
    mutated["audit"]["actor_identity"] = "mallory"

    # Field rewrite alone: the recomputed hash exposes it. The stored
    # signature still matches the stored (unmodified) hash, so detection runs
    # through hash_ok here.
    result = verify_stored_envelope(mutated, signing_key=_SIGNING_KEY)
    assert result.hash_ok is False

    # Full forgery attempt: rewrite the field AND recompute the hash. The
    # hash then matches, but the HMAC cannot be reproduced without the key.
    from remora.governance.envelope_verify import recompute_stored_hash

    mutated["audit"]["hash"] = recompute_stored_hash(mutated)
    forged = verify_stored_envelope(mutated, signing_key=_SIGNING_KEY)
    assert forged.hash_ok is True
    assert forged.signature_ok is False


def test_v2_records_verify_links_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """v2 records predate field binding; recompute must refuse, not guess."""
    from remora.governance.envelope_verify import verify_stored_envelope

    v2_record = {"audit": {"schema_version": "2", "hash": "ab" * 32, "previous_hash": None}}
    result = verify_stored_envelope(v2_record, signing_key=_SIGNING_KEY)

    assert result.mode == "links"
    assert result.hash_ok is None
    assert result.signature_ok is None


def test_chain_verify_endpoint_recompute_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """mode=recompute catches a stored envelope whose actor was rewritten,
    while the default links mode still reports the chain as valid."""
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", _SIGNING_KEY)
    api = _load_api_module(monkeypatch)
    client = TestClient(api.app)
    headers = {
        "Authorization": "Bearer test-token",
        "X-Remora-Tenant": "tenant-sr01-endpoint",
    }

    first = _post_assess(client, "Approve maintenance action H1?", "tenant-sr01-endpoint")
    _post_assess(client, "Approve maintenance action H2?", "tenant-sr01-endpoint")
    victim_request_id = first["request"]["request_id"]

    ok_resp = client.get(
        "/v1/audit/chain/verify", params={"mode": "recompute"}, headers=headers
    )
    assert ok_resp.status_code == 200, ok_resp.text
    body = ok_resp.json()
    assert body["verification_scope"] == "recompute"
    assert body["recompute"]["recomputed"] == 2
    assert body["recompute"]["hash_failures"] == []
    assert body["signature_status"] == "CHECKED"
    assert body["chain_valid"] is True

    # Tamper with the stored envelope as a control-plane writer would.
    store = api._CONTROL_PLANE_STORE
    original_get = store.get_envelope

    def _tampered(*, request_id, tenant_id):
        envelope = original_get(request_id=request_id, tenant_id=tenant_id)
        if request_id == victim_request_id and isinstance(envelope, dict):
            envelope = copy.deepcopy(envelope)
            envelope["audit"]["actor_identity"] = "mallory"
        return envelope

    monkeypatch.setattr(store, "get_envelope", _tampered)

    links_resp = client.get("/v1/audit/chain/verify", headers=headers)
    assert links_resp.json()["chain_valid"] is True, (
        "links mode must stay blind to field rewrites (documented scope)"
    )

    bad_resp = client.get(
        "/v1/audit/chain/verify", params={"mode": "recompute"}, headers=headers
    )
    bad = bad_resp.json()
    assert bad["chain_valid"] is False
    assert victim_request_id in bad["recompute"]["hash_failures"]

    bad_mode = client.get(
        "/v1/audit/chain/verify", params={"mode": "deep"}, headers=headers
    )
    assert bad_mode.status_code == 422


def test_overlay_write_between_populate_and_seal_is_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structural pin for the handler order populate -> overlay -> seal: a
    field written by the semantic overlay must land inside the hash preimage."""
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", _SIGNING_KEY)
    api = _load_api_module(monkeypatch)

    envelope: dict = {"request": {"proposed_action": "x", "action_type": "y"}}
    api._populate_envelope_audit_fields(
        envelope_payload=envelope,
        tenant_id="tenant-sr01-structural",
        actor_identity="tester",
        tool_call=None,
    )
    # Simulated overlay write (the real overlay needs a configured bundle).
    envelope["audit"]["tool_contract_bundle_hash"] = "ab" * 32
    api._seal_envelope_audit(envelope_payload=envelope, tenant_id="tenant-sr01-structural")

    assert _recompute(api, envelope) == envelope["audit"]["hash"]

    envelope_no_overlay: dict = {"request": {"proposed_action": "x", "action_type": "y"}}
    api._populate_envelope_audit_fields(
        envelope_payload=envelope_no_overlay,
        tenant_id="tenant-sr01-structural-2",
        actor_identity="tester",
        tool_call=None,
    )
    api._seal_envelope_audit(
        envelope_payload=envelope_no_overlay, tenant_id="tenant-sr01-structural-2"
    )
    assert envelope_no_overlay["audit"]["hash"] != envelope["audit"]["hash"], (
        "the overlay-written bundle hash did not move the audit hash"
    )
