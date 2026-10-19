# SPDX-License-Identifier: BUSL-1.1
"""Q7 run orchestration (SAP v7 §14), callable only with a locked manifest.

:func:`run_study` draws the split, reads the test side through the lock,
runs K1 over every test entry, decides on K2 from labels alone, labels every
call, applies every arm to the same contexts, adds J-τ from J's risk with
the τ recorded in the manifest, writes the raw log and flips the manifest to
``evaluated``. Models, the environment and the arms are injected.

Hypothesis evaluation (H5 to H7, S7.1 to S7.7) and the adjudication of
§14.4 are separate steps, not part of this module.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from experiments.routing_baselines import labels as lab
from experiments.routing_baselines.arms import ArmDecision, CallContext, j_tau
from experiments.routing_baselines.split import (
    Entry,
    draw_split,
    load_entries,
    structural_fields,
)
from experiments.routing_baselines.trajectory import (
    AGENTS,
    WRONG_SET_TARGET,
    Environment,
    TrajectoryAgent,
    run_entry,
)
from experiments.sap_v7_addenda.budget import BudgetExceeded, ModelClient
from experiments.sap_v7_addenda.seal import LockedManifest, mark_evaluated, require_lock

SCHEMA = "remora/sap-v7-q7-bfcl-mt-raw/v1"
Arm = Callable[[CallContext], ArmDecision]


def judge_selection(call_labels: Mapping[str, str], capacity: int, seed: int) -> tuple[list[str], float]:
    """§14.6 budget rule: every non-gold call, plus the largest seeded gold sample that fits.

    Returns the call ids J judges and the gold sampling fraction.
    """
    import random

    non_gold = sorted(c for c, label in call_labels.items() if label != lab.GOLD)
    gold = sorted(c for c, label in call_labels.items() if label == lab.GOLD)
    room = max(0, capacity - len(non_gold))
    chosen = gold if room >= len(gold) else sorted(random.Random(seed).sample(gold, room))
    fraction = (len(chosen) / len(gold)) if gold else 1.0
    return non_gold + chosen, fraction


def label_run(run: Mapping[str, Any], entry: Entry,
              catalogue: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {c["call_id"]: lab.label_call(c["tool_name"], c["arguments"],
                                         entry.ground_truth[c["turn"]], catalogue)
            for c in run["calls"]}


def primary_wrong_count(labels: Mapping[str, str], tools: Mapping[str, str],
                        write_tools: frozenset[str]) -> int:
    return sum(1 for cid, label in labels.items()
               if lab.in_primary_wrong_set(label, tools[cid], write_tools))


def _call_id(agent_key: str) -> Callable[[str, int, int, int], str]:
    def make(entry_id: str, turn: int, step: int, k: int) -> str:
        return f"{agent_key}:{entry_id}:t{turn}:s{step}:c{k}"
    return make


def run_study(lock: LockedManifest, data_root: Path, *,
              client_for: Callable[[TrajectoryAgent], ModelClient],
              env_for: Callable[[Entry], Environment],
              arms: Sequence[Arm], catalogue: Mapping[str, Mapping[str, Any]],
              owner: Mapping[str, str], write_tools: frozenset[str], out: Path,
              empty_turn_text: str | None = None,
              files: dict[str, str] | None = None) -> dict[str, Any]:
    require_lock(lock, "the Q7 run")
    split = draw_split(structural_fields(data_root))
    entries = load_entries(data_root, split, "test", lock=lock, files=files)
    runs: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    tools: dict[str, str] = {}
    budget_stop = ""
    agents_run = []
    for key in ("K1", "K2"):
        if key == "K2" and (budget_stop or primary_wrong_count(labels, tools, write_tools)
                            >= WRONG_SET_TARGET):
            break
        agent = AGENTS[key]
        agents_run.append(key)
        for entry in entries:
            if budget_stop:
                runs.append({"agent": key, "entry_id": entry.entry_id, "not_run": "budget_stop"})
                continue
            try:
                run = run_entry(entry, agent, client_for(agent), env_for(entry), catalogue,
                                owner, empty_turn_text, call_id=_call_id(key))
            except BudgetExceeded as exc:
                budget_stop = str(exc)
                runs.append({"agent": key, "entry_id": entry.entry_id, "not_run": "budget_stop"})
                continue
            run["agent"] = key
            runs.append(run)
            labels.update(label_run(run, entry, catalogue))
            tools.update({c["call_id"]: c["tool_name"] for c in run["calls"]})
    tau = lock.body.get("judge_tau")
    rows = []
    for run in runs:
        for ctx in run.get("contexts", ()):
            decisions = {}
            for arm in arms:
                d = arm(ctx)
                decisions[d.arm] = d
                if d.arm == "J" and isinstance(tau, int):
                    t = j_tau(d, tau)
                    decisions["J-tau"] = t
            label = labels[ctx.call_id]
            rows.append({"call_id": ctx.call_id, "entry_id": ctx.entry_id,
                         "cluster_task": split.cluster(ctx.entry_id), "cluster_tool": ctx.tool_name,
                         "turn": ctx.turn, "tool_name": ctx.tool_name, "arguments": ctx.arguments,
                         "label": label,
                         "primary_wrong": lab.in_primary_wrong_set(label, ctx.tool_name,
                                                                   write_tools),
                         "arms": {name: {"passed": d.passed, "decision": d.decision,
                                         "reasons": list(d.reasons), "risk": d.risk}
                                  for name, d in decisions.items()}})
    body = {"schema": SCHEMA, "manifest": str(lock.path), "split_unit": split.unit,
            "agents_run": agents_run, "budget_stop": budget_stop,
            "runs": [{k: v for k, v in r.items() if k != "contexts"} for r in runs],
            "decisions": rows}
    Path(out).write_text(json.dumps(body, indent=2, sort_keys=True, default=str) + "\n",
                         encoding="utf-8")
    mark_evaluated(lock, raw_log=str(out))
    return body
