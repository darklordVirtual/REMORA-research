# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Surface and effect evidence survive a restart (quality program Q3.5).

``SurfaceRuntime`` kept its tenant chain, executions and effects in memory,
so a restart lost the evidence that a tool ran and what its effect was
(AST-011). With a durable chain the evidence is written through, and a
runtime started on the same store can recheck it.
"""
from __future__ import annotations

import pytest

from remora.governance.effect_verification import PostconditionContract
from remora.governance.tenant_chain import SQLiteTenantChain
from remora.toolcall.surface_evaluation import reference_lease, reference_runtime

TENANT = "reference"
KEY = "durable-surface-spec-key"


@pytest.fixture(autouse=True)
def _lease_key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "durable-surface-lease-key")


def _executed(root, chain):
    runtime, store, _, spec = reference_runtime(root, chain=chain, key=KEY)
    assessment = runtime.assess(
        "write", {"value": 1}, tenant=TENANT, principal="reference-agent",
        target="local-record",
        postcondition=PostconditionContract("write", "local-reader", {"id": "record"}, {"value": 1}))
    outcome = runtime.dispatch(assessment.assessment_id, reference_lease(spec), "write",
                               {"value": 1}, tenant=TENANT, principal="reference-agent",
                               target="local-record")
    assert outcome.runtime_outcome == "SUCCEEDED"
    return runtime, store, assessment.assessment_id


def _restart(root, chain):
    return reference_runtime(root, chain=chain, key=KEY)[0]


def _record(runtime, store, assessment_id):
    return runtime.record_effect(assessment_id, tenant=TENANT, principal="reference-reader",
                                 verifier_identity="local-reader", observed=store.read())


class TestDurableChain:
    def test_effect_evidence_rechecks_after_a_restart(self, tmp_path):
        db = str(tmp_path / "surface.db")
        first, store, assessment_id = _executed(tmp_path, SQLiteTenantChain(db))
        evidence = _record(first, store, assessment_id)
        restarted = _restart(tmp_path, SQLiteTenantChain(db))
        assert restarted.recheck_effect(assessment_id, tenant=TENANT) == evidence
        assert restarted.audit_valid(TENANT)

    def test_an_effect_can_be_recorded_after_a_restart(self, tmp_path):
        db = str(tmp_path / "surface.db")
        _, store, assessment_id = _executed(tmp_path, SQLiteTenantChain(db))
        restarted = _restart(tmp_path, SQLiteTenantChain(db))
        evidence = _record(restarted, store, assessment_id)
        assert evidence["property_verdict"] == "EFFECT_VERIFIED"

    def test_a_settled_effect_stays_settled_after_a_restart(self, tmp_path):
        db = str(tmp_path / "surface.db")
        first, store, assessment_id = _executed(tmp_path, SQLiteTenantChain(db))
        _record(first, store, assessment_id)
        restarted = _restart(tmp_path, SQLiteTenantChain(db))
        with pytest.raises(ValueError, match="effect_already_settled"):
            _record(restarted, store, assessment_id)

    def test_the_restarted_chain_keeps_every_entry(self, tmp_path):
        db = str(tmp_path / "surface.db")
        first, store, assessment_id = _executed(tmp_path, SQLiteTenantChain(db))
        _record(first, store, assessment_id)
        before = first.audit_entries(TENANT)
        assert _restart(tmp_path, SQLiteTenantChain(db)).audit_entries(TENANT) == before


class TestTheInMemoryControl:
    def test_without_a_durable_chain_a_restart_loses_the_evidence(self, tmp_path):
        first, store, assessment_id = _executed(tmp_path, None)
        _record(first, store, assessment_id)
        restarted = _restart(tmp_path, None)
        with pytest.raises(ValueError, match="effect_not_found"):
            restarted.recheck_effect(assessment_id, tenant=TENANT)
        with pytest.raises(ValueError, match="execution_not_found"):
            _record(restarted, store, assessment_id)


def test_the_committed_reference_artifact_is_unchanged(repo_root):
    import json

    from remora.toolcall.surface_evaluation import evaluate_reference

    artifact = repo_root / "artifacts/runtime_surface/reference_runtime_v1.json"
    assert json.loads(artifact.read_text(encoding="utf-8")) == evaluate_reference()
