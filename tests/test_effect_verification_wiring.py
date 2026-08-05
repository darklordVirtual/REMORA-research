# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A verification reaches the audit chain and the evidence export.

Handoff gate §2.6: an effect verification that only exists in memory
proves nothing to an auditor. It has to become a chain entry, be
projected onto the proposal's state, and travel in the evidence bundle
with the same hashed-manifest treatment as everything else.

Two invariants get pinned here that are easy to erode later:

- verification APPENDS; it never edits the execution record it verifies.
  A verifier that can rewrite what it verifies is not evidence;
- ``EFFECT_UNSUPPORTED`` does NOT move the proposal to a verified state.
  A tool that declares no postcondition was never observed, and
  "we did not look" must never be recorded as "we checked".
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.effect_verification import (  # noqa: E402
    EffectStatus,
    EffectVerification,
)
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "effect-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "effect-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "effect-lease-key")
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
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app)


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


def _executed(client) -> str:
    """Run one proposal all the way through dispatch; return its id."""
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    item_id = assessed["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    return str(r.json()["proposal_id"])


def _verification(proposal_id: str, status: EffectStatus,
                  reason: str) -> EffectVerification:
    return EffectVerification.build(
        proposal_id=proposal_id, execution_id="exec-1",
        tool_id="store_artifact", toolspec_hash="d" * 64,
        status=status, reason_code=reason,
        verifier_identity="test.reader/v1",
        expected={"artifact_id": "effect-1"},
        observed={"artifact_id": "effect-1"},
    )


# ── The record reaches the chain ───────────────────────────────────────────

def test_a_verification_becomes_a_chain_entry(client) -> None:
    proposal_id = _executed(client)
    before = len(_mod()._CHAIN.entries("acme"))

    _mod().record_effect_verification(
        "acme", _verification(proposal_id, EffectStatus.VERIFIED,
                              "postcondition_verified"),
    )

    entries = _mod()._CHAIN.entries("acme")
    assert len(entries) == before + 1, "verification must APPEND, not edit"
    payload = entries[-1].payload
    assert payload["event"] == "effect_verified"
    assert payload["proposal_id"] == proposal_id
    assert payload["status"] == "EFFECT_VERIFIED"
    assert len(payload["expected_sha256"]) == 64


def test_recording_a_verification_keeps_the_chain_valid(client) -> None:
    proposal_id = _executed(client)
    _mod().record_effect_verification(
        "acme", _verification(proposal_id, EffectStatus.MISMATCH,
                              "postcondition_field_mismatch"),
    )
    valid, problems = _mod()._CHAIN.verify("acme")
    assert valid, problems


# ── The proposal's state follows the verification ──────────────────────────

@pytest.mark.parametrize("status,reason,expected_state", [
    (EffectStatus.VERIFIED, "postcondition_verified", "EFFECT_VERIFIED"),
    (EffectStatus.MISMATCH, "postcondition_field_mismatch", "EFFECT_MISMATCH"),
    (EffectStatus.UNOBSERVABLE, "postcondition_read_timeout", "EFFECT_UNKNOWN"),
    (EffectStatus.VERIFIER_FAILED, "postcondition_reader_error", "EFFECT_UNKNOWN"),
])
def test_the_state_reflects_the_verification(client, status, reason,
                                             expected_state) -> None:
    proposal_id = _executed(client)
    _mod().record_effect_verification("acme",
                                      _verification(proposal_id, status, reason))
    body = client.get(f"/v1/execution/proposals/{proposal_id}").json()
    assert body["current_state"] == expected_state


def test_unsupported_does_not_claim_the_effect_was_verified(client) -> None:
    """A tool with no postcondition contract was never observed. Recording
    that as EFFECT_VERIFIED would be the overclaim this layer prevents."""
    proposal_id = _executed(client)
    _mod().record_effect_verification(
        "acme", _verification(proposal_id, EffectStatus.UNSUPPORTED,
                              "postcondition_not_declared"),
    )
    body = client.get(f"/v1/execution/proposals/{proposal_id}").json()
    assert body["current_state"] != "EFFECT_VERIFIED"
    assert body["effect"]["status"] == "EFFECT_UNSUPPORTED"


def test_a_later_observation_supersedes_an_unknown(client) -> None:
    """EFFECT_UNKNOWN resolves forward: a new record, never a rewrite."""
    proposal_id = _executed(client)
    _mod().record_effect_verification(
        "acme", _verification(proposal_id, EffectStatus.UNOBSERVABLE,
                              "postcondition_read_timeout"),
    )
    _mod().record_effect_verification(
        "acme", _verification(proposal_id, EffectStatus.VERIFIED,
                              "postcondition_verified"),
    )
    body = client.get(f"/v1/execution/proposals/{proposal_id}").json()
    assert body["current_state"] == "EFFECT_VERIFIED"
    trail = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle"
    ).json()
    events = [e["event"] for e in trail["events"]]
    assert events.count("effect_verified") == 2, (
        "the earlier uncertainty must survive in the trail"
    )


# ── Evidence export ────────────────────────────────────────────────────────

def test_evidence_carries_the_verification_and_hashes_it(client) -> None:
    proposal_id = _executed(client)
    _mod().record_effect_verification(
        "acme", _verification(proposal_id, EffectStatus.VERIFIED,
                              "postcondition_verified"),
    )
    bundle = client.get(
        f"/v1/execution/proposals/{proposal_id}/evidence"
    ).json()
    assert bundle["effect_verification"]["status"] == "EFFECT_VERIFIED"
    assert bundle["effect_verification"]["history"], "the trail must travel too"
    assert "effect_verification" in bundle["manifest"]["section_sha256"]


def test_evidence_without_a_verification_says_so_rather_than_omitting(
    client,
) -> None:
    """Absence of verification must be visible, not inferred from a
    missing key: a reader who does not find the section cannot tell
    "not verified" from "this export predates the feature"."""
    proposal_id = _executed(client)
    bundle = client.get(
        f"/v1/execution/proposals/{proposal_id}/evidence"
    ).json()
    assert bundle["effect_verification"]["status"] is None
    assert bundle["effect_verification"]["history"] == []
