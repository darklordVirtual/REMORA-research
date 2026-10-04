#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Compute the RF-14 slice-1 sequential assurance receipt over a committed
per-decision episode stream.

This is the per-decision successor of scripts/compute_far_confidence_sequence.py
(CLAIM-011): instead of counting adapt cycles whose windows overlap, it reads
one resolved governance decision per line and emits a
``sequential_assurance_receipt_v1`` artifact carrying the Beta-mixture
confidence sequence, the empirical-Bernstein confidence sequence, an
e-process against the gate threshold, and the machine-checkable premise
verdict per epoch segment.

Input scope, stated plainly: ``artifacts/aromer_holdout_episodes.jsonl`` is a
synthetic replay fixture (``synthetic: true``, ``label_source:
replay_truth``). The receipt demonstrates and regression-locks the
per-decision pipeline; it is not operational telemetry and establishes no
field safety rate. The fixture predates epoch and cluster tagging, so the
epoch identity is a declared fixture label and the receipt's assumption
status is expected to be PARTIALLY_ESTABLISHED.

Group (scripts/README.md): gated. The artifact is registered `regenerable`
in docs/assurance/results_manifest_v1.yaml, so the deterministic
reproduction round re-runs this script and compares against the commit.

Usage:
    python scripts/compute_sequential_assurance.py
    python scripts/compute_sequential_assurance.py --input PATH --output PATH
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.selective.sequential_assurance import (  # noqa: E402
    AssuranceEpoch,
    SequentialAssuranceMonitor,
    outcomes_from_episode_records,
)

INPUT = ROOT / "artifacts" / "aromer_holdout_episodes.jsonl"
OUTPUT = ROOT / "results" / "sequential_assurance_receipt_v1.json"

#: The fixture carries no policy, ToolSpec or model identity. The epoch is a
#: declared label for the fixture population; a deployment passes its own.
FIXTURE_EPOCH = AssuranceEpoch(
    policy="fixture:aromer-holdout-v1",
    toolspec="fixture:untagged",
    model="fixture:untagged",
)


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
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--threshold", type=float, default=0.05,
                        help="gate threshold the e-process tests against")
    parser.add_argument("--population", default="accept",
                        help="verdict population under monitoring (default: accept)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[FAIL] missing input stream: {args.input}")
        return 1
    raw = args.input.read_bytes()
    source_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]

    monitor = SequentialAssuranceMonitor(alpha=args.alpha, threshold=args.threshold)
    monitor.observe_all(
        outcomes_from_episode_records(records, epoch=FIXTURE_EPOCH, population=args.population)
    )
    receipt = monitor.receipt(
        monitored_event="false_accept",
        population_definition=(
            f"{args.population}-verdict decisions in {args.input.relative_to(ROOT)}"
        ),
        input_description=(
            f"{args.input.relative_to(ROOT)}: synthetic replay fixture "
            "(label_source=replay_truth), one resolved episode per line; "
            "not operational telemetry"
        ),
        generated_by="scripts/compute_sequential_assurance.py",
        source_digest=source_digest,
        git_commit=_git_commit(),
    )
    artifact = receipt.to_dict()
    args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] wrote {args.output.relative_to(ROOT)}")
    for segment in artifact["segments"]:
        print(
            f"     epoch {segment['epoch_id']}: n={segment['n_resolved']}, "
            f"false_accepts={segment['false_accepts']}, "
            f"assumption_status={segment['assumption_status']}, "
            f"upper_bound={segment['upper_bound']}"
        )
    print(f"     receipt assumption_status={artifact['assumption_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
