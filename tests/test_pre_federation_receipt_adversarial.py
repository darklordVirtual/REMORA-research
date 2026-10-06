# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation adversarial probes for effect receipt integrity.

Test-only.  These probes attack the join between dispatch lineage, verifier
identity, terminal effect state and the metadata later exported as evidence.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")

from remora.governance.effect_receipt import ReceiptRefused, verify_receipt
from remora.governance.effect_verification import EffectStatus
from remora.governance.tenant_chain import TenantAuditChain

CALL_HASH = "a" * 64
JTI = "jti-1"
DIGEST = "d" * 64


def _events():
    attempted = datetime.now(UTC) - timedelta(seconds=5)
    return [{
        "event": "execution_result",
        "timestamp": attempted.isoformat(),
        "payload": {
            "event": "execution_result",
            "proposal_id": "prop-1",
            "tool_call_hash": CALL_HASH,
            "grant_jti": JTI,
            "tool_executed": True,
            "state_unknown": False,
        },
    }]


def _receipt(**overrides):
    kwargs = dict(
        events=_events(),
        proposal_id="prop-1",
        claimed_status=EffectStatus.VERIFIED,
        tool_call_hash=CALL_HASH,
        grant_jti=JTI,
        expected_sha256=DIGEST,
        observed_sha256=DIGEST,
        verified_at=datetime.now(UTC).isoformat(),
        verifier_identity="reader-1",
        trusted_verifiers=("reader-1",),
    )
    kwargs.update(overrides)
    return verify_receipt(**kwargs)


def test_empty_trusted_verifier_set_is_fail_closed():
    """An empty trust store means nobody is trusted, not everybody is trusted.

    The execution API separately binds verifier identity to the authenticated
    principal.  This probe targets the reusable core primitive and its own
    documented invariant that a settled attestation comes from a trusted
    verifier.
    """
    with pytest.raises(ReceiptRefused) as exc:
        _receipt(trusted_verifiers=(), verifier_identity="arbitrary-reader")
    assert exc.value.reason == "untrusted_verifier"


def test_terminal_unsupported_requires_dispatch_binding():
    """UNSUPPORTED is terminal, so it must not be able to occupy the one-shot
    effect slot without naming the dispatch it is closing.
    """
    with pytest.raises(ReceiptRefused) as exc:
        _receipt(
            claimed_status=EffectStatus.UNSUPPORTED,
            tool_call_hash="",
            grant_jti="",
            expected_sha256="",
            observed_sha256="",
        )
    assert exc.value.reason == "binding_incomplete"


@pytest.fixture()
def api_client(monkeypatch, tmp_path):
    """Minimal effect-record endpoint client, equivalent to the repository fixture."""
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "probe-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "probe-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_BINDINGS", "employee-1=acme.reader/v1")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY",
                "REMORA_TOOLSPEC_TRUSTED_IDENTITIES", "REMORA_CHAIN_DB",
                "REMORA_PG_DSN"):
        monkeypatch.delenv(var, raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from fastapi.testclient import TestClient

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
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
    return TestClient(api_mod.app)


def _execute(api_client):
    call = {
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "probe-1", "content": {"n": 1}},
        "target_environment": "prod",
        "schema_valid": True,
    }
    assessed = api_client.post("/v1/execution/assess", json=call).json()
    item = assessed["review_item_id"]
    assert api_client.post("/v1/execution/approve", json={"item_id": item}).status_code == 200
    executed = api_client.post(
        "/v1/execution/execute", json={"item_id": item, "tool_call": call})
    assert executed.status_code == 200, executed.text
    return str(executed.json()["proposal_id"])


def _binding(api_client, proposal_id):
    """The binding a legitimate verifier would read from the chain.

    ``toolspec_hash`` is the assessed spec identity (empty when no signed
    bundle is configured). An earlier revision of this probe sent ``"d" * 64``
    as its baseline, which is itself a forged spec claim and is refused now
    that the recorder checks it.
    """
    trail = api_client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle").json()
    assessed = next(e["payload"] for e in trail["events"]
                    if e.get("event") == "assessed")
    for event in reversed(trail["events"]):
        if event.get("event") == "execution_result":
            payload = event.get("payload") or event
            return {
                "tool_call_hash": payload.get("tool_call_hash", ""),
                "grant_jti": payload.get("grant_jti", ""),
                "toolspec_hash": assessed.get("toolspec_hash", ""),
            }
    raise AssertionError("no execution_result")


def _effect_body(api_client, proposal_id, **overrides):
    body = {
        **_binding(api_client, proposal_id),
        "execution_id": "e-1",
        "tool_id": "store_artifact",
        "status": "EFFECT_VERIFIED",
        "reason_code": "postcondition_verified",
        "verifier_identity": "acme.reader/v1",
        "expected_sha256": "a" * 64,
        "observed_sha256": "a" * 64,
        "verified_at": datetime.now(UTC).isoformat(),
        "detail": "",
    }
    body.update(overrides)
    return body


def test_terminal_unsupported_cannot_poison_the_dispatch_slot(api_client):
    """A terminal 'unsupported' claim must not block a later real observation.

    Today EffectStatus.UNSUPPORTED is terminal, while verify_receipt does not
    require the exact dispatch binding for it.  If accepted, append_once uses
    the dispatch slot and a later VERIFIED receipt can be rejected as replay.
    """
    proposal_id = _execute(api_client)
    unsupported = _effect_body(
        api_client, proposal_id,
        status="EFFECT_UNSUPPORTED",
        reason_code="postcondition_not_declared",
        tool_call_hash="",
        grant_jti="",
        expected_sha256="",
        observed_sha256="",
    )
    first = api_client.post(
        f"/v1/execution/proposals/{proposal_id}/effect", json=unsupported)

    # Either the unbound terminal report is refused immediately, or — if a
    # deployment elects to record UNSUPPORTED — it must remain non-settling so
    # a later real observation can close the dispatch.  The unsafe combination
    # is 200 here followed by replay refusal below.
    if first.status_code not in {409, 422}:
        assert first.status_code == 200, first.text

    verified = api_client.post(
        f"/v1/execution/proposals/{proposal_id}/effect",
        json=_effect_body(api_client, proposal_id))
    assert verified.status_code == 200, (
        "an unbound EFFECT_UNSUPPORTED occupied the terminal dispatch slot "
        f"and poisoned later verification: first={first.text}; later={verified.text}"
    )


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("tool_id", "different_tool"),
        ("toolspec_hash", "f" * 64),
    ],
)
def test_receipt_cannot_store_forged_dispatch_metadata(api_client, field, forged):
    """Evidence metadata that names the governed action/spec must be derived
    from or checked against dispatch lineage, not copied from the request.
    """
    proposal_id = _execute(api_client)
    body = _effect_body(api_client, proposal_id, **{field: forged})
    response = api_client.post(
        f"/v1/execution/proposals/{proposal_id}/effect", json=body)
    assert response.status_code == 409, response.text


def test_verified_reason_code_must_agree_with_status(api_client):
    """A VERIFIED record carrying a mismatch reason is internally contradictory
    evidence and should not be admitted to the immutable audit trail.
    """
    proposal_id = _execute(api_client)
    response = api_client.post(
        f"/v1/execution/proposals/{proposal_id}/effect",
        json=_effect_body(
            api_client, proposal_id,
            status="EFFECT_VERIFIED",
            reason_code="postcondition_field_mismatch",
        ),
    )
    assert response.status_code in {409, 422}, response.text
