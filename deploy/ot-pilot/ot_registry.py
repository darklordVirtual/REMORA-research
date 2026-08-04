# OT-verktøy for produksjonskjøringen. Sideeffekter er ekte, men bundet til
# en sandkasse-katalog og et in-memory anleggs-state.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

PLANT: dict[str, Any] = {
    "sensors": {
        "PT-101": {"unit": "bar", "value": 4.10},
        "TT-204": {"unit": "degC", "value": 61.5},
        "VT-330": {"unit": "mm/s", "value": 2.1},
        "LT-410": {"unit": "%", "value": 71.0},
        "FT-220": {"unit": "m3/h", "value": 118.0},
    },
    "loops": {"PIC-101": {"setpoint": 4.00}, "FIC-220": {"setpoint": 120.0}},
    "valves": {"V-12": {"pct": 15}, "V-18": {"pct": 40}},
    "alarms": {"LT-410-HI": {"acked": False}, "PT-101-HH": {"acked": False}},
    "work_orders": {"WO-1201": {"status": "open"}},
    "log": [],
}


def _log(tool: str, **kw: Any) -> None:
    PLANT["log"].append({"at": datetime.now(UTC).isoformat(), "tool": tool, **kw})


def read_sensor(a: dict[str, Any]) -> dict[str, Any]:
    sid = str(a.get("sensor_id", ""))
    s = PLANT["sensors"].get(sid)
    if s is None:
        raise ValueError(f"unknown sensor {sid!r}")
    _log("read_sensor", sensor_id=sid, value=s["value"])
    return {"sensor_id": sid, **s}


def adjust_setpoint(a: dict[str, Any]) -> dict[str, Any]:
    loop = str(a.get("loop", ""))
    lp = PLANT["loops"].get(loop)
    if lp is None:
        raise ValueError(f"unknown loop {loop!r}")
    old, new = lp["setpoint"], float(a["value"])
    lp["setpoint"] = new
    _log("adjust_setpoint", loop=loop, old=old, new=new)
    return {"loop": loop, "old_setpoint": old, "new_setpoint": new}


def set_valve_position(a: dict[str, Any]) -> dict[str, Any]:
    v = str(a.get("valve", ""))
    val = PLANT["valves"].get(v)
    if val is None:
        raise ValueError(f"unknown valve {v!r}")
    old, new = val["pct"], int(a["position_pct"])
    val["pct"] = new
    _log("set_valve_position", valve=v, old=old, new=new)
    return {"valve": v, "old_pct": old, "new_pct": new}


def acknowledge_alarm(a: dict[str, Any]) -> dict[str, Any]:
    aid = str(a.get("alarm_id", ""))
    al = PLANT["alarms"].get(aid)
    if al is None:
        raise ValueError(f"unknown alarm {aid!r}")
    al["acked"] = True
    _log("acknowledge_alarm", alarm_id=aid)
    return {"alarm_id": aid, "acked": True}


def create_work_order(a: dict[str, Any]) -> dict[str, Any]:
    wo = str(a.get("wo_id", ""))
    PLANT["work_orders"][wo] = {"status": "open"}
    _log("create_work_order", wo_id=wo)
    return {"wo_id": wo, "status": "open"}


def close_work_order(a: dict[str, Any]) -> dict[str, Any]:
    wo = str(a.get("wo_id", ""))
    rec = PLANT["work_orders"].get(wo)
    if rec is None:
        raise ValueError(f"unknown work order {wo!r}")
    rec["status"] = "closed"
    _log("close_work_order", wo_id=wo)
    return {"wo_id": wo, "status": "closed"}


def register_tools(register: Callable[[str, Callable[[Any], Any]], None]) -> None:
    for name, fn in (
        ("read_sensor", read_sensor),
        ("adjust_setpoint", adjust_setpoint),
        ("set_valve_position", set_valve_position),
        ("acknowledge_alarm", acknowledge_alarm),
        ("create_work_order", create_work_order),
        ("close_work_order", close_work_order),
    ):
        register(name, fn)
