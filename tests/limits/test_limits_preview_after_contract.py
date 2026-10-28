# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The signed contract refuses a call before the limit preview reads the plant.

``/v1/execution/assess`` ran the advisory limit preview (``_limits_or_refuse``)
before the ToolSpec check, so a call the signed contract would refuse still
reached the deployment's observer module with the agent's own argument as the
resource: an unknown unit, a value outside the schema, any target. In the
autonomous-ot-control testbed the observer put that string into a URL path on
the plant's read API. The refusal also named the limit layer
(``limit_observation_unavailable``, ``limit_exceeded``) instead of the
contract violation.

The order is now: signed contract first, then the preview. A call the contract
admits is previewed exactly as before.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from tests.limits import ventilation_sim as sim  # noqa: E402
from tests.limits.harness import _tool, call  # noqa: E402
from tests.test_toolspec_execution_wiring import _bundle_file, _client  # noqa: E402

POLICY = {
    "schema": "remora-cumulative-limits/v1",
    "limits": [{"limit_id": "supply-air-movement", "tenant": "acme",
                "quantity": "setpoint_movement", "unit": "degC", "max": 20,
                "window_seconds": 3600, "principal": "*", "resource": "*"}],
    "meters": {"set_supply_air_setpoint": [{
        "quantity": "setpoint_movement", "kind": "change", "argument": "value",
        "scale": 10, "unit": "degC", "resource_argument": "unit", "observed": True}]},
}


@pytest.fixture()
def client_and_reads(monkeypatch, tmp_path):
    import servers.execution_api as exec_mod

    sim.reset()
    reads: list[str] = []
    real = sim.observe_limit_value

    def spy(tenant: str, quantity: str, resource: str) -> float:
        reads.append(resource)
        return real(tenant, quantity, resource)

    monkeypatch.setattr(sim, "observe_limit_value", spy)
    (tmp_path / "limits.json").write_text(json.dumps(POLICY))
    monkeypatch.setenv("REMORA_LIMITS_FILE", str(tmp_path / "limits.json"))
    monkeypatch.setenv("REMORA_LIMITS_LEDGER", str(tmp_path / "limits-ledger.db"))
    monkeypatch.setenv("REMORA_LIMITS_OBSERVER_MODULE", "tests.limits.ventilation_sim")
    spec = _tool(sim.set_supply_air_setpoint, unit="string", value="number")
    spec["argument_schema"]["properties"]["unit"] = {"type": "string",
                                                     "enum": ["AHU-1", "AHU-2"]}
    spec["argument_schema"]["properties"]["value"] = {"type": "number",
                                                      "minimum": 15, "maximum": 25}
    client = _client(monkeypatch, tmp_path,
                     bundle_path=_bundle_file(tmp_path, [spec], name="order-bundle.json"))
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.limits.ventilation_sim")
    exec_mod._reset_tool_dispatcher()
    yield client, reads
    sim.reset()


def _assess(client, c):
    return client.post("/v1/execution/assess", json=c)


@pytest.mark.parametrize(("name", "c", "reason"), [
    ("unknown unit", call("set_supply_air_setpoint", unit="AHU-9", value=20.0),
     "toolspec_arguments_schema_invalid"),
    ("path in the resource", call("set_supply_air_setpoint", unit="../operations/x", value=20.0),
     "toolspec_arguments_schema_invalid"),
    ("value outside the schema", call("set_supply_air_setpoint", unit="AHU-1", value=40.0),
     "toolspec_arguments_schema_invalid"),
    ("extra argument", call("set_supply_air_setpoint", unit="AHU-1", value=20.0, force=True),
     "toolspec_arguments_schema_invalid"),
    ("target outside the spec", {**call("set_supply_air_setpoint", unit="AHU-1", value=20.0),
                                 "target_environment": "production"},
     "toolspec_target_not_allowed"),
])
def test_a_call_the_contract_refuses_never_reaches_the_observer(client_and_reads, name, c,
                                                                 reason):
    client, reads = client_and_reads
    r = _assess(client, c)
    assert r.status_code == 409, (name, r.text)
    assert r.json()["detail"].startswith(reason), (name, r.json())
    assert reads == [], f"{name}: the observer was asked about {reads}"


def test_an_admitted_call_is_still_previewed(client_and_reads):
    client, reads = client_and_reads
    r = _assess(client, call("set_supply_air_setpoint", unit="AHU-1", value=20.0))
    assert r.status_code == 200, r.text
    assert reads == ["AHU-1"]


def test_the_preview_still_refuses_an_admitted_call_over_its_limit(client_and_reads):
    client, _ = client_and_reads
    # 19.0 -> 23.0 is 4.0 degC, over the 2.0 degC hourly budget, inside the schema.
    r = _assess(client, call("set_supply_air_setpoint", unit="AHU-1", value=23.0))
    assert r.status_code == 409, r.text
    assert r.json()["detail"].startswith("limit_exceeded"), r.json()
