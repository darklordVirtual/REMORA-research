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
