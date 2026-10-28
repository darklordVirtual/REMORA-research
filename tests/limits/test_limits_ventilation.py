# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Cumulative limits on ventilation calls, through the execution API.

The payment case generalised to equipment. Each call below passes any check
that looks at one call alone: a setpoint move of 0.5 degC, one fan start,
60 minutes of runtime. What a per-call check cannot see is the total. These
tests run the calls through ``/v1/execution/assess``, ``/approve``,
``/execute`` and the governed dispatcher with sandboxed tools, and pin that

* without limits REMORA lets the total grow without bound (the baseline);
* setpoint movement, fan starts and runtime are capped per unit and window,
  shared by every principal;
* moving back counts as movement, and a move too small to count is refused;
* a controller that fails leaves the unit unknown until a new baseline;
* a write tool nobody metered is refused under ``all_writes`` coverage.
"""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")

from tests.limits import registry  # noqa: E402
from tests.limits.harness import (  # noqa: E402
    approve_and_execute,
    assess,
    call,
    make_client,
    ran,
    refused_at_dispatch,
    run,
)

HOUR, DAY = 3600, 86400


def policy(seed="s1", ahu1=19.0):
    shared = {"tenant": "acme", "principal": "*", "resource": "*"}
    return {
        "schema": "remora-cumulative-limits/v1",
        "coverage": "all_writes",
        "meters": {
            "set_supply_air_setpoint": [{"quantity": "setpoint_movement", "kind": "change",
                                         "argument": "value", "scale": 10, "unit": "degC",
                                         "resource_argument": "unit"}],
            "start_fan": [{"quantity": "fan_starts", "kind": "count", "unit": "starts",
                           "resource_argument": "unit"}],
            "run_fan_minutes": [{"quantity": "fan_runtime", "kind": "sum",
                                 "argument": "minutes", "unit": "min",
                                 "resource_argument": "unit"}],
        },
        "limits": [
            {"limit_id": "supply-air-movement", "quantity": "setpoint_movement",
             "unit": "degC", "max": 20, "window_seconds": HOUR, **shared},  # 2.0 degC
            {"limit_id": "fan-starts", "quantity": "fan_starts", "unit": "starts", "max": 3,
             "window_seconds": HOUR, **shared},
            {"limit_id": "fan-runtime", "quantity": "fan_runtime", "unit": "min",
             "max": 120, "window_seconds": DAY, **shared},
        ],
        "baselines": [
            {"tenant": "acme", "quantity": "setpoint_movement", "resource": "AHU-1",
             "value": ahu1, "seed_id": seed},
            {"tenant": "acme", "quantity": "setpoint_movement", "resource": "AHU-2",
             "value": 19.0, "seed_id": "s1"},
        ],
    }


def setpoint(value, unit="AHU-1"):
    return call("set_supply_air_setpoint", unit=unit, value=value)


def as_principal(monkeypatch, principal):
    import servers.api as api_mod

    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: principal)


def test_baseline_without_limits_small_moves_add_up_without_bound(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, None)
    for value in (19.5, 20.0, 20.5, 21.0, 21.5, 22.0, 22.5, 23.0):
        assert run(client, setpoint(value))["executed"] is True
    assert ran(tmp_path)[-1]["value"] == 23.0  # 4.0 degC in eight steps of 0.5


def test_setpoint_movement_is_capped_per_window(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    for value in (19.5, 20.0, 20.5, 21.0):
        assert run(client, setpoint(value))["executed"] is True
    assert run(client, setpoint(21.5))["detail"] == "limit_exceeded"
    assert ran(tmp_path)[-1]["value"] == 21.0


def test_moving_back_counts_as_movement(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    assert run(client, setpoint(21.0))["executed"] is True  # 2.0
    assert run(client, setpoint(19.0))["detail"] == "limit_exceeded"


def test_every_unit_has_its_own_total(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    assert run(client, setpoint(21.0))["executed"] is True
    assert run(client, setpoint(21.0, unit="AHU-2"))["executed"] is True


def test_a_second_principal_shares_the_units_limit(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    assert run(client, setpoint(20.0))["executed"] is True
    as_principal(monkeypatch, "agent-2")
    assert run(client, setpoint(21.0))["executed"] is True  # 1.0 + 1.0
    as_principal(monkeypatch, "agent-3")
    assert run(client, setpoint(21.5))["detail"] == "limit_exceeded"


def test_moves_approved_together_are_refused_at_dispatch(monkeypatch, tmp_path):
    """Each is within 2.0 of 19.0, so all five pass assess; dispatch holds."""
    client = make_client(monkeypatch, tmp_path, policy())
    values = (19.5, 20.0, 20.5, 21.0, 20.5)
    items = [(assess(client, setpoint(v)).json()["review_item_id"], v) for v in values]
    results = [approve_and_execute(client, item, setpoint(v)).json()["tool_execution"]
               for item, v in items]
    assert [r["executed"] for r in results] == [True, True, True, True, False]
    assert results[-1]["refusal_reason"] == "limit_exceeded"


def test_a_move_too_small_to_count_is_refused(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    r = assess(client, setpoint(19.05))
    assert (r.status_code, r.json()["detail"]) == (409, "limit_amount_invalid")


@pytest.mark.parametrize("value", ["20", True, None])
def test_a_value_that_is_not_a_number_is_refused(monkeypatch, tmp_path, value):
    client = make_client(monkeypatch, tmp_path, policy())
    r = assess(client, setpoint(value))
    assert r.status_code in (409, 422)
    if r.status_code == 409:
        # The signed contract (value: number) refuses it before the preview.
        assert r.json()["detail"] == "toolspec_arguments_schema_invalid"


def test_a_unit_without_a_baseline_is_refused(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    assert run(client, setpoint(19.5, unit="AHU-9"))["detail"] == "limit_baseline_unknown"


def test_a_failed_write_leaves_the_unit_unknown_until_a_new_baseline(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    import servers.execution_api as exec_mod

    monkeypatch.setattr(exec_mod, "_limits_or_refuse", lambda *a: None)
    registry.FAIL_NEXT.append(True)
    failed = run(client, setpoint(20.0))
    assert failed["executed"] is not True
    assert refused_at_dispatch(run(client, setpoint(20.0)), "limit_baseline_unknown")
    client = make_client(monkeypatch, tmp_path, policy(seed="s2", ahu1=19.0))
    assert run(client, setpoint(20.0))["executed"] is True  # the operator re-seeded


def test_fan_starts_are_capped_per_unit(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    for _ in range(3):
        assert run(client, call("start_fan", unit="AHU-1"))["executed"] is True
    assert run(client, call("start_fan", unit="AHU-1"))["detail"] == "limit_exceeded"
    assert run(client, call("start_fan", unit="AHU-2"))["executed"] is True


def test_concurrent_fan_starts_never_pass_the_limit(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    pending = [(assess(client, call("start_fan", unit="AHU-1")).json()["review_item_id"])
               for _ in range(6)]
    for item_id in pending:
        client.post("/v1/execution/approve", json={"item_id": item_id,
                                                    "approval_ttl_seconds": 600})
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda item: client.post(
            "/v1/execution/execute",
            json={"item_id": item, "tool_call": call("start_fan", unit="AHU-1")}), pending))
    assert len(ran(tmp_path)) == 3


def test_concurrent_setpoint_moves_never_pass_the_limit(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    values = (20.0, 21.0, 19.5, 20.5, 18.0, 17.5)
    pending = [(assess(client, setpoint(v)).json()["review_item_id"], v) for v in values]
    for item_id, _ in pending:
        client.post("/v1/execution/approve", json={"item_id": item_id,
                                                    "approval_ttl_seconds": 600})
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda p: client.post(
            "/v1/execution/execute", json={"item_id": p[0], "tool_call": setpoint(p[1])}),
            pending))
    conn = sqlite3.connect(tmp_path / "limits-ledger.db")
    try:
        reserved = conn.execute("SELECT COALESCE(SUM(amount),0) FROM limit_reservation "
                                "WHERE counter_key LIKE 'supply-air-movement%'").fetchone()[0]
    finally:
        conn.close()
    assert reserved <= 20
    applied = [19.0] + [r["value"] for r in ran(tmp_path)]
    movement = sum(abs(b - a) for a, b in zip(applied, applied[1:]))
    assert movement <= 2.0 + 1e-9


def test_runtime_is_capped_per_day(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    assert run(client, call("run_fan_minutes", unit="AHU-1", minutes=60))["executed"] is True
    assert run(client, call("run_fan_minutes", unit="AHU-1", minutes=60))["executed"] is True
    assert run(client, call("run_fan_minutes", unit="AHU-1",
                            minutes=1))["detail"] == "limit_exceeded"


def test_an_unmetered_write_tool_is_refused_and_a_read_is_not(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, policy())
    r = assess(client, call("reset_controller", unit="AHU-1"))
    assert (r.status_code, r.json()["detail"]) == (409, "limit_tool_unmetered")
    assert assess(client, call("read_air_temperature", unit="AHU-1")).status_code == 200


def test_an_unmetered_write_tool_is_refused_at_dispatch_too(monkeypatch, tmp_path):
    import servers.execution_api as exec_mod

    client = make_client(monkeypatch, tmp_path, policy())
    monkeypatch.setattr(exec_mod, "_limits_or_refuse", lambda *a: None)
    assert refused_at_dispatch(run(client, call("reset_controller", unit="AHU-1")),
                               "limit_tool_unmetered")
    assert ran(tmp_path) == []
