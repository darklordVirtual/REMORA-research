from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from remora.toolcall.baselines import MajorityVoteBaseline
from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_failures.json"
DOC_PATH = REPO_ROOT / "docs" / "failure_analysis.md"


def _serialize_task(task: Any) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "domain": task.domain,
        "severity": task.severity,
        "ground_truth_action": task.ground_truth_action,
        "expected_failure_mode": task.expected_failure_mode,
        "tags": list(task.tags),
        "scenario_family": str((task.context or {}).get("scenario_family", "unknown")),
    }


def run() -> dict[str, Any]:
    tasks = load_benchmark_v2()
    _by_id = {t.task_id: t for t in tasks}  # noqa: F841

    remora_gate = RemoraToolCallGate()
    majority = MajorityVoteBaseline()

    remora_outcomes = {t.task_id: simulate(t, remora_gate.decide(t)) for t in tasks}
    majority_outcomes = {t.task_id: simulate(t, majority.decide(t)) for t in tasks}

    remora_false_executes: list[dict[str, Any]] = []
    remora_false_blocks: list[dict[str, Any]] = []
    majority_false_executes: list[dict[str, Any]] = []
    remora_saves_vs_majority: list[dict[str, Any]] = []
    remora_harms_vs_majority: list[dict[str, Any]] = []

    for task in tasks:
        ro = remora_outcomes[task.task_id]
        mo = majority_outcomes[task.task_id]
        item = _serialize_task(task)
        item["remora_action"] = ro.decision.action
        item["majority_action"] = mo.decision.action

        if ro.false_accept:
            remora_false_executes.append(item)
        if ro.false_block:
            remora_false_blocks.append(item)
        if mo.false_accept:
            majority_false_executes.append(item)
        if mo.false_accept and not ro.false_accept:
            remora_saves_vs_majority.append(item)
        if ro.false_accept and not mo.false_accept:
            remora_harms_vs_majority.append(item)

    def family_counts(items: list[dict[str, Any]]) -> dict[str, int]:
        return dict(sorted(Counter(str(i.get("scenario_family", "unknown")) for i in items).items()))

    result = {
        "benchmark": "toolcall_benchmark_v2",
        "n_tasks": len(tasks),
        "remora_false_executes": remora_false_executes,
        "remora_false_blocks": remora_false_blocks,
        "majority_false_executes": majority_false_executes,
        "remora_saves_vs_majority": remora_saves_vs_majority,
        "remora_harms_vs_majority": remora_harms_vs_majority,
        "summary": {
            "remora_false_execute_count": len(remora_false_executes),
            "remora_false_block_count": len(remora_false_blocks),
            "majority_false_execute_count": len(majority_false_executes),
            "remora_saves_vs_majority_count": len(remora_saves_vs_majority),
            "remora_harms_vs_majority_count": len(remora_harms_vs_majority),
        },
        "family_breakdown": {
            "remora_false_executes": family_counts(remora_false_executes),
            "remora_false_blocks": family_counts(remora_false_blocks),
            "majority_false_executes": family_counts(majority_false_executes),
            "remora_saves_vs_majority": family_counts(remora_saves_vs_majority),
            "remora_harms_vs_majority": family_counts(remora_harms_vs_majority),
        },
        "example_task_ids": {
            "remora_saves_vs_majority": [item["task_id"] for item in remora_saves_vs_majority[:15]],
            "majority_false_executes": [item["task_id"] for item in majority_false_executes[:15]],
        },
        "limitations": [
            "Failure analysis is deterministic and benchmark-scoped.",
            "Majority comparator uses heuristic pseudo-oracles, not live model ensemble outputs.",
        ],
    }
    return result


def write_markdown(result: dict[str, Any]) -> str:
    s = result["summary"]
    fb = result["family_breakdown"]
    lines = [
        "# REMORA Tool-Call v2 Failure Analysis",
        "",
        f"Tasks analyzed: {result['n_tasks']}",
        "",
        "## Headline counts",
        "",
        f"- REMORA false execute count: {s['remora_false_execute_count']}",
        f"- REMORA false block count: {s['remora_false_block_count']}",
        f"- Majority false execute count: {s['majority_false_execute_count']}",
        f"- REMORA saves vs majority: {s['remora_saves_vs_majority_count']}",
        f"- REMORA harms vs majority: {s['remora_harms_vs_majority_count']}",
        "",
        "## Scenario-family breakdown",
        "",
        f"- REMORA false executes: {fb['remora_false_executes']}",
        f"- REMORA false blocks: {fb['remora_false_blocks']}",
        f"- Majority false executes: {fb['majority_false_executes']}",
        f"- REMORA saves vs majority: {fb['remora_saves_vs_majority']}",
        f"- REMORA harms vs majority: {fb['remora_harms_vs_majority']}",
        "",
        "## Notes",
        "",
        "- `remora_false_executes` are tasks where REMORA predicted `EXECUTE` while ground truth was not `EXECUTE`.",
        "- `remora_false_blocks` are useful-safe `EXECUTE` tasks that REMORA blocked.",
        "- `remora_saves_vs_majority` are majority false executes prevented by REMORA.",
        "",
        "See `results/toolcall_benchmark_v2_failures.json` for per-task records.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    result = run()
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    DOC_PATH.write_text(write_markdown(result), encoding="utf-8")
    print(f"Wrote {RESULT_PATH}")
    print(f"Wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
