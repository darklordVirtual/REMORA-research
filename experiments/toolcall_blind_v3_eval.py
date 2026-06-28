# Author: Stian Skogbrott
# License: Apache-2.0
"""Evaluate RemoraToolCallGate on the blinded benchmark v3.

Implements REM-009: primary gate evaluation using the separated CandidateAction /
EvaluationTruth split. The gate only receives CandidateAction; labels are loaded
separately at scoring time.

This is the reference protocol for all future REMORA toolcall safety claims.

Artifact: results/toolcall_blind_v3_results.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from remora.toolcall.benchmark_blind_v3 import (
    load_candidate_actions_v3,
    load_evaluation_truths_v3,
    score_blinded_v3,
)
from remora.toolcall.remora_gate import RemoraToolCallGate
from remora.toolcall.schema import ToolCallTask

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_blind_v3_results.json"


def _to_v2_task(candidate) -> ToolCallTask:
    """Adapt CandidateActionV3 to ToolCallTask for gate compatibility.

    Provides dummy values for evaluation-only fields that the gate must not use.
    This verifies the fix is architectural: even if the gate accidentally
    reads these fields, it gets neutral values.
    """
    return ToolCallTask(
        task_id=candidate.task_id,
        domain=candidate.domain,
        user_request=candidate.user_request,
        proposed_tool_name=candidate.proposed_tool_name,
        proposed_tool_args=candidate.proposed_tool_args,
        context=candidate.context,
        severity=candidate.severity,
        tags=candidate.tags,
        ground_truth_action="EXECUTE",     # dummy neutral — gate MUST NOT use this
        is_unsafe_if_executed=False,       # dummy neutral — gate MUST NOT use this
        is_useful_if_executed=True,        # dummy neutral
        expected_failure_mode=None,        # dummy neutral
        explanation="[blinded]",           # dummy neutral
    )


def main() -> None:
    print("=== Blinded Benchmark v3 Evaluation ===")
    print("Protocol: CandidateAction to gate; EvaluationTruth loaded separately.\n")

    candidates = load_candidate_actions_v3()
    truths = load_evaluation_truths_v3()

    gate = RemoraToolCallGate()

    decisions = []
    for candidate in candidates:
        task = _to_v2_task(candidate)
        decision = gate.decide(task)
        decisions.append(decision.action)

    result = score_blinded_v3(candidates, decisions, truths)
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    result["gate"] = "RemoraToolCallGate (default)"
    result["protocol"] = (
        "Blinded evaluation: gate receives CandidateAction only. "
        "Labels loaded separately by scorer. "
        "is_unsafe_if_executed not accessible to gate (M1 fix, 2026-06-28). "
        "See benchmarks/toolcall_blind_v3/ and remora/toolcall/benchmark_blind_v3.py."
    )

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"N={result['n_tasks']} (harmful={result['n_harmful']}, benign={result['n_benign']})")
    print(f"FAR: {result['false_accept_rate']:.4f}  (false accepts: {result['false_accepts']})")
    print(f"FBR: {result['false_block_rate']:.4f}  (false blocks: {result['false_blocks']})")
    print(f"Accuracy: {result['accuracy']:.4f}")
    print(f"Leakage-free: {result['leakage_free']}")
    print(f"\nArtifact: {RESULT_PATH}")


if __name__ == "__main__":
    main()
