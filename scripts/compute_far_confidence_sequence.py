#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Compute the anytime-valid FA-rate bound for REM-020 monitoring.

Reads the committed longitudinal stability artifact and emits a companion
artifact carrying a time-uniform (anytime-valid) upper confidence bound on
the cycle-level false-accept indicator rate. Unlike the Wilson intervals
reported elsewhere, this bound remains valid under REM-020's continuous
monitoring and data-dependent close date (see
remora/selective/confidence_sequence.py and
docs/theoretical_foundations_proposals_v1.md §1).

Scope note: the input artifact aggregates at ADAPT-CYCLE level
(n_cycles_analyzed cycles, each with FAR=0.0 throughout the window). The
bound below is therefore on the per-cycle "any false accept in this cycle"
indicator — NOT a per-decision FAR. This is stated in the artifact.

Usage:
    python scripts/compute_far_confidence_sequence.py
    python scripts/compute_far_confidence_sequence.py --k 0 --n 168 --alpha 0.05
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.selective.confidence_sequence import far_monitoring_report  # noqa: E402

INPUT = ROOT / "results" / "longitudinal_stability_v1.json"
OUTPUT = ROOT / "results" / "far_confidence_sequence_v1.json"


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=ROOT, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=None,
                        help="event count override (default: derived from input artifact)")
    parser.add_argument("--n", type=int, default=None,
                        help="trial count override (default: n_cycles_analyzed from input)")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--threshold", type=float, default=0.05,
                        help="gate threshold the bound is compared against")
    args = parser.parse_args()

    if args.k is not None and args.n is not None:
        k, n, source = args.k, args.n, "cli_override"
    else:
        if not INPUT.exists():
            print(f"[FAIL] missing input artifact: {INPUT}")
            return 1
        data = json.loads(INPUT.read_text(encoding="utf-8"))
        n = int(data["n_cycles_analyzed"])
        if float(data.get("far_max", 1.0)) != 0.0:
            print("[FAIL] far_max != 0.0 in input artifact — derive k explicitly "
                  "with --k/--n instead of assuming zero events.")
            return 1
        k = 0
        source = str(INPUT.relative_to(ROOT))

    report = far_monitoring_report(k, n, alpha=args.alpha, threshold=args.threshold)
    artifact = {
        "schema": "far_confidence_sequence_v1",
        "unit_of_analysis": (
            "adapt-cycle level: indicator 'any false accept occurred in this "
            "cycle'. NOT a per-decision FAR bound; per-decision counts are "
            "not aggregated in the input artifact."
        ),
        "input_artifact": source,
        "gate": "REM-020 (supplementary anytime-valid bound)",
        **report,
        "provenance": {
            "script": "scripts/compute_far_confidence_sequence.py",
            "git_commit": _git_commit(),
            "input_sha_note": "input is manifest-tracked; see artifact_manifest_v1.md",
        },
    }
    OUTPUT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] wrote {OUTPUT.relative_to(ROOT)}")
    print(f"     k={k}, n={n}, alpha={args.alpha} → "
          f"time-uniform upper bound = {report['time_uniform_upper_bound']:.4f} "
          f"(below threshold {args.threshold}: {report['upper_bound_below_threshold']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
