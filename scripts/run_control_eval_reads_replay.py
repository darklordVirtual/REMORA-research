#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Development replay: how far does read autonomy reach on AgentDojo?

The OT pilot showed five legitimate monitoring reads completing without a
person once the deployment declared its tools and grounding could fire
(artifacts/ot-pilot/grounded-reads-2026-11-03/). This script asks the same
question of real tasks, with no model call and no new mechanism: every
development user task's ground-truth calls, in order, classified by the
deployment's own declaration (``agentdojo_flow_toolspecs_v1.yaml``) and by what
the engine's grounded-read path would need.

Per benign call it records: the declared action type and risk tier; whether
each arm of G1 executed it; whether its argument values are grounded in the
task text or in prior tool outputs (:func:`argument_grounding`, the check the
engine uses); and whether the deterministic intent extractor resolves the
task. Per task: whether every call is a declared read, and whether every such
read is grounded. That ceiling is what a reads-only autonomy policy with a
perfect intent source could complete. The engine's own ``tool_matches_goal``
and ``expected_effect_matches`` are reported as they come out, not asserted.

Scope: development suites only (the held-out suite is never loaded), the SAP
v7 development split, scripted ground truth. Nothing here is a sealed result.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

ARMS = ("A_none", "B_refuse_all", "E1_remora_strict", "E_IFC", "E_IFC_WS1")


def _g1():
    spec = importlib.util.spec_from_file_location(
        "run_control_eval_g1", REPO_ROOT / "scripts" / "run_control_eval_g1.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Observer:
    """A pass-through defence that records what the grounded-read path would see."""

    name = "OBS_grounding"

    def __init__(self, tools, suite: str, declarations) -> None:
        from experiments.control_eval.remora_adapter import OBSERVED, RemoraGate

        self._gate = RemoraGate(tools, OBSERVED, suite)
        self._decl = declarations
        self.rows: list[dict[str, Any]] = []

    def decide(self, call):
        from experiments.control_eval.policies import Verdict
        from remora.toolcall.routing import bfcl_semantic_bundle_v2 as bundle_v2
        from remora.toolcall.routing.compatibility import argument_grounding
        from remora.toolcall.routing.evaluate import build_full_observation

        gate = self._gate
        episode = gate.episode(call)
        intent = bundle_v2.extract_intent(call.user_task, gate._lexicon, gate._full)
        state = gate._state(call)
        obs = build_full_observation(episode, gate._registry, state,
                                     contracts=gate._bundle, intent=intent)
        grounding = argument_grounding(dict(call.args), task_text=call.user_task, state=state,
                                       domain=gate._domain,
                                       signature=gate._registry.signatures.get(call.name))
        decl = self._decl.get(call.name)
        self.rows.append({
            "suite": call.suite, "user_task": call.user_task_id, "function": call.name,
            "declared_action_type": decl.action_type if decl else None,
            "declared_risk_tier": decl.risk_tier if decl else None,
            "argument_count": len(call.args),
            "arguments_grounded": grounding.grounded,
            "ungrounded_arguments": sorted(grounding.ungrounded_arguments),
            "intent_resolved": intent is not None,
            "tool_matches_goal": obs.tool_matches_goal,
            "expected_effect_matches": obs.expected_effect_matches,
            "argument_values_supported": obs.argument_values_supported,
            "argument_values_grounded": obs.argument_values_grounded,
            "prior_outputs": len(call.prior_outputs),
            "executed": {},
        })
        return Verdict(True, 0.0, "observe", {})


def _plan(task):
    return lambda env, t=task: (list(t.ground_truth(env)), t.GROUND_TRUTH_OUTPUT)


def summarize(calls: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts over the per-call and per-task rows. Pure, so it is testable without AgentDojo."""

    def count(pred) -> int:
        return sum(1 for r in calls if pred(r))

    reads = [r for r in calls if r["declared_action_type"] == "read"]
    return {
        "dev_tasks": len(tasks), "benign_calls": len(calls),
        "declared_reads": len(reads),
        "declared_writes": count(lambda r: r["declared_action_type"] not in (None, "read")),
        "undeclared_tools": count(lambda r: r["declared_action_type"] is None),
        "reads_arguments_grounded": sum(1 for r in reads if r["arguments_grounded"] is True),
        "reads_no_judgeable_argument": sum(1 for r in reads if r["arguments_grounded"] is None),
        "reads_arguments_ungrounded": sum(1 for r in reads if r["arguments_grounded"] is False),
        "reads_intent_resolved": sum(1 for r in reads if r["intent_resolved"]),
        "reads_tool_matches_goal_true": sum(1 for r in reads if r["tool_matches_goal"] is True),
        "reads_expected_effect_matches_true": sum(1 for r in reads if r["expected_effect_matches"] is True),
        "reads_all_four_grounding_signals_true": sum(
            1 for r in reads if all(r[k] is True for k in (
                "tool_matches_goal", "expected_effect_matches",
                "argument_values_supported", "argument_values_grounded"))),
        "reads_executed_by_arm": {a: sum(1 for r in reads if r["executed"].get(a)) for a in ARMS},
        "writes_executed_by_arm": {a: count(lambda r, a=a: r["declared_action_type"] not in (None, "read")
                                            and r["executed"].get(a)) for a in ARMS},
        "tasks_reads_only": sum(1 for t in tasks if t["reads_only"]),
        "tasks_reads_only_and_grounded": sum(1 for t in tasks if t["reads_only_and_grounded"]),
        "tasks_completed_by_arm": {a: sum(1 for t in tasks if t["utility"].get(a)) for a in ARMS},
        "reads_by_suite": dict(Counter(r["suite"] for r in reads)),
        "reads_tool_mix": dict(Counter(r["function"] for r in reads).most_common()),
        "reads_ungrounded_argument_names": dict(Counter(
            a for r in reads if r["arguments_grounded"] is False for a in r["ungrounded_arguments"])),
    }


def run() -> dict[str, Any]:
    g1 = _g1()
    from agentdojo.functions_runtime import FunctionsRuntime
    from experiments.control_eval.agentdojo_glue import tool_specs
    from experiments.control_eval.metrics import inspected_user_tasks, split_tasks
    from experiments.control_eval.policies import NoGate, RefuseAll
    from experiments.control_eval.remora_adapter import STRICT, RemoraGate
    from experiments.control_eval.remora_ifc import RemoraIfcGate, load_declarations

    suites = {name: g1._suite(name) for name in g1.dev_suites()}
    split = split_tasks({n: list(s.user_tasks) for n, s in suites.items()},
                        forced_dev=inspected_user_tasks())
    dev_users = {n: parts["dev"] for n, parts in split.items()}

    calls: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for suite_name, suite in suites.items():
        tools = tool_specs(FunctionsRuntime(suite.tools))
        declarations = load_declarations(suite_name)
        arms = {"A_none": NoGate(), "B_refuse_all": RefuseAll(),
                "E1_remora_strict": RemoraGate(tools, STRICT, suite_name),
                "E_IFC": RemoraIfcGate(suite_name), "E_IFC_WS1": RemoraIfcGate(suite_name, ws1=True)}
        for tid in dev_users[suite_name]:
            task = suite.get_user_task_by_id(tid)
            observer = _Observer(tools, suite_name, declarations)
            suite.run_task_with_pipeline(
                g1._pipeline(_plan(task), observer, suite_name, tid, None, []), task, None, {})
            rows = observer.rows
            utility: dict[str, bool] = {}
            for arm_name in ARMS:
                log: list[dict[str, Any]] = []
                util, _ = suite.run_task_with_pipeline(
                    g1._pipeline(_plan(task), arms[arm_name], suite_name, tid, None, log),
                    task, None, {})
                utility[arm_name] = bool(util)
                # A blocked call ends the arm's sequence at that point for the task's
                # purposes, but the scripted agent keeps proposing, so the log keeps
                # one entry per ground-truth call in order.
                for i, entry in enumerate(log):
                    if i < len(rows):
                        rows[i]["executed"][arm_name] = bool(entry["execute"])
            reads = [r for r in rows if r["declared_action_type"] == "read"]
            tasks.append({
                "suite": suite_name, "user_task": tid, "calls": len(rows),
                "declared_reads": len(reads),
                "declared_writes": sum(1 for r in rows if r["declared_action_type"] not in (None, "read")),
                "undeclared": sum(1 for r in rows if r["declared_action_type"] is None),
                "reads_only": bool(rows) and len(reads) == len(rows),
                "reads_only_and_grounded": bool(rows) and len(reads) == len(rows)
                and all(r["arguments_grounded"] is not False for r in rows),
                "intent_resolved": bool(rows) and all(r["intent_resolved"] for r in rows),
                "utility": utility,
            })
            calls.extend(rows)

    summary = summarize(calls, tasks)
    return {
        "status": "development_replay_read_autonomy",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark_version": g1.BENCHMARK_VERSION,
        "agent": "scripted ground truth, non-adaptive, no model call",
        "model_calls": 0,
        "holdout_suite": g1.holdout_suite(),
        "dev_user_tasks": dev_users,
        "declaration": "experiments/control_eval/agentdojo_flow_toolspecs_v1.yaml",
        "arms": list(ARMS),
        "caveats": [
            "Development suites and the SAP v7 development split only; the held-out suite is never loaded.",
            "Ground-truth calls scripted by the benchmark, not an agent; no model call.",
            "tool_matches_goal and expected_effect_matches come from the deterministic lexical extractor "
            "over the task text; AgentDojo has no deployment intent source such as a work order.",
            "A reads-only task count is a ceiling for a reads-only autonomy policy, not a measured utility.",
        ],
        "summary": summary, "tasks": tasks, "calls": calls,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="write the JSON report here")
    args = parser.parse_args(argv)
    report = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
