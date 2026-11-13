# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The bounded-write ACCEPT path through the execution API (issue #1233).

A host signs a ToolSpec bundle and its cumulative limits, declares its tools in
``REMORA_TOOL_METADATA_FILE`` and turns on ``REMORA_BOUNDED_WRITE_ACCEPT``. A
low-tier, reversible, metered write to staging is then ACCEPTed and dispatched
with no person in the loop. What these tests pin:

* the two facts the path needs from the server (the signed spec is enforced
  for this tool, a cumulative-limit meter governs it) come from configuration,
  never from the request;
* an ACCEPT whose total would pass a limit's ``dual_control_above`` is still
  lowered to ESCALATE for two approvers;
* the reservation at dispatch still charges and still refuses
  ``limit_exceeded``;
* the tool metadata file and the signed ToolSpec must agree on
  ``action_type`` and ``risk_tier``, or the server refuses to start.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tests.limits import registry  # noqa: E402
from tests.limits.harness import _tool, ran  # noqa: E402
from tests.test_toolspec_execution_wiring import (  # noqa: E402
    IDENTITY,
    KEY,
    _bundle_file,
    _client,
)

DAY = 86400
REPO = Path(__file__).resolve().parents[1]


def _low(spec: dict, tier: str = "low") -> dict:
    return {**spec, "risk_tier": tier}


def _specs(fan_tier: str = "low") -> list[dict]:
    return [
        _low(_tool(registry.run_fan_minutes, unit="string", minutes="integer"), fan_tier),
        _low(_tool(registry.start_fan, unit="string")),
    ]


def _entry(action_type: str = "write", risk_tier: str = "low") -> dict:
    return {"risk_tier": risk_tier, "domain": "building_automation",
            "action_type": action_type, "target_environment": "staging",
            "rollback_available": True, "schema_valid": True}


def _metadata(tmp_path, **tools: dict) -> Path:
    path = tmp_path / "tool_metadata.json"
    tools = tools or {"run_fan_minutes": _entry(), "start_fan": _entry()}
    path.write_text(json.dumps({"version": 1, "tools": tools}), encoding="utf-8")
    return path


def _policy(max_minutes: int = 60, dual_control_above: int | None = None) -> dict:
    limit = {"limit_id": "fan-runtime", "tenant": "acme", "principal": "*",
             "resource": "*", "quantity": "fan_runtime", "unit": "min",
             "max": max_minutes, "window_seconds": DAY}
    if dual_control_above is not None:
        limit["dual_control_above"] = dual_control_above
    return {"schema": "remora-cumulative-limits/v1",
            "meters": {"run_fan_minutes": [{"quantity": "fan_runtime", "kind": "sum",
                                            "argument": "minutes", "unit": "min",
                                            "resource_argument": "unit"}]},
            "limits": [limit]}


def _signed(policy: dict) -> tuple[dict, str]:
    from remora.crypto import SignatureDomain, SigningKey
    from remora.enforcement.cumulative_limits import sign_policy

    key = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    return (sign_policy(policy, key, "2026-11-13T00:00:00Z"),
            key.verification_key().public_bytes.hex())


def _host(monkeypatch, tmp_path, *, policy: dict | None = None, bundle: bool = True,
          specs: list[dict] | None = None, accept: str = "1", require_intent: str = "0",
          max_tier: str = "low"):
    """A host as issue #1233 describes it, embedding the execution API in-process."""
    import servers.execution_api as exec_mod
    from remora.toolcall.deployment_registry import reset_deployment_tool_metadata

    monkeypatch.setenv("REMORA_LIMITS_TOOL_LOG", str(tmp_path / "tool-log.jsonl"))
    for var in ("REMORA_LIMITS_FILE", "REMORA_LIMITS_LEDGER", "REMORA_LIMITS_TRUSTED_KEYS",
                "REMORA_LIMITS_EVIDENCE_MODULE", "REMORA_REQUIRE_IDEMPOTENCY",
                "REMORA_REQUIRE_LIMITS", "REMORA_LIMITS_OBSERVER_MODULE"):
        monkeypatch.delenv(var, raising=False)
    if policy is not None:
        signed, public = _signed(policy)
        (tmp_path / "limits.json").write_text(json.dumps(signed), encoding="utf-8")
        monkeypatch.setenv("REMORA_LIMITS_FILE", str(tmp_path / "limits.json"))
        monkeypatch.setenv("REMORA_LIMITS_LEDGER", str(tmp_path / "limits-ledger.db"))
        monkeypatch.setenv("REMORA_LIMITS_TRUSTED_KEYS", public)
    bundle_path = (_bundle_file(tmp_path, specs or _specs(), name="host-bundle.json")
                   if bundle else None)
    client = _client(monkeypatch, tmp_path, bundle_path=bundle_path)
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.limits.registry")
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", str(_metadata(tmp_path)))
    monkeypatch.setenv("REMORA_BOUNDED_WRITE_ACCEPT", accept)
    monkeypatch.setenv("REMORA_BOUNDED_WRITE_REQUIRE_INTENT", require_intent)
    monkeypatch.setenv("REMORA_BOUNDED_WRITE_MAX_TIER", max_tier)
    reset_deployment_tool_metadata()
    monkeypatch.setattr(exec_mod, "_ENGINE", exec_mod._engine_from_env())
    exec_mod._reset_tool_dispatcher()
    registry.FAIL_NEXT.clear()
    return client


@pytest.fixture(autouse=True)
def _fresh_metadata_cache():
    from remora.toolcall.deployment_registry import reset_deployment_tool_metadata

    reset_deployment_tool_metadata()
    yield
    reset_deployment_tool_metadata()


def _call(tool: str = "run_fan_minutes", target: str = "staging", **arguments) -> dict:
    if not arguments:
        arguments = ({"unit": "AHU-1", "minutes": 10} if tool == "run_fan_minutes"
                     else {"unit": "AHU-1"})
    # A context of its own per call: repeating one call in one context is
    # what loop safety escalates, and that is not what these tests are about.
    return {"tool_name": tool, "arguments": arguments, "target_environment": target,
            "schema_valid": True, "rollback_available": True,
            "context_id": f"ctx-{uuid.uuid4().hex[:8]}", "task_id": "task-1"}


def _assess(client, call: dict) -> dict:
    r = client.post("/v1/execution/assess", json=call)
    assert r.status_code == 200, r.text
    return r.json()


def _redeem(client, assessed: dict, call: dict) -> dict:
    r = client.post("/v1/execution/execute-accepted",
                    json={"execution_token": assessed["execution_token"], "tool_call": call})
    assert r.status_code == 200, r.text
    return r.json()


def _events(name: str) -> list[dict]:
    import servers.execution_api as exec_mod

    return [e.payload for e in exec_mod._CHAIN.entries("acme")
            if e.payload.get("event") == name]


# ── The path, end to end over HTTP ──────────────────────────────────────────

def test_a_bounded_write_is_accepted_and_runs_with_no_person(monkeypatch, tmp_path):
    client = _host(monkeypatch, tmp_path, policy=_policy())
    call = _call()
    assessed = _assess(client, call)
    assert assessed["decision"] == "accept", assessed
    assert "bounded_write_accept" in assessed["reasons"]
    assert "review_item_id" not in assessed and assessed.get("execution_token")
    executed = _redeem(client, assessed, call)
    assert executed["tool_execution"]["executed"] is True, executed
    assert [r["tool"] for r in ran(tmp_path)] == ["run_fan_minutes"]
    assert _events("approved") == []


def _server_facts(monkeypatch, tmp_path, call: dict) -> tuple[bool | None, bool | None]:
    import servers.execution_api as exec_mod
    from servers.execution_contracts import ToolCallRequest

    obs = exec_mod._observation(ToolCallRequest(**call), "acme")
    return obs.toolspec_enforced, obs.cumulative_limit_metered


def test_the_server_sets_both_facts_from_its_own_configuration(monkeypatch, tmp_path):
    _host(monkeypatch, tmp_path, policy=_policy())
    assert _server_facts(monkeypatch, tmp_path, _call()) == (True, True)
    assert _server_facts(monkeypatch, tmp_path, _call("start_fan")) == (True, False)


def test_with_the_flag_off_the_observation_carries_neither_fact(monkeypatch, tmp_path):
    _host(monkeypatch, tmp_path, policy=_policy(), accept="0")
    assert _server_facts(monkeypatch, tmp_path, _call()) == (None, None)


#: One API-level case per condition the server contributes, each on its own.
API_REFUSALS = {
    "flag_off": dict(host=dict(accept="0")),
    "toolspec_not_enforced": dict(host=dict(bundle=False)),
    "toolspec_disagrees_with_metadata": dict(host=dict(specs=_specs(fan_tier="medium"))),
    "no_limits_configured": dict(host=dict(policy=None)),
    "tool_not_metered": dict(call=dict(tool="start_fan")),
    "production_target": dict(call=dict(target="prod")),
    "intent_required_and_absent": dict(host=dict(require_intent="1")),
    "caller_declares_no_rollback": dict(patch={"rollback_available": False}),
    "caller_declares_schema_invalid": dict(patch={"schema_valid": False}),
}


@pytest.mark.parametrize("case", sorted(API_REFUSALS))
def test_each_missing_condition_is_not_accepted(monkeypatch, tmp_path, case):
    spec = API_REFUSALS[case]
    host = {"policy": _policy(), **spec.get("host", {})}
    client = _host(monkeypatch, tmp_path, **host)
    call = {**_call(**spec.get("call", {})), **spec.get("patch", {})}
    assessed = _assess(client, call)
    assert assessed["decision"] != "accept", (case, assessed)
    assert "bounded_write_accept" not in assessed["reasons"], case
    assert "execution_token" not in assessed, case


@pytest.mark.parametrize("missing", ["bundle", "meter"])
def test_a_caller_cannot_assert_the_server_only_facts(monkeypatch, tmp_path, missing):
    """``toolspec_enforced`` and ``cumulative_limit_metered`` in the request
    are unknown extras: ignored, never read as the fact."""
    client = _host(monkeypatch, tmp_path, policy=_policy(), bundle=missing != "bundle")
    call = {**_call("run_fan_minutes" if missing == "bundle" else "start_fan"),
            "toolspec_enforced": True, "cumulative_limit_metered": True}
    assessed = _assess(client, call)
    assert assessed["decision"] != "accept", assessed
    assert "bounded_write_accept" not in assessed["reasons"]
    from servers.execution_contracts import ToolCallRequest

    assert not hasattr(ToolCallRequest(**call), "toolspec_enforced")
    assert not hasattr(ToolCallRequest(**call), "cumulative_limit_metered")


def test_a_medium_ceiling_lets_a_medium_write_through(monkeypatch, tmp_path):
    from remora.toolcall.deployment_registry import reset_deployment_tool_metadata

    client = _host(monkeypatch, tmp_path, policy=_policy(), max_tier="medium",
                   specs=_specs(fan_tier="medium"))
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", str(_metadata(
        tmp_path, run_fan_minutes=_entry(risk_tier="medium"), start_fan=_entry())))
    reset_deployment_tool_metadata()
    assessed = _assess(client, _call())
    assert assessed["decision"] == "accept", assessed
    assert "bounded_write_accept" in assessed["reasons"]


# ── What already holds downstream still holds ───────────────────────────────

def test_an_accept_past_dual_control_above_becomes_escalate(monkeypatch, tmp_path):
    client = _host(monkeypatch, tmp_path, policy=_policy(dual_control_above=20))
    first = _call(unit="AHU-1", minutes=15)
    assessed = _assess(client, first)
    assert assessed["decision"] == "accept", assessed
    assert _redeem(client, assessed, first)["tool_execution"]["executed"] is True
    past = _assess(client, _call(unit="AHU-1", minutes=10))      # 25 > 20
    assert past["decision"] == "escalate", past
    assert "execution_token" not in past
    assert past["approvals_required"] == 2
    assert [r["minutes"] for r in ran(tmp_path)] == [15]


def test_the_reservation_still_charges_and_refuses_at_dispatch(monkeypatch, tmp_path):
    client = _host(monkeypatch, tmp_path, policy=_policy(max_minutes=25))
    calls = [_call(unit="AHU-1", minutes=10) for _ in range(3)]
    # The assess preview is advisory: all three fit an empty ledger.
    grants = [_assess(client, c) for c in calls]
    assert [g["decision"] for g in grants] == ["accept"] * 3, grants
    results = [_redeem(client, g, c)["tool_execution"] for g, c in zip(grants, calls)]
    assert [r["executed"] for r in results] == [True, True, False]
    assert results[2]["refusal_reason"] == "limit_exceeded"
    assert sum(r["minutes"] for r in ran(tmp_path)) == 20
    # The two that ran were charged: the next one is refused before anything is decided.
    refused = client.post("/v1/execution/assess", json=_call(unit="AHU-1", minutes=10))
    assert refused.status_code == 409 and refused.json()["detail"] == "limit_exceeded"


# ── Through the SDK, as a host uses it ──────────────────────────────────────

def test_a_host_runs_a_bounded_write_through_the_sdk_with_no_person(monkeypatch, tmp_path):
    import servers.api as api_mod
    from fastapi.testclient import TestClient

    from remora.sdk import DecisionAction, RemoraClient, ToolCall

    _host(monkeypatch, tmp_path, policy=_policy(dual_control_above=50))
    sdk = RemoraClient(base_url="http://testserver", token="test-token",
                       http_client=TestClient(api_mod.app))
    try:
        call = ToolCall(tool_name="run_fan_minutes", arguments={"unit": "AHU-2", "minutes": 5},
                        target_environment="staging", schema_valid=True,
                        rollback_available=True)
        assessment = sdk.assess(call)
        assert assessment.action is DecisionAction.ACCEPT, assessment.reasons
        assert "bounded_write_accept" in assessment.reasons
        assert assessment.review_item_id is None
        assert assessment.toolspec is not None and assessment.toolspec.enforced is True
        outcome = sdk.execute_accepted(assessment.execution_token, call)
        assert outcome.tool_execution is not None
        assert outcome.tool_execution["executed"] is True, outcome.raw
        assert sdk.verify_audit_chain().valid is True
    finally:
        sdk.close()
    assert ran(tmp_path) == [{"tool": "run_fan_minutes", "unit": "AHU-2", "minutes": 5}]
    assert _events("approved") == []


# ── The metadata file and the signed ToolSpec must agree ─────────────────────

def _configure_cross_check(monkeypatch, tmp_path, **tools: dict) -> None:
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(_bundle_file(tmp_path, _specs(),
                                                                  name="check.json")))
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
    monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", str(_metadata(tmp_path, **tools)))
    import servers.execution_api as exec_mod

    exec_mod._reset_toolspec_bundle()


@pytest.mark.parametrize("field,entry,signed", [
    ("action_type", _entry(action_type="read"), "write"),
    ("risk_tier", _entry(risk_tier="medium"), "low"),
])
def test_a_metadata_file_that_disagrees_with_the_signed_spec_refuses(
        monkeypatch, tmp_path, field, entry, signed):
    import servers.api as api_mod
    from remora.toolcall.deployment_registry import DeploymentRegistryError

    _configure_cross_check(monkeypatch, tmp_path, run_fan_minutes=entry, start_fan=_entry())
    with pytest.raises(DeploymentRegistryError) as refused:
        api_mod._validate_deployment_tool_metadata()
    message = str(refused.value)
    assert "run_fan_minutes" in message and field in message and signed in message


def test_a_matching_metadata_file_is_accepted(monkeypatch, tmp_path):
    import servers.api as api_mod

    _configure_cross_check(monkeypatch, tmp_path)
    api_mod._validate_deployment_tool_metadata()


def test_metadata_for_a_tool_the_bundle_does_not_sign_is_not_compared(monkeypatch, tmp_path):
    import servers.api as api_mod

    _configure_cross_check(monkeypatch, tmp_path, run_fan_minutes=_entry(),
                           other_tool=_entry(action_type="read"))
    api_mod._validate_deployment_tool_metadata()


def test_the_mismatch_stops_the_server_from_starting(tmp_path):
    """Run as a host would: import the app with the two files configured."""
    bundle = _bundle_file(tmp_path, _specs(), name="startup.json")
    metadata = _metadata(tmp_path, run_fan_minutes=_entry(action_type="read"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("REMORA_")}
    env.update({"REMORA_ENV": "development", "REMORA_PDP_SIGNING_KEY": "startup-key",
                "REMORA_TOOLSPEC_BUNDLE": str(bundle), "REMORA_TOOLSPEC_SIGNING_KEY": KEY,
                "REMORA_TOOLSPEC_TRUSTED_IDENTITIES": IDENTITY,
                "REMORA_TOOL_METADATA_FILE": str(metadata),
                "PYTHONPATH": str(REPO)})
    started = subprocess.run([sys.executable, "-c", "import servers.api"], cwd=REPO, env=env,
                             capture_output=True, text=True, timeout=300)
    assert started.returncode != 0
    assert "run_fan_minutes" in started.stderr and "action_type" in started.stderr
