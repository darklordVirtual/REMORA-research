#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate toolcall_blind_v3 benchmark with separated evaluator truth.

Implements intern_forbedring.txt §3 (REM-009): 'Rebuild tool-call evaluation
as a blinded harness with separated evaluator truth.'

Reads toolcall_benchmark_v2.json and splits each task into:
  benchmarks/toolcall_blind_v3/tasks.json   — CandidateAction (runtime-safe)
  benchmarks/toolcall_blind_v3/labels.json  — EvaluationTruth (evaluator-only)

Policy gates must only receive tasks.json. Labels loaded separately at scoring
time. The split enforces the import boundary documented in remora/toolcall/schema_v3_blind.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_ARTIFACT = REPO_ROOT / "artifacts" / "toolcall_benchmark_v2.json"
OUT_DIR = REPO_ROOT / "benchmarks" / "toolcall_blind_v3"

CANDIDATE_FIELDS = frozenset({
    "task_id", "domain", "user_request", "proposed_tool_name",
    "proposed_tool_args", "context", "severity", "tags",
})

TRUTH_FIELDS = frozenset({
    "task_id",
    "ground_truth_action",
    "is_unsafe_if_executed",
    "is_useful_if_executed",
    "expected_failure_mode",
    "explanation",
})

# Fields known to exist in v2 tasks (ToolCallTask) that are NOT in either set
# (name, is_mutating, etc.). These go into CandidateAction as well.
EXTRA_CANDIDATE_FIELDS = frozenset({"name", "is_mutating"})


def split_task(task: dict) -> tuple[dict, dict]:
    """Split a v2 task into (CandidateAction, EvaluationTruth)."""
    candidate = {k: v for k, v in task.items()
                 if k in CANDIDATE_FIELDS or k in EXTRA_CANDIDATE_FIELDS}
    truth = {k: v for k, v in task.items() if k in TRUTH_FIELDS}

    # Sanity: task_id in both
    assert "task_id" in candidate and "task_id" in truth, f"missing task_id: {task}"

    # Verify no label fields leaked into candidate
    label_fields = {"ground_truth_action", "is_unsafe_if_executed",
                    "is_useful_if_executed", "expected_failure_mode", "explanation"}
    leaked = label_fields & set(candidate.keys())
    assert not leaked, f"Label fields in CandidateAction: {leaked}"

    return candidate, truth


def main() -> int:
    if not V2_ARTIFACT.exists():
        print(f"ERROR: v2 artifact not found: {V2_ARTIFACT}", file=sys.stderr)
        return 1

    raw = json.loads(V2_ARTIFACT.read_text(encoding="utf-8"))
    tasks_raw: list[dict] = raw if isinstance(raw, list) else raw.get("tasks", [])

    if not tasks_raw:
        print("ERROR: no tasks found in v2 artifact", file=sys.stderr)
        return 1

    candidates = []
    truths = []

    for task in tasks_raw:
        candidate, truth = split_task(task)
        candidates.append(candidate)
        truths.append(truth)

    # Validate: all task_ids unique
    ids = [c["task_id"] for c in candidates]
    assert len(ids) == len(set(ids)), "Duplicate task_ids in v2 benchmark"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tasks_out = OUT_DIR / "tasks.json"
    labels_out = OUT_DIR / "labels.json"

    tasks_out.write_text(
        json.dumps({
            "schema_version": "v3_blind_1",
            "description": (
                "CandidateAction-only task definitions for toolcall_blind_v3. "
                "No evaluation labels. Evaluator truth is in labels.json (separate file). "
                "Policy gates must only receive these task definitions. "
                "See remora/toolcall/benchmark_blind_v3.py for the blinded loader."
            ),
            "source": "toolcall_benchmark_v2 (split by generate_blind_benchmark_v3.py)",
            "n_tasks": len(candidates),
            "tasks": candidates,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    labels_out.write_text(
        json.dumps({
            "schema_version": "v3_blind_1",
            "description": (
                "EvaluationTruth labels for toolcall_blind_v3. "
                "EVALUATOR-ONLY: must not be loaded by policy gates or runtime code. "
                "Joined to tasks by task_id at scoring time. "
                "See remora/toolcall/benchmark_blind_v3.py for the blinded loader."
            ),
            "source": "toolcall_benchmark_v2 (split by generate_blind_benchmark_v3.py)",
            "n_tasks": len(truths),
            "labels": truths,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    n_harmful = sum(1 for t in truths if t.get("is_unsafe_if_executed"))
    n_benign = sum(1 for t in truths if not t.get("is_unsafe_if_executed"))

    print(f"[generate_blind_benchmark_v3] Generated {len(candidates)} tasks")
    print(f"  Harmful: {n_harmful}  Benign: {n_benign}")
    print(f"  Tasks -> {tasks_out}")
    print(f"  Labels -> {labels_out}")
    print("\n  Import boundary: policy gates load tasks.json ONLY.")
    print("  Scorers load labels.json at evaluation time via load_evaluation_truths_v3().")
    return 0


if __name__ == "__main__":
    sys.exit(main())
