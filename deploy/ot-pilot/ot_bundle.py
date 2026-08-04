# Semantisk bundle for produksjonskjøringen.
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from remora.toolcall.routing.compatibility import CoverageScope, StateIndex
from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature
from remora.toolcall.semantic_bundle import ResolvedIntent, SemanticBundle


def build_semantic_bundle() -> SemanticBundle:
    registry = ToolRegistry(signatures={
        "read_sensor": ToolSignature(name="read_sensor", effect="read",
                                     required_params=("sensor_id",)),
        "adjust_setpoint": ToolSignature(name="adjust_setpoint", effect="write",
                                         required_params=("loop", "value")),
        "set_valve_position": ToolSignature(name="set_valve_position", effect="write",
                                            required_params=("valve", "position_pct")),
        "acknowledge_alarm": ToolSignature(name="acknowledge_alarm", effect="write",
                                           required_params=("alarm_id",)),
        "create_work_order": ToolSignature(name="create_work_order", effect="write",
                                           required_params=("wo_id",)),
        "close_work_order": ToolSignature(name="close_work_order", effect="write",
                                          required_params=("wo_id",)),
    })
    contracts = ToolContractRegistry([
        ToolContract(tool="read_sensor", capability="process_monitoring",
                     effect="read", resource_type="sensor", mutation=False,
                     argument_roles={"sensor_id": "target_resource"}),
        ToolContract(tool="adjust_setpoint", capability="process_control",
                     effect="update", resource_type="control_loop", mutation=True,
                     argument_roles={"loop": "target_resource"},
                     state_delta={"control_loop.setpoint": "changed"}),
        ToolContract(tool="set_valve_position", capability="process_control",
                     effect="update", resource_type="valve", mutation=True,
                     argument_roles={"valve": "target_resource"},
                     state_delta={"valve.position": "changed"}),
        ToolContract(tool="acknowledge_alarm", capability="alarm_management",
                     effect="update", resource_type="alarm", mutation=True,
                     argument_roles={"alarm_id": "target_resource"},
                     state_delta={"alarm.acked": "true"}),
        ToolContract(tool="create_work_order", capability="maintenance",
                     effect="create", resource_type="work_order", mutation=True,
                     argument_roles={"wo_id": "target_resource"},
                     state_delta={"work_order.status": "open"}),
        ToolContract(tool="close_work_order", capability="maintenance",
                     effect="close", resource_type="work_order", mutation=True,
                     argument_roles={"wo_id": "target_resource"},
                     state_delta={"work_order.status": "closed"}),
    ])
    state = StateIndex.from_values(
        {"PT-101", "TT-204", "VT-330", "LT-410", "FT-220",
         "PIC-101", "FIC-220", "V-12", "V-18", "WO-1201"},
        (CoverageScope("ot_plant",
                       frozenset({"sensor_id", "loop", "valve", "wo_id", "alarm_id"}),
                       closed_world=True),),
    )
    return SemanticBundle.build(registry=registry, contracts=contracts,
                                validators=None, state=state)


def resolve_intent(intent_ref: str) -> ResolvedIntent | None:
    cfg = os.environ.get("REMORA_INTENT_SOURCE_FILE", "").strip()
    if not cfg or not intent_ref:
        return None
    try:
        raw = Path(cfg).read_bytes()
        table = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    e = table.get(intent_ref)
    if not isinstance(e, dict) or not e.get("task_text"):
        return None
    auth = f"signed_work_order:{hashlib.sha256(raw).hexdigest()}"
    return ResolvedIntent(
        intent=TaskIntent(
            operation=str(e.get("operation", "")),
            resource_type=str(e.get("resource_type", "")),
            requested_effect=str(e.get("requested_effect", "")),
            target_entities=tuple(e.get("target_entities", ())),
            source_spans=tuple(e.get("source_spans", ())),
            action_spans=tuple(e.get("action_spans", ())),
            proposed_by=auth),
        task_text=str(e["task_text"]), authority=auth)
