# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Authentic is not complete (quality program Q7.3).

A chain holding an authentic ``execution_authorized`` entry and nothing else
verifies clean. These tests pin the four verdicts, their precedence, and
that the evidence export reports them for a real proposal.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from remora.governance.evidence_coverage import (
    AUTHORIZED_EXECUTION,
    EXECUTED_EFFECT,
    Authenticity,
    CoverageStatus,
    EvidenceContract,
    EvidenceItem,
    EvidenceRequirement,
    assess_coverage,
    chain_event_items,
    content_digest_verifier,
)


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def _item(kind, payload=None, *, sha=True, ref=""):
    payload = payload or {}
    return EvidenceItem(kind=kind, payload=payload, ref=ref or kind,
                        sha256=_digest(payload) if sha else None)


CONTRACT = EvidenceContract("c1", "claim", (
    EvidenceRequirement("a"), EvidenceRequirement("b", {"ok": True})))


class TestVerdicts:
    def test_every_required_kind_authentic_is_complete(self):
        verdict = assess_coverage(CONTRACT, [_item("a"), _item("b", {"ok": True})])
        assert verdict.status is CoverageStatus.COMPLETE
        assert verdict.missing == ()

    def test_authentic_with_a_kind_missing_is_incomplete(self):
        verdict = assess_coverage(CONTRACT, [_item("a")])
        assert verdict.status is CoverageStatus.AUTHENTIC_BUT_INCOMPLETE
        assert verdict.missing == ("b[ok=True]",)

    def test_an_item_that_does_not_meet_the_condition_does_not_count(self):
        verdict = assess_coverage(CONTRACT, [_item("a"), _item("b", {"ok": False})])
        assert verdict.status is CoverageStatus.AUTHENTIC_BUT_INCOMPLETE

    def test_an_unverifiable_item_makes_the_set_inconclusive(self):
        verdict = assess_coverage(CONTRACT, [_item("a"), _item("b", {"ok": True}, sha=False)])
        assert verdict.status is CoverageStatus.INCONCLUSIVE
        assert verdict.unverifiable == ("b",)

    def test_one_authentic_item_satisfies_a_kind_despite_an_unverifiable_twin(self):
        verdict = assess_coverage(CONTRACT, [
            _item("a"), _item("a", sha=False, ref="a2"), _item("b", {"ok": True})])
        assert verdict.status is CoverageStatus.COMPLETE

    def test_a_tampered_item_dominates_everything(self):
        forged = EvidenceItem("a", {"x": 1}, ref="forged", sha256=_digest({"x": 2}))
        verdict = assess_coverage(CONTRACT, [forged, _item("b", {"ok": True})])
        assert verdict.status is CoverageStatus.TAMPERED
        assert verdict.tampered == ("forged",)

    def test_tampering_in_an_item_no_requirement_needs_still_dominates(self):
        forged = EvidenceItem("unrelated", {"x": 1}, sha256="0" * 64)
        verdict = assess_coverage(CONTRACT, [_item("a"), _item("b", {"ok": True}), forged])
        assert verdict.status is CoverageStatus.TAMPERED

    def test_missing_kinds_are_listed_on_every_verdict(self):
        forged = EvidenceItem("a", {"x": 1}, sha256="0" * 64)
        assert assess_coverage(CONTRACT, [forged]).missing == ("a", "b[ok=True]")

    def test_nothing_is_incomplete_not_complete(self):
        assert assess_coverage(CONTRACT, []).status is CoverageStatus.AUTHENTIC_BUT_INCOMPLETE

    def test_no_digest_is_unverifiable_not_authentic(self):
        assert content_digest_verifier(_item("a", sha=False)) is Authenticity.UNVERIFIABLE


class TestChainItems:
    EVENTS = [{"sequence_no": n, "event": kind, "payload": {"event": kind}}
              for n, kind in enumerate(["assessed", "execution_authorized", "execution_result"])]

    def test_a_clean_chain_is_authentic(self):
        assert {i.authenticity for i in chain_event_items(self.EVENTS, [])} == {
            Authenticity.AUTHENTIC}

    def test_a_broken_entry_is_tampered_and_later_ones_unverifiable(self):
        items = chain_event_items(self.EVENTS, ["hash_mismatch_at:1"])
        assert [i.authenticity for i in items] == [
            Authenticity.AUTHENTIC, Authenticity.TAMPERED, Authenticity.UNVERIFIABLE]

    def test_an_unlocated_problem_makes_every_entry_unverifiable(self):
        items = chain_event_items(self.EVENTS, ["chain_unreadable"])
        assert {i.authenticity for i in items} == {Authenticity.UNVERIFIABLE}


# ── on the evidence export ─────────────────────────────────────────────────

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.effect_verification import EffectStatus, EffectVerification  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

CALL = {"tool_name": "store_artifact",
        "arguments": {"artifact_id": "coverage-1", "content": {"n": 1}},
        "target_environment": "prod", "schema_valid": True}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "coverage-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "coverage-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY",
                "REMORA_TOOLSPEC_TRUSTED_IDENTITIES", "REMORA_REQUIRE_TASK_IDENTITY"):
        monkeypatch.delenv(var, raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
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
    item_id = client.post("/v1/execution/assess", json=CALL).json()["review_item_id"]
    assert client.post("/v1/execution/approve", json={"item_id": item_id}).status_code == 200
    response = client.post("/v1/execution/execute", json={"item_id": item_id, "tool_call": CALL})
    assert response.status_code == 200, response.text
    return str(response.json()["proposal_id"])


def _coverage(client, proposal_id):
    return client.get(f"/v1/execution/proposals/{proposal_id}/evidence").json()[
        "evidence_coverage"]


def _verify_effect(proposal_id, status):
    _mod().record_effect_verification("acme", EffectVerification.build(
        proposal_id=proposal_id, execution_id="exec-1", tool_id="store_artifact",
        toolspec_hash="d" * 64, status=status, reason_code="postcondition_verified",
        verifier_identity="test.reader/v1",
        expected={"artifact_id": "coverage-1"}, observed={"artifact_id": "coverage-1"}))


class TestTheExportReportsCoverage:
    def test_an_execution_without_an_observation_is_authentic_but_incomplete(self, client):
        coverage = _coverage(client, _executed(client))
        assert coverage[AUTHORIZED_EXECUTION.contract_id]["status"] == "COMPLETE"
        effect = coverage[EXECUTED_EFFECT.contract_id]
        assert effect["status"] == "AUTHENTIC_BUT_INCOMPLETE"
        assert effect["missing"] == ["effect_verified[status=EFFECT_VERIFIED]"]

    def test_an_observed_effect_completes_the_claim(self, client):
        proposal_id = _executed(client)
        _verify_effect(proposal_id, EffectStatus.VERIFIED)
        assert _coverage(client, proposal_id)[EXECUTED_EFFECT.contract_id]["status"] == "COMPLETE"

    def test_an_unsupported_observation_does_not_complete_it(self, client):
        proposal_id = _executed(client)
        _verify_effect(proposal_id, EffectStatus.UNSUPPORTED)
        assert _coverage(client, proposal_id)[EXECUTED_EFFECT.contract_id]["status"] == (
            "AUTHENTIC_BUT_INCOMPLETE")

    def test_a_rewritten_chain_entry_is_reported_tampered(self, client):
        proposal_id = _executed(client)
        entries = _mod()._CHAIN._entries["acme"]
        target = next(i for i, e in enumerate(entries)
                      if e.payload.get("event") == "execution_result")
        forged = dict(entries[target].payload, tool_executed=True, note="rewritten")
        entries[target] = entries[target].__class__(**{**entries[target].__dict__,
                                                      "payload": forged})
        coverage = _coverage(client, proposal_id)
        assert coverage[AUTHORIZED_EXECUTION.contract_id]["status"] == "TAMPERED"

    def test_coverage_is_inside_the_hashed_manifest(self, client):
        bundle = client.get(f"/v1/execution/proposals/{_executed(client)}/evidence").json()
        assert "evidence_coverage" in bundle["manifest"]["section_sha256"]
