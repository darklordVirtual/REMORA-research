# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's own limits, tools and semantic bundle through the execution API.

``deploy/ot-pilot`` ships ``limits.json`` with coverage ``all_writes``. The
pilot has no signed ToolSpec bundle, so which tools write comes from its
semantic bundle. These tests load the pilot's registry, bundle, work orders
and limits as the container does and pin that the battery's own writes still
run, that small setpoint and valve moves cannot add up past the limit, and
that a write tool the limits forget is refused.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from tests.test_toolspec_execution_wiring import _client  # noqa: E402

PILOT = Path(__file__).resolve().parents[2] / "deploy" / "ot-pilot"


def _compose_env(name):
    for line in (PILOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}:"):
            return line.split(":", 1)[1].strip().strip('"')
    raise KeyError(name)


PILOT_KEY = _compose_env("REMORA_LIMITS_TRUSTED_KEYS")


def shipped_policy():
    """The policy inside the pilot's signed limits.json."""
    return json.loads((PILOT / "limits.json").read_text(encoding="utf-8"))["policy"]


@pytest.fixture()
def pilot(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(PILOT))
    import ot_registry

    saved = copy.deepcopy(ot_registry.PLANT)
    client = _client(monkeypatch, tmp_path)

    def configure(limits=None, trusted_key=None):
        import servers.api as api_mod
        import servers.execution_api as exec_mod

        monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("ot-pilot", "reviewer"))
        # Who acts comes from a header, so a dual-control item can be given
        # two distinct approvers; without it, the one principal as before.
        monkeypatch.setattr(api_mod, "_authenticated_principal",
                            lambda request: request.headers.get("x-test-principal",
                                                                "pilot-reviewer"))
        path = tmp_path / "limits.json"
        path.write_text(json.dumps(limits) if limits is not None
                        else (PILOT / "limits.json").read_text(encoding="utf-8"))
        monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "ot_registry")
        monkeypatch.setenv("REMORA_SEMANTIC_BUNDLE_MODULE", "ot_bundle")
        monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", str(PILOT / "work_orders.json"))
        monkeypatch.setenv("REMORA_LIMITS_FILE", str(path))
        monkeypatch.setenv("REMORA_LIMITS_LEDGER", str(tmp_path / "limits-ledger.db"))
        monkeypatch.setenv("REMORA_LIMITS_OBSERVER_MODULE", "ot_registry")
        monkeypatch.setenv("REMORA_REQUIRE_LIMITS", _compose_env("REMORA_REQUIRE_LIMITS"))
        monkeypatch.setenv("REMORA_LIMITS_TRUSTED_KEYS", trusted_key or PILOT_KEY)
        exec_mod._reset_semantic_bundle()
        exec_mod._reset_tool_dispatcher()
        return client

    yield configure
    ot_registry.PLANT.clear()
    ot_registry.PLANT.update(saved)
    sys.modules.pop("ot_registry", None)
    sys.modules.pop("ot_bundle", None)


def payload(tool, intent_ref, **arguments):
    return {"tool_name": tool, "arguments": arguments, "target_environment": "prod",
            "intent_ref": intent_ref}


def run(client, p):
    """Assess, approve and execute one call; a dual-control item gets a second approver."""
    agent = {"x-test-principal": "pilot-agent"}
    r = client.post("/v1/execution/assess", json=p, headers=agent)
    if r.status_code != 200:
        return {"stage": "assess", "status": r.status_code, "detail": r.json()["detail"]}
    item = r.json().get("review_item_id")
    if item is None:
        return {"stage": "assess", "decision": r.json()["decision"]}
    client.post("/v1/execution/approve", json={"item_id": item, "approval_ttl_seconds": 900})
    if r.json().get("approvals_required") == 2:
        client.post("/v1/execution/approve", headers={"x-test-principal": "second-reviewer"},
                    json={"item_id": item, "approval_ttl_seconds": 900})
    e = client.post("/v1/execution/execute", json={"item_id": item, "tool_call": p},
                    headers=agent).json()
    execution = e.get("tool_execution") or {}
    return {"stage": "execute", "executed": execution.get("executed"),
            "refusal": execution.get("refusal_reason")}


def test_the_shipped_limits_file_loads_and_covers_every_pilot_write():
    from remora.enforcement.cumulative_limits import LimitPolicy

    policy = LimitPolicy.from_dict(shipped_policy())
    sys.path.insert(0, str(PILOT))
    try:
        import ot_bundle

        bundle = ot_bundle.build_semantic_bundle()
    finally:
        sys.path.remove(str(PILOT))
        sys.modules.pop("ot_bundle", None)
    writes = {name for name, c in bundle.contracts.contracts.items() if c.mutation}
    assert policy.coverage == "all_writes" and writes == set(policy.meters)


def test_the_battery_writes_still_run(pilot):
    client = pilot()
    import ot_registry

    assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                               value=3.8))["executed"] is True
    assert run(client, payload("set_valve_position", "WO-1204", valve="V-12",
                               position_pct=35))["executed"] is True
    assert ot_registry.PLANT["loops"]["PIC-101"]["setpoint"] == 3.8


def test_small_setpoint_moves_cannot_add_up(pilot):
    client = pilot()
    # 1.60 bar of PIC-101 movement per hour (recalibrated 2026-11-06, plan v2):
    # 4.00 -> 3.60 -> 4.00 -> 3.60 -> 4.00 is 1.60, and one more 0.10 is past it.
    for value in (3.6, 4.0, 3.6, 4.0):
        assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                                   value=value))["executed"] is True
    assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                               value=3.9)) == {"stage": "assess", "status": 409,
                                               "detail": "limit_exceeded"}


def test_valve_strokes_cannot_add_up(pilot):
    client = pilot()
    # 70 percent of travel per valve per hour: 15 -> 50 -> 15 is 70.
    for position in (50, 15):
        assert run(client, payload("set_valve_position", "WO-1204", valve="V-12",
                                   position_pct=position))["executed"] is True
    assert run(client, payload("set_valve_position", "WO-1204", valve="V-12",
                               position_pct=16))["detail"] == "limit_exceeded"


def test_delivery_to_zero_runs_on_a_spent_hour_and_the_restart_is_metered(pilot):
    """FIC-220 = 0 is the pilot's declared safe value. After the hour's 180 m3/h
    of movement is spent, the stop still runs and is charged nothing; moving
    away from zero again is charged, and refused while the hour is spent."""
    client = pilot()
    import ot_registry

    for value in (160.0, 80.0, 140.0):          # 40 + 80 + 60 = 180, the hour's limit
        assert run(client, payload("adjust_setpoint", "WO-1207", loop="FIC-220",
                                   value=value))["executed"] is True
    assert run(client, payload("adjust_setpoint", "WO-1207", loop="FIC-220",
                               value=141.0))["detail"] == "limit_exceeded"
    assert run(client, payload("adjust_setpoint", "WO-1207", loop="FIC-220",
                               value=0.0))["executed"] is True
    assert ot_registry.PLANT["loops"]["FIC-220"]["setpoint"] == 0.0
    assert run(client, payload("adjust_setpoint", "WO-1207", loop="FIC-220",
                               value=20.0))["detail"] == "limit_exceeded"


def test_pic_101_is_exempt_while_delivery_is_stopped_and_metered_after(pilot):
    """With FIC-220 parked at its safe value 0, PIC-101 may be lowered for the
    restart and raised again uncharged; once delivery restarts, it is metered."""
    client = pilot()
    assert run(client, payload("adjust_setpoint", "WO-1207", loop="FIC-220",
                               value=0.0))["executed"] is True
    for value in (2.0, 4.5):                     # 2.0 + 2.5 bar, more than 1.60, exempt
        assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                                   value=value))["executed"] is True
    assert run(client, payload("adjust_setpoint", "WO-1207", loop="FIC-220",
                               value=60.0))["executed"] is True
    assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                               value=2.8))["detail"] == "limit_exceeded"     # 1.7 bar, metered


def test_a_write_tool_the_limits_forget_is_refused(pilot):
    from remora.crypto import SignatureDomain, SigningKey
    from remora.enforcement.cumulative_limits import sign_policy

    limits = shipped_policy()
    del limits["meters"]["acknowledge_alarm"]
    limits["limits"] = [lim for lim in limits["limits"] if lim["quantity"] != "alarm_acks"]
    key = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    client = pilot(sign_policy(limits, key, "2026-10-23T00:00:00Z"),
                   trusted_key=key.verification_key().public_bytes.hex())
    assert run(client, payload("acknowledge_alarm", "WO-1202",
                               alarm_id="LT-410-HI"))["detail"] == "limit_tool_unmetered"
    assert run(client, payload("read_sensor", "MON-ROUND", sensor_id="PT-101")) \
        .get("detail") != "limit_tool_unmetered"


def test_an_outside_change_at_the_plant_is_measured_not_assumed(pilot):
    client = pilot()
    import ot_registry

    ot_registry.PLANT["loops"]["PIC-101"]["setpoint"] = 2.4  # changed at the plant
    # 2.40 -> 4.00 is 1.60 of movement at the plant: the whole hour's limit.
    assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                               value=4.0))["executed"] is True
    assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                               value=4.1))["detail"] == "limit_exceeded"


def test_the_pilot_observer_reads_the_plant():
    sys.path.insert(0, str(PILOT))
    try:
        import ot_registry

        assert ot_registry.observe_limit_value("ot-pilot", "valve_travel", "V-18") == 40.0
        with pytest.raises(KeyError):
            ot_registry.observe_limit_value("ot-pilot", "alarm_acks", "LT-410-HI")
    finally:
        sys.path.remove(str(PILOT))
        sys.modules.pop("ot_registry", None)


def test_the_shipped_pilot_policy_puts_pic_101_past_half_a_bar_under_dual_control():
    """S20 (two +0.30 bar moves in an hour) is stopped by the second tier, not
    by a lower cap: the cap stays 1.60 bar, and 0.50 is where a second
    approver becomes necessary (NEGATIVE_RESULTS section 97)."""
    from remora.enforcement.cumulative_limits import LimitPolicy

    tiers = {lim.limit_id: (lim.max, lim.dual_control_above)
             for lim in LimitPolicy.from_dict(shipped_policy()).limits}
    assert tiers["pic-101-movement"] == (160, 50)
    assert all(tier is None for lid, (_, tier) in tiers.items() if lid != "pic-101-movement")


def test_s20_needs_a_second_approver_on_the_shipped_policy(pilot):
    client = pilot()
    import ot_registry

    assert run(client, payload("adjust_setpoint", "WO-1201", loop="PIC-101",
                               value=4.3))["executed"] is True
    r = client.post("/v1/execution/assess", json=payload("adjust_setpoint", "WO-1201",
                                                         loop="PIC-101", value=4.6),
                    headers={"x-test-principal": "pilot-agent"})
    assert r.json()["approvals_required"] == 2
    item = r.json()["review_item_id"]
    client.post("/v1/execution/approve", json={"item_id": item, "approval_ttl_seconds": 900})
    e = client.post("/v1/execution/execute", json={"item_id": item, "tool_call": payload(
        "adjust_setpoint", "WO-1201", loop="PIC-101", value=4.6)},
        headers={"x-test-principal": "pilot-agent"})
    assert (e.status_code, e.json()["detail"]) == (409, "dual_control_second_approval_required")
    assert ot_registry.PLANT["loops"]["PIC-101"]["setpoint"] == 4.3


def test_the_shipped_pilot_policy_is_signed_by_the_pilot_key_and_required(pilot):
    import servers.execution_api as exec_mod

    pilot()
    assert exec_mod._limit_guard().policy.coverage == "all_writes"
    assert _compose_env("REMORA_REQUIRE_LIMITS") == "1"
