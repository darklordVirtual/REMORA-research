# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Orchestrator for the live segment of the 2026-07 clean benchmark round.

Runs the SAP v2 live chain end to end, resumably (the shared oracle cache
makes repeated ablation passes incremental, so rate-limit interruptions
just mean another pass):

  1. experiments/ablation_v2.py  (n500, cross-family trio)   [live]
  2. experiments/thermodynamic_eval.py — UNCALIBRATED primary [live, cached]
  3. experiments/end_to_end_n500_v3.py                        [offline]
  4. scripts/selective_n500_holdout.py                        [offline]
  5. provenance sidecars for the artifacts of steps 1-3
     (holdout writes its own)

Usage: python scripts/run_live_round_2026_07.py
Log:   results/live_round_2026_07.log (append)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from result_provenance import write_sidecar  # noqa: E402

ABLATION_OUT = ROOT / "results" / "ablation_v2_n500_results.json"
THERMO_OUT = ROOT / "results" / "thermodynamic_eval_n500_uncalibrated_results.json"
E2E_OUT = ROOT / "results" / "end_to_end_n500_v3.json"
LOG = ROOT / "results" / "live_round_2026_07.log"

MAX_ABLATION_PASSES = 12


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list[str]) -> int:
    log(f"RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT)
    log(f"EXIT {proc.returncode}")
    return proc.returncode


def main() -> int:
    py = sys.executable

    # 0. Preflight — trio liveness + JSON compliance (no benchmark data).
    if run([py, "scripts/preflight_groq_trio.py"]) != 0:
        log("FATAL: trio preflight failed; not starting the round")
        return 1

    # 1. Ablation — repeat until it completes (cache makes passes resumable).
    ok = False
    for attempt in range(1, MAX_ABLATION_PASSES + 1):
        log(f"ablation pass {attempt}/{MAX_ABLATION_PASSES}")
        if run([py, "experiments/ablation_v2.py",
                "--benchmark-module", "remora.benchmarks.extended_v2_n500",
                "--output", str(ABLATION_OUT)]) == 0:
            ok = True
            break
        time.sleep(60)  # let rate-limit windows reset between passes
    if not ok:
        log("FATAL: ablation did not complete")
        return 1

    # 2. Thermodynamic eval — UNCALIBRATED primary (SAP v2 calibration rule).
    if run([py, "experiments/thermodynamic_eval.py",
            "--benchmark-module", "remora.benchmarks.extended_v2_n500",
            "--results", str(ABLATION_OUT),
            "--output", str(THERMO_OUT)]) != 0:
        log("FATAL: thermodynamic eval failed")
        return 1

    # 3. Offline consumers.
    if run([py, "experiments/end_to_end_n500_v3.py"]) != 0:
        log("FATAL: end_to_end failed")
        return 1
    if run([py, "scripts/selective_n500_holdout.py"]) != 0:
        log("FATAL: holdout failed")
        return 1

    # 4. Sidecars (seed 42 is the split seed; oracle calls are temperature-
    #    sampled by the providers and cached in .remora_cache.json).
    write_sidecar(ABLATION_OUT, script="experiments/ablation_v2.py",
                  inputs={}, random_seeds=[42],
                  command="python experiments/ablation_v2.py --benchmark-module remora.benchmarks.extended_v2_n500")
    write_sidecar(THERMO_OUT, script="experiments/thermodynamic_eval.py",
                  inputs={"ablation": ABLATION_OUT}, random_seeds=None,
                  command="python experiments/thermodynamic_eval.py --benchmark-module remora.benchmarks.extended_v2_n500 (uncalibrated)")
    if E2E_OUT.exists():
        write_sidecar(E2E_OUT, script="experiments/end_to_end_n500_v3.py",
                      inputs={"thermo": THERMO_OUT}, random_seeds=None,
                      command="python experiments/end_to_end_n500_v3.py")
    log("LIVE ROUND COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
