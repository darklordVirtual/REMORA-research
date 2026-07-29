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
 11. result_provenance_v2 sidecars for the artifacts of steps 2-7

Usage: python scripts/run_deterministic_round_2026_07.py
Log:   results/deterministic_round_2026_07.log (append)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from result_provenance import write_sidecar  # noqa: E402

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


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    for script, args in STEPS:
        cmd = [sys.executable, script, *args]
        log(f"RUN {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=ROOT)
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
        )
        log(f"SIDECAR {artifact}")

    log("DETERMINISTIC ROUND COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
