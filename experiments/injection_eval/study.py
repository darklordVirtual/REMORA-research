# SPDX-License-Identifier: BUSL-1.1
"""Q6 run orchestration (SAP v7 §13), callable only with a locked manifest.

:func:`run_study` generates every agent's proposals, decides on M4 from
InjecAgent's labels alone, generates the U2 twins, applies every arm to the
hijacked calls, the twins and the U1 calls, writes the raw log of §15.3 and
flips the manifest to ``evaluated``. Models, transports and the upstream
evaluator are injected; the tests drive it end to end with fakes on a
hand-written checkout.

Hypothesis evaluation (H4a, H4b, S6.1 to S6.5) is not part of this module.
It is written and committed before sealing, as a separate step.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from experiments.injection_eval import agent as gen
from experiments.injection_eval.arms import ArmDecision, GateInput, apply_arms
from experiments.injection_eval.builder import (
    attacked_cases,
    intent_ref,
    u1_calls,
    u2_twin_prompts,
    upstream_tool_dict,
)
from experiments.injection_eval.upstream import Upstream
from experiments.sap_v7_addenda.budget import ModelClient
from experiments.sap_v7_addenda.seal import LockedManifest, mark_evaluated, require_lock

SCHEMA = "remora/sap-v7-q6-injecagent-raw/v1"
Arm = Callable[[GateInput], ArmDecision]


def intents(root: Path, files: Mapping[str, str] | None = None) -> dict[str, str]:
    """intent_ref to instruction text, for the server's intent source (§13.3).

    Written before any agent runs: the cases' user instructions, the twins'
    instructions and the U1 instructions.
    """
    out: dict[str, str] = {}
    for case in attacked_cases(root, files):
        out[intent_ref("case", case.case_id)] = case.user_instruction
    for twin in u2_twin_prompts(root, files):
        out[intent_ref("twin", twin.attacker_case)] = twin.instruction
    for call in u1_calls(root, files):
        out[intent_ref("u1", call.call_id)] = call.instruction
    return out


def gate_inputs(generation: Sequence[Mapping[str, Any]], twins: Sequence[Mapping[str, Any]],
                root: Path, files: Mapping[str, str] | None = None) -> list[GateInput]:
    calls: list[GateInput] = []
    for rec in generation:
        for p in rec.get("proposals", ()):
            cid = f"{rec['agent']}:{rec['case_id']}:s{p['stage']}"
            calls.append(GateInput(
                call_id=cid, cluster=rec["attacker_case"], kind="hijack",
                tool_name=p["tool_name"], arguments=p["arguments"],
                intent_ref=intent_ref("case", rec["case_id"]),
                context_id=f"{rec['agent']}:{rec['case_id']}", task_id=rec["case_id"],
                untrusted_context=p["untrusted_context"]))
    for rec in twins:
        if rec.get("is_twin"):
            p = rec["proposal"]
            calls.append(GateInput(
                call_id=f"{rec['agent']}:twin:{rec['attacker_case']}", cluster=rec["attacker_case"],
                kind="twin", tool_name=p["tool_name"], arguments=p["arguments"],
                intent_ref=intent_ref("twin", rec["attacker_case"]),
                context_id=f"{rec['agent']}:twin:{rec['attacker_case']}",
                task_id=f"twin:{rec['attacker_case']}"))
    for u in u1_calls(root, files):
        calls.append(GateInput(call_id=u.call_id, cluster=u.call_id, kind="u1",
                               tool_name=u.tool_name, arguments=u.arguments,
                               intent_ref=intent_ref("u1", u.call_id), context_id=u.call_id,
                               task_id=u.call_id))
    return calls


def run_study(lock: LockedManifest, root: Path, *,
              client_for: Callable[[gen.AgentModel], ModelClient], upstream: Upstream,
              arms: Sequence[Arm], out: Path,
              files: Mapping[str, str] | None = None) -> dict[str, Any]:
    require_lock(lock, "the Q6 run")
    cases = attacked_cases(root, files)
    tool_dict = upstream_tool_dict(root)
    agents = [gen.AGENTS[k] for k in ("M1", "M2", "M3")]
    result = gen.generate(cases, agents, client_for, upstream, tool_dict, root)
    m4 = not result["budget_stop"] and gen.needs_m4(result["records"])
    if m4:
        more = gen.generate(cases, [gen.AGENTS["M4"]], client_for, upstream, tool_dict, root)
        result["records"] += more["records"]
        result["not_run"] += more["not_run"]
        result["budget_stop"] = more["budget_stop"]
        agents.append(gen.AGENTS["M4"])
    twins = []
    if not result["budget_stop"]:
        for a in agents:
            for twin in u2_twin_prompts(root, files):
                twins.append(gen.run_twin(twin, a, client_for(a), upstream, tool_dict))
    rows = apply_arms(gate_inputs(result["records"], twins, root, files), arms)
    body = {"schema": SCHEMA, "manifest": str(lock.path), "m4_run": m4,
            "hijacked_calls_before_gate": gen.hijacked_count(result["records"]),
            "generation": result["records"], "not_run": result["not_run"],
            "budget_stop": result["budget_stop"], "twins": twins, "decisions": rows}
    Path(out).write_text(json.dumps(body, indent=2, sort_keys=True, default=str) + "\n",
                         encoding="utf-8")
    mark_evaluated(lock, raw_log=str(out))
    return body
