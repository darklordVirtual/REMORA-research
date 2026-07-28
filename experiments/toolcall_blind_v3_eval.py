# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evaluate RemoraToolCallGate on the blinded benchmark v3.

Implements REM-009: primary gate evaluation using the separated CandidateAction /
EvaluationTruth split. The gate only receives CandidateAction; labels are loaded
separately at scoring time.

Two-phase protocol (research audit P0-3, 2026-07-27): the decision phase and
the scoring phase are separable so a clean benchmark run can execute them as
distinct processes — the decide process never imports or loads labels.json:

    python experiments/toolcall_blind_v3_eval.py decide   # writes decisions.jsonl
    python experiments/toolcall_blind_v3_eval.py score    # reads decisions + labels

Running with no argument performs both phases in one process (legacy mode);
the result then honestly records decision_process.mode = "single_process".

This is the reference protocol for all future REMORA toolcall safety claims.

Artifact: results/toolcall_blind_v3_results.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from remora.toolcall.benchmark_blind_v3 import load_candidate_actions_v3
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.schema import ToolCallTask

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_blind_v3_results.json"
DECISIONS_PATH = REPO_ROOT / "results" / "toolcall_blind_v3_decisions.jsonl"


def _to_v2_task(candidate) -> ToolCallTask:
    """Adapt CandidateActionV3 to ToolCallTask for gate compatibility.

    Provides neutral values for every field the gate must not use — both the
    evaluation labels AND the author annotations (severity/tags, which are
    ground-truth adjacent; research audit P0-2). Even if the gate accidentally
    reads any of them, it gets neutral values, so the fix is architectural.
    """
    return ToolCallTask(
        task_id=candidate.task_id,
        domain=candidate.domain,
        user_request=candidate.user_request,
        proposed_tool_name=candidate.proposed_tool_name,
        proposed_tool_args=candidate.proposed_tool_args,
        context=candidate.context,
        severity="unknown",                # author annotation — neutralized
        tags=(),                           # author annotation — neutralized
        ground_truth_action="EXECUTE",     # dummy neutral — gate MUST NOT use this
        is_unsafe_if_executed=False,       # dummy neutral — gate MUST NOT use this
        is_useful_if_executed=True,        # dummy neutral
        expected_failure_mode=None,        # dummy neutral
        explanation="[blinded]",           # dummy neutral
    )


def run_decide(decisions_path: Path = DECISIONS_PATH) -> int:
    """Decision phase: candidates in, decisions out. No labels touched.

    This function (and this phase) must never import or read labels.json —
    that is the process-isolation property the two-phase protocol exists for.
    """
    candidates = load_candidate_actions_v3()
    gate = RemoraToolCallGate()

    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with open(decisions_path, "w", encoding="utf-8", newline="\n") as f:
        for candidate in candidates:
            decision = gate.decide(_to_v2_task(candidate))
            f.write(json.dumps(
                {"task_id": candidate.task_id, "decision": decision.action}
            ) + "\n")
    print(f"[decide] {len(candidates)} decisions -> {decisions_path}")
    return len(candidates)


def run_score(
    decisions_path: Path = DECISIONS_PATH,
    result_path: Path = RESULT_PATH,
    *,
    process_mode: str = "two_phase",
) -> dict:
    """Scoring phase: joins persisted decisions with labels by task_id."""
    # Labels enter the picture only here — imported locally so the decide
    # phase can run in a process where this import never happens.
    from remora.toolcall.benchmark_blind_v3 import (
        LABELS_PATH,
        TASKS_PATH,
        load_evaluation_truths_v3,
        score_blinded_v3,
    )

    candidates = load_candidate_actions_v3()
    truths = load_evaluation_truths_v3()

    by_id: dict[str, str] = {}
    with open(decisions_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                by_id[rec["task_id"]] = rec["decision"]
    decisions = [by_id[c.task_id] for c in candidates]

    result = score_blinded_v3(candidates, decisions, truths)
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    result["gate"] = "RemoraToolCallGate (default)"
    result["decision_process"] = {
        "mode": process_mode,
        "decisions_file": decisions_path.relative_to(REPO_ROOT).as_posix(),
    }
    result["protocol"] = (
        "Blinded evaluation: gate receives CandidateAction only, with author "
        "annotations (severity/tags) neutralized by the adapter. Labels are "
        "loaded only in the scoring phase and joined by task_id. "
        "is_unsafe_if_executed not accessible to gate (M1 fix, 2026-06-28). "
        "Two-phase decide/score protocol added 2026-07-27 (audit P0-3). "
        "See benchmarks/toolcall_blind_v3/ and remora/toolcall/benchmark_blind_v3.py."
    )

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    # Full provenance sidecar (research audit remedy): code, environment and
    # input binding for the artifact just written.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from result_provenance import write_sidecar
    write_sidecar(
        result_path,
        script="experiments/toolcall_blind_v3_eval.py",
        inputs={
            "tasks": TASKS_PATH,
            "labels": LABELS_PATH,
            "decisions": decisions_path,
        },
        random_seeds=None,
        command=f"python experiments/toolcall_blind_v3_eval.py ({process_mode})",
        extra={"n_samples": result["n_tasks"]},
    )

    print(f"N={result['n_tasks']} (harmful={result['n_harmful']}, benign={result['n_benign']})")
    print(f"FAR (harmful-denominator): {result['false_accept_rate']:.4f}  (false accepts: {result['false_accepts']})")
    print(f"FBR (benign-denominator):  {result['false_block_rate']:.4f}  (false blocks: {result['false_blocks']})")
    print(f"Accuracy: {result['accuracy']:.4f}")
    print(f"Leakage-free (computed): {result['leakage_free']}")
    print(f"Decision process: {process_mode}")
    print(f"\nArtifact: {result_path}")
    return result


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("=== Blinded Benchmark v3 Evaluation ===")
    if phase == "decide":
        run_decide()
    elif phase == "score":
        run_score(process_mode="two_phase")
    elif phase == "all":
        print("(single-process legacy mode; use decide/score in separate "
              "processes for the isolation the protocol is designed for)\n")
        run_decide()
        run_score(process_mode="single_process")
    else:
        raise SystemExit(f"unknown phase {phase!r}; use decide | score | all")


if __name__ == "__main__":
    main()
