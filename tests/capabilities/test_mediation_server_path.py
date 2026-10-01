# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""NTA-2 on the execution API: the ceiling comes from the signed ToolSpec.

A mediated tool executed through /execute-accepted receives effect authority
derived from the capability set bound into its lease and the downstream
ceiling its signed v2 ToolSpec declares. The chain's execution_result carries
the nested-effect summary, and the evidence export assesses
success_established_v2 next to v1.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from remora.toolcall.toolspec import sign_bundle  # noqa: E402
from tests.capabilities import mediated_registry  # noqa: E402
from tests.capabilities.test_capability_server_path import READ, _mod, _token  # noqa: E402
from tests.capabilities.test_capability_server_path import client as _client  # noqa: E402,F401
from tests.test_toolspec_runtime import IDENTITY, KEY, _spec  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path, request):
    spec = _spec(
        tool_id="read_telemetry", action_type="read", credential_scope=["telemetry:read"],
        allowed_targets=["staging"],
        argument_schema={"type": "object", "properties": {"asset": {"type": "string"}},
                         "required": ["asset"], "additionalProperties": False},
        semantic_contract={"capability": "telemetry", "effect": "read",
                           "resource_type": "asset", "mutation": False,
                           "argument_roles": {"asset": "target_resource"}},
        downstream_capabilities=[{"capability": "database.read",
                                  "resources": ["database://telemetry-eu/*"],
                                  "purpose": "read_readings"}])
    bundle = sign_bundle({"schema_version": 2, "tool_specs": [spec]}, key=KEY,
                         signing_identity=IDENTITY, signed_at="2026-09-29T00:00:00+00:00")
    path = tmp_path / "toolspecs.json"
    path.write_text(json.dumps(bundle))
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(path))
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
    monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)
    from remora.execution.authorization import reset_toolspec_bundle_cache

    reset_toolspec_bundle_cache()
    mediated_registry.EFFECT_CALLS.clear()
    request.getfixturevalue("_client")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.capabilities.mediated_registry")
    _mod()._reset_tool_dispatcher()
    from fastapi.testclient import TestClient

    import servers.api as api_mod

    yield TestClient(api_mod.app)
    reset_toolspec_bundle_cache()


def _execute(client):
    return client.post("/v1/execution/execute-accepted",
                       json={"execution_token": _token(READ), "tool_call": READ})


def test_the_mediated_tool_reaches_only_its_declared_effect(client):
    response = _execute(client)
    assert response.status_code == 200, response.text
    execution = response.json()["tool_execution"]
    assert execution["executed"] is True
    assert execution["result"]["rows"] == [42]
    assert execution["result"]["upload"] == "capability_not_allowed"
    assert mediated_registry.EFFECT_CALLS == [("database.read", "database://telemetry-eu/P-1")]
    assert execution["nested_effects"]["by_state"] == {"EXECUTED": 1, "REFUSED": 1}
    assert [c["capability"] for c in execution["effect_graph"]["children"]] == [
        "database.read", "network.http.post"]


def test_the_chain_records_the_nested_summary_not_the_results(client):
    _execute(client)
    record = [e.payload for e in _mod()._CHAIN.entries("acme")
              if e.payload.get("event") == "execution_result"][-1]
    assert record["nested_effects"]["settled"] is True
    assert record["nested_effects"]["count"] == 2
    assert "rows" not in json.dumps(record)


def test_the_evidence_export_assesses_both_success_contracts(client):
    body = _execute(client).json()
    proposal_id = body.get("proposal_id") or body["tool_execution"]["proposal_id"]
    export = client.get(f"/v1/execution/proposals/{proposal_id}/evidence")
    assert export.status_code == 200, export.text
    coverage = export.json()["evidence_coverage"]
    v1, v2 = coverage["success_established_v1"], coverage["success_established_v2"]
    # No effect verifier is bound here, so neither is COMPLETE; the point is
    # that v2 does not list the nested requirement as missing: it holds.
    assert "execution_result[nested_effects.settled=True,tool_executed=True]" in v2["satisfied"]
    assert v1["status"] == v2["status"]
