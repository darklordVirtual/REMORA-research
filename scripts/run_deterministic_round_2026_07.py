# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Orchestrator for the deterministic segment of the 2026-07 clean round.

Runs the SAP v2 deterministic set (no live oracles, no API keys) in order,
fail-hard, from the tagged round commit:

  1. experiments/generate_toolcall_benchmark_v2.py   (v2 task surface)
  2. experiments/evaluate_toolcall_benchmark_v2.py
  3. experiments/toolcall_v2_significance.py
  4. experiments/toolcall_v2_calibration_blind.py
  5. experiments/toolcall_v2_failure_analysis.py
  6. experiments/toolcall_ablation_v2.py
  7. experiments/evaluate_governance_intelligence.py
  8. scripts/generate_blind_benchmark_v3.py          (v3 surface, no
     severity/tags — audit P0-2)
  9. experiments/toolcall_blind_v3_eval.py decide    (separate process,
     labels never loaded — audit P0-3)
 10. experiments/toolcall_blind_v3_eval.py score     (separate process;
     writes its own provenance sidecar)
 11. result_provenance_v3 sidecars for the artifacts of steps 2-7:
     worktree state is captured BEFORE step 1 (issue #32), the round's
     declared outputs live in ALLOWED_OUTPUTS, and the sidecars record
     pre-/post-run cleanliness plus any dirty paths beyond the declared
     outputs. Step 10's self-written sidecar opts in via the
     REMORA_PRE_RUN_WORKTREE_CLEAN / REMORA_ALLOWED_OUTPUTS env contract.

Usage: python scripts/run_deterministic_round_2026_07.py
Log:   results/deterministic_round_2026_07.log (append)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from result_provenance import capture_pre_run_state, write_sidecar  # noqa: E402

LOG = ROOT / "results" / "deterministic_round_2026_07.log"

V2_SURFACE = ROOT / "artifacts" / "toolcall_benchmark_v2.json"

# (script, [args]) in required order. Steps 9-10 are deliberately separate
# subprocess invocations of the same script: the decide process must never
# have the labels file in memory (rebenchmark_protocol_v1.md requirement 4).
STEPS: list[tuple[str, list[str]]] = [
    ("experiments/generate_toolcall_benchmark_v2.py", []),
    ("experiments/evaluate_toolcall_benchmark_v2.py", []),
    ("experiments/toolcall_v2_significance.py", []),
    ("experiments/toolcall_v2_calibration_blind.py", []),
    ("experiments/toolcall_v2_failure_analysis.py", []),
    ("experiments/toolcall_ablation_v2.py", []),
    ("experiments/evaluate_governance_intelligence.py", []),
    ("scripts/generate_blind_benchmark_v3.py", []),
    ("experiments/toolcall_blind_v3_eval.py", ["decide"]),
    ("experiments/toolcall_blind_v3_eval.py", ["score"]),
]

# artifact -> (producing script, inputs, seeds) for the sidecar pass. The
# blind v3 scorer writes its own sidecar; surfaces and *_result.json
# companions are intermediate representations of the same runs. Seeds are
# recorded only where the script actually draws random numbers
# (significance: cluster bootstrap 7/11, permutation 17/19); the other
# steps are RNG-free.
SIDECARS: dict[str, tuple[str, dict[str, Path], list[int] | None]] = {
    "results/toolcall_benchmark_v2_results.json": (
        "experiments/evaluate_toolcall_benchmark_v2.py",
        {"benchmark": V2_SURFACE},
        None,
    ),
    "results/toolcall_benchmark_v2_significance.json": (
        "experiments/toolcall_v2_significance.py",
        {"results": ROOT / "results" / "toolcall_benchmark_v2_results.json"},
        [7, 11, 17, 19],
    ),
    "results/toolcall_benchmark_v2_calibration.json": (
        "experiments/toolcall_v2_calibration_blind.py",
        {"benchmark": V2_SURFACE},
        None,
    ),
    "results/toolcall_benchmark_v2_blind_test.json": (
        "experiments/toolcall_v2_calibration_blind.py",
        {"benchmark": V2_SURFACE},
        None,
    ),
    "results/toolcall_benchmark_v2_failures.json": (
        "experiments/toolcall_v2_failure_analysis.py",
        {"results": ROOT / "results" / "toolcall_benchmark_v2_results.json"},
        None,
    ),
    "results/toolcall_benchmark_v2_ablation.json": (
        "experiments/toolcall_ablation_v2.py",
        {"benchmark": V2_SURFACE},
        None,
    ),
    "artifacts/governance_intelligence/evaluation_results.json": (
        "experiments/evaluate_governance_intelligence.py",
        # The experiment reads TASKS_FILE from benchmarks/ (its line 40); the
        # declared provenance input must match the file actually consumed
        # (external review 2026-07-29 F-06: the artifacts/ path here made the
        # fail-hard round abort in the provenance step on a clean HEAD).
        {"tasks": ROOT / "benchmarks" / "governance_intelligence" / "tasks.jsonl"},
        None,
    ),
}


def _sidecar_name(rel: str) -> str:
    """Mirror write_sidecar's naming: <artifact-stem>.provenance.json."""
    head, _, name = rel.rpartition("/")
    stem = name.rsplit(".", 1)[0]
    return (head + "/" if head else "") + stem + ".provenance.json"


# Outputs of steps not covered by the SIDECARS map: step 1 surface, step 8
# blind v3 surface, step 9 decisions, step 10 result + its self-sidecar.
# results/deterministic_round_2026_07.log and .remora_cache*.json are
# gitignored and never appear in `git status --porcelain`, so they are
# deliberately not listed. Keep this an explicit file list — no globs — so
# an undeclared new output flips post_run_worktree_clean and is noticed.
EXTRA_OUTPUTS = [
    "artifacts/toolcall_benchmark_v2.json",               # step 1
    "benchmarks/toolcall_blind_v3/tasks.json",            # step 8
    "benchmarks/toolcall_blind_v3/labels.json",           # step 8
    "results/toolcall_blind_v3_decisions.jsonl",          # step 9
    "results/toolcall_blind_v3_results.json",             # step 10
    "results/toolcall_blind_v3_results.provenance.json",  # step 10 self-sidecar
]

# Every declared output of the round, incl. the sidecars this script writes
# (each sidecar name must itself be allowed, or writing sidecar N would make
# sidecar N+1 report a dirty worktree).
ALLOWED_OUTPUTS = sorted(
    set(SIDECARS) | {_sidecar_name(a) for a in SIDECARS} | set(EXTRA_OUTPUTS)
)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    # Issue #32: worktree state must be captured BEFORE any step generates
    # output — v2's write-time flag was false for every real round. Record
    # only, never abort: enforcement lives in the promotion gate
    # (scripts/check_claim_provenance.py, issue #88), and a dishonest run
    # is worse than a dirty one.
    pre = capture_pre_run_state()
    log(f"PRE-RUN worktree_clean={pre['pre_run_worktree_clean']}")
    if pre["pre_run_dirty_paths"]:
        log("PRE-RUN dirty: " + ", ".join(pre["pre_run_dirty_paths"]))

    # Env contract so step 10's self-written sidecar (toolcall_blind_v3_eval
    # score) can opt in to result_provenance_v3 with the same pre-run state.
    env = {
        **os.environ,
        "REMORA_PRE_RUN_WORKTREE_CLEAN": (
            "1" if pre["pre_run_worktree_clean"] else "0"
        ),
        "REMORA_ALLOWED_OUTPUTS": ";".join(ALLOWED_OUTPUTS),
    }

    for script, args in STEPS:
        cmd = [sys.executable, script, *args]
        log(f"RUN {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=ROOT, env=env)
        log(f"EXIT {proc.returncode}")
        if proc.returncode != 0:
            log(f"FATAL: {script} {' '.join(args)} failed")
            return 1

    for artifact, (script, inputs, seeds) in SIDECARS.items():
        path = ROOT / artifact
        if not path.exists():
            log(f"FATAL: expected artifact missing: {artifact}")
            return 1
        # A declared input that is missing is a provenance failure, not
        # something to silently drop from the record (self-review 2026-07-28).
        missing_inputs = [k for k, v in inputs.items() if not v.exists()]
        if missing_inputs:
            log(f"FATAL: declared provenance inputs missing for {artifact}: {missing_inputs}")
            return 1
        write_sidecar(
            path,
            script=script,
            inputs=dict(inputs),
            random_seeds=seeds,
            command=f"python {script}",
            pre_run_worktree_clean=pre["pre_run_worktree_clean"],
            allowed_generated_outputs=ALLOWED_OUTPUTS,
        )
        log(f"SIDECAR {artifact}")

    log("DETERMINISTIC ROUND COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
