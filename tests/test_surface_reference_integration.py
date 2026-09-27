# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Real REMORA reference dispatch, signed specs, file readback and reproducible evidence."""
import json
from dataclasses import replace

import pytest

from remora.toolcall.surface_evaluation import evaluate_reference, reference_runtime, reference_lease
from remora.toolcall.toolspec import ToolSpecRefused


def test_actual_reference_effect_and_refusal_paths():
    cases = evaluate_reference()["cases"]
    assert cases["verified"]["property"] == "EFFECT_VERIFIED"
    assert cases["mismatch"]["property"] == "EFFECT_MISMATCH"
    assert cases["unobserved"]["property"] == "NOT_ESTABLISHED"
    for case in ("verified", "mismatch", "unobserved"):
        assert cases[case]["runtime"] == "SUCCEEDED"
        assert cases[case]["receipt"] == "FRESH_AND_BOUND"
        assert cases[case]["rechecked"]
    for case in ("extra_tool", "replacement", "missing_lease"):
        assert cases[case]["runtime"] == "REFUSED"
        assert not cases[case]["file_written"]
    assert cases["shadow_drift"]["runtime"] == "SUCCEEDED"
    assert cases["shadow_drift"]["surface"] == "MISMATCH"
    assert cases["alternate_effect_path"]["paths"] == [["shell", "write"]]
    assert cases["incomplete_inventory"]["verdict"] == "NOT_ESTABLISHED"


@pytest.mark.docgate
def test_committed_reference_artifact_reproduces(repo_root):
    artifact = repo_root / "artifacts/runtime_surface/reference_runtime_v1.json"
    assert json.loads(artifact.read_text(encoding="utf-8")) == evaluate_reference()


def test_signed_runtime_rejects_callable_schema_and_scope_changes(tmp_path):
    rt, store, observed, _ = reference_runtime(tmp_path)
    with pytest.raises(ToolSpecRefused, match="registered callable"):
        rt.register(observed, lambda args: args)
    with pytest.raises(ValueError, match="metadata_mismatch"):
        rt.register(replace(observed, argument_schema_json='{"type":"array"}'), store.write)
    with pytest.raises(ToolSpecRefused, match="scope beyond"):
        rt.register(replace(observed, credential_scope=("root",)), store.write)
    with pytest.raises(ToolSpecRefused):
        rt.assess("write", {"value": "not-an-integer"}, tenant="reference",
                  principal="reference-agent", target="local-record")
    with pytest.raises(ToolSpecRefused):
        rt.assess("write", {"value": 1}, tenant="reference",
                  principal="reference-agent", target="elsewhere")


def test_replacement_before_assessment_cannot_use_signed_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "test-only-key")
    rt, store, _, spec = reference_runtime(tmp_path, mode="shadow")
    rt.dispatcher.register("write", lambda args: args)
    assessment = rt.assess("write", {"value": 1}, tenant="reference",
                           principal="reference-agent", target="local-record")
    outcome = rt.dispatch(assessment.assessment_id, reference_lease(spec), "write", {"value": 1},
                           tenant="reference", principal="reference-agent", target="local-record")
    assert outcome.runtime_outcome == "REFUSED"
    assert not store.path.exists()
