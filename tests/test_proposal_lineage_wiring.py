# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Probing is visible through the API, and the caller cannot hide it.

The unit tests pin the derivation. These pin the two things that only
exist once it is wired into a live assessment:

- **the caller has no say.** There is no request field that suppresses,
  sets, or redirects lineage, and sending one changes nothing. A control
  a caller can switch off protects only the callers who would not have
  attacked it;
- **it is shadow only.** Eligibility appears in the response and the audit
  record while the decision stays exactly what the engine returned.
  Routing on a signal whose false-positive rate nobody has measured is
  the mistake this layer exists to prevent.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

# A read the engine cannot accept on client-asserted trust alone: it has
# no evidence pipeline behind it, so it abstains — which is exactly the
# decision this feature is about.
ABSTAINING_CALL = {
    "tool_name": "read_telemetry",
    "arguments": {"sensor": "P-1"},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "lineage-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "lineage-lease-key")
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

    state = {"principal": "agent-1"}
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: state["principal"])
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


def _assess(client, **overrides):
    payload = dict(ABSTAINING_CALL)
    payload.update(overrides)
    r = client.post("/v1/execution/assess", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ── The abstaining call really does abstain ────────────────────────────────

def test_the_probe_scenario_actually_abstains(client) -> None:
    """If this stopped abstaining, every test below would pass for the
    wrong reason."""
    api, _state = client
    assert _assess(api)["decision"] == "abstain"


# ── Lineage accumulates ────────────────────────────────────────────────────

def test_a_first_proposal_reports_no_ancestor(client) -> None:
    api, _state = client
    body = _assess(api)
    assert body["lineage"]["superseded_proposal_id"] == ""
    assert body["lineage"]["probe_sequence_no"] == 1
    assert body["lineage"]["escalation_eligible"] is False


def test_a_retry_names_the_proposal_it_supersedes(client) -> None:
    api, _state = client
    first = _assess(api)
    second = _assess(api, arguments={"sensor": "P-1", "detail": "full"})
    assert second["lineage"]["superseded_proposal_id"] == first["proposal_id"]
    assert second["lineage"]["probe_sequence_no"] == 2


def test_a_tweaked_payload_does_not_reset_the_count(client) -> None:
    """The whole point: changing an argument changes the call hash, and a
    prober relies on that making each attempt look new."""
    api, _state = client
    for i in range(3):
        _assess(api, arguments={"sensor": "P-1", "attempt": i})
    body = _assess(api, arguments={"sensor": "P-1", "attempt": 99})
    assert body["lineage"]["probe_sequence_no"] == 4
    assert body["lineage"]["escalation_eligible"] is True


# ── Shadow only ────────────────────────────────────────────────────────────

def test_eligibility_does_not_change_the_decision(client) -> None:
    """The load-bearing restraint. Eligible must not mean escalated until
    the false-positive rate has been measured."""
    api, _state = client
    for _ in range(4):
        body = _assess(api)
    assert body["lineage"]["escalation_eligible"] is True
    assert body["lineage"]["shadow_only"] is True
    assert body["decision"] == "abstain", (
        "lineage must not route: it changed the decision"
    )
    assert "review_item_id" not in body


# ── The caller has no say ──────────────────────────────────────────────────

def test_a_client_supplied_lineage_field_is_ignored(client) -> None:
    """A prober would happily assert 'this supersedes nothing'."""
    api, _state = client
    first = _assess(api)
    second = _assess(
        api, superseded_proposal_id="", lineage={"probe_sequence_no": 1},
        supersedes_proposal_id="something-else",
    )
    assert second["lineage"]["superseded_proposal_id"] == first["proposal_id"]
    assert second["lineage"]["probe_sequence_no"] == 2


def test_switching_identity_does_not_inherit_someone_elses_lineage(
    client,
) -> None:
    """Lineage follows the authenticated principal, so it can neither be
    dodged by nor pinned on another actor."""
    api, state = client
    _assess(api)
    _assess(api)
    state["principal"] = "agent-2"
    body = _assess(api)
    assert body["lineage"]["probe_sequence_no"] == 1
    assert body["lineage"]["superseded_proposal_id"] == ""


def test_a_different_environment_is_a_different_run(client) -> None:
    api, _state = client
    _assess(api)
    body = _assess(api, target_environment="staging")
    assert body["lineage"]["probe_sequence_no"] == 1


# ── The audit trail carries it ─────────────────────────────────────────────

def test_the_chain_records_the_lineage_and_stays_verifiable(client) -> None:
    api, _state = client
    first = _assess(api)
    _assess(api)
    import servers.execution_api as exec_mod

    payload = exec_mod._CHAIN.entries("acme")[-1].payload
    assert payload["superseded_proposal_id"] == first["proposal_id"]
    assert payload["lineage"]["shadow_only"] is True
    # Recorded so a later derivation can reconstruct the key.
    assert payload["target_environment"] == "prod"
    assert "lineage_resource" in payload
    valid, problems = exec_mod._CHAIN.verify("acme")
    assert valid, problems


def test_the_record_states_how_precise_the_key_was(client) -> None:
    """Without a signed ToolSpec nothing declares the target, so the key
    is coarse — and the record must say so rather than let a reader assume
    a precise match."""
    api, _state = client
    body = _assess(api)
    assert body["lineage"]["lineage_key_basis"] == "tool_only"
