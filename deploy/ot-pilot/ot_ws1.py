# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's WS1 deployment (``REMORA_WS1_DEPLOYMENT_MODULE=ot_ws1``).

Shadow mode first: WS1 runs on every assessment through the real routes,
proves what it can from the deployment's systems of record, and records in
the audit chain what it would have done. It changes no decision until
``REMORA_WS1_MODE=enforce``, which this pilot does not set (enforce needs
flow control and evidence for IFC-04b, 06, 11, 12 and 13).

Two predicates, one verifier, two systems of record (``ot_ws1_facts.json``):

* ``sensor_on_round``, for ``read_sensor``: the sensor is one the daily
  monitoring round names. PROVED grounds the engine's two argument signals
  for the read, the same facts the state index already establishes; in
  shadow this shows whether grounding from proofs agrees with it.
* ``target_named_by_work_order``, for every write: the loop, valve, alarm or
  work order the call names is a target some signed work order names. This
  is deliberately weaker than "the work order this call is made under": the
  pilot's intent authority is the hash of the whole work-order file, not one
  order, so per-order binding is not available to the verifier. It is a
  pilot limit, recorded here, not a property of WS1. Since 2026-11-06 the
  per-order binding is enforced outside WS1: ``ot_bundle.validate_intent_scope``
  checks the call against the scope of its own work order, and the engine
  refuses a call outside it before review. This predicate is unchanged.

The verifier is synthetic and deployment-owned. Nothing it proves is a safety
claim about a plant.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from remora.decision_providers.composition_adapter import MonitorMode, MonitorProfile
from remora.verification.execution_gate import Ws1Deployment
from remora.verification.preconditions import LogicalState, ProposalContext, ResolutionClass
from remora.verification.registry import PredicateSpec, PreconditionRegistry, ResolverSpec
from remora.verification.resolvers import InMemorySource

HERE = Path(__file__).resolve().parent
FACTS_PATH = HERE / "ot_ws1_facts.json"
TENANT = "ot-pilot"

_WRITES = {"adjust_setpoint": "loop", "set_valve_position": "valve",
           "acknowledge_alarm": "alarm_id", "create_work_order": "wo_id", "close_work_order": "wo_id"}

REGISTRY = PreconditionRegistry(
    tools={
        "read_sensor": (PredicateSpec("sensor_on_round", ResolutionClass.MACHINE,
                                      "ot-facts", ("round",), "sensor_id"),),
        **{tool: (PredicateSpec("target_named_by_work_order", ResolutionClass.MACHINE,
                                "ot-facts", ("work_orders",), subject),)
           for tool, subject in _WRITES.items()},
    },
    resolvers={
        "round": ResolverSpec("round", "monitoring-round", frozenset({"sensor_on_round"}),
                              "resolve:round"),
        "work_orders": ResolverSpec("work_orders", "work-order-system",
                                    frozenset({"target_named_by_work_order"}), "resolve:work_orders"),
    })

#: No learned monitor runs in the pilot. SHADOW declares that: the composer
#: records the monitor as not requested and caps nothing on it.
PROFILE = MonitorProfile(profile_id="ot-pilot-no-monitor", mode=MonitorMode.SHADOW,
                         model_id="no-monitor-0.0.0", question_set_hash="0" * 64,
                         thresholds={"injection": 0.5}, language="en")


class FactsVerifier:
    verifier_id, version = "ot-facts", "1.0.0"

    def verify(self, pre: Any, payload: Any, ctx: ProposalContext) -> tuple[LogicalState, str]:
        if not payload.get("found"):
            return LogicalState.UNKNOWN, "not_in_system_of_record"
        record = payload.get("record") or {}
        if record.get("tenant") != ctx.tenant_id:
            return LogicalState.REFUTED, "another_tenant"
        return LogicalState.PROVED, str(record.get("fact") or "named")


def _records() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    round_records = {sensor: {"tenant": TENANT, "fact": "sensor_on_round", "round": round_id}
                     for round_id, sensors in facts["monitoring_rounds"].items() for sensor in sensors}
    wo_records = {target: {"tenant": TENANT, "fact": "target_named_by_work_order", "work_order": wo}
                  for wo, targets in facts["work_order_targets"].items() for target in targets}
    return {TENANT: round_records}, {TENANT: wo_records}


def build_ws1_deployment() -> Ws1Deployment:
    round_records, wo_records = _records()
    return Ws1Deployment(
        registry=REGISTRY,
        verifiers={"ot-facts": FactsVerifier()},
        resolvers={"round": InMemorySource("round", "monitoring-round", round_records),
                   "work_orders": InMemorySource("work_orders", "work-order-system", wo_records)},
        monitor_profile=PROFILE,
        resolve_capabilities=lambda tenant, principal: frozenset({"resolve:round", "resolve:work_orders"}),
        clock_ms=lambda: time.time_ns() // 1_000_000,
        # Grounding from proofs (§94): a PROVED sensor_on_round establishes the
        # engine's two argument signals for the read. Nothing is declared for
        # tool_matches_goal or expected_effect_matches; those come from the
        # semantic bundle. In shadow this is recorded, not applied.
        grounding={"sensor_on_round": ("argument_values_supported", "argument_values_grounded")},
    )
