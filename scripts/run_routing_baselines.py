#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 Q7 runner: external baselines on BFCL v4 multi-turn (§14, PRF-011).

Modes:

``--verify-upstream PATH``
    Check a gorilla ``bfcl_eval/data`` directory against the §14.2 pins.
    Hashes only; no model call.
``--split PATH``
    Draw the §14.3 split from ``involved_classes`` and ``initial_config``
    alone and print the development and test entry ids. No question text,
    ground truth or model call is touched.
``--run --data PATH``
    The sealed run. Refused unless ``data/routing_bench_bfcl_mt_v1/manifest.json``
    exists with status ``locked_never_run`` and every recorded hash matches
    (§15.1), and refused for ever once the status is ``evaluated``.

No manifest exists; ``--run`` refuses today (§15.5).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from experiments.routing_baselines import pins  # noqa: E402
from experiments.routing_baselines.split import draw_split, structural_fields  # noqa: E402
from experiments.sap_v7_addenda.seal import RunRefused, open_locked_manifest  # noqa: E402

MANIFEST = REPO_ROOT / "data" / "routing_bench_bfcl_mt_v1" / "manifest.json"
REGISTRY = "data/routing_bench_bfcl_mt_v1/registry.json"
REQUIRED_FILES = (
    "docs/assurance/statistical_analysis_plan_v7_control_eval.md",
    "scripts/run_routing_baselines.py",
    "scripts/peer_review_posthoc.py",
    "experiments/control_eval/metrics.py",
    "experiments/sap_v7_addenda/seal.py",
    "experiments/sap_v7_addenda/budget.py",
    "experiments/sap_v7_addenda/registry.py",
    "experiments/injection_eval/prompts/registry_labeller_v1.txt",
    "experiments/routing_baselines/pins.py",
    "experiments/routing_baselines/split.py",
    "experiments/routing_baselines/labels.py",
    "experiments/routing_baselines/arms.py",
    "experiments/routing_baselines/trajectory.py",
    "experiments/routing_baselines/study.py",
    "experiments/routing_baselines/prompts/judge_v1.txt",
    "experiments/routing_baselines/ig_rules_v1.gr",
    REGISTRY,
)


def verify_upstream(path: Path) -> int:
    bad = pins.mismatches(path)
    if bad:
        print(f"MISMATCH against gorilla {pins.COMMIT[:8]}: {bad}", file=sys.stderr)
        return 1
    print(f"BFCL data matches {pins.COMMIT} ({len(pins.FILES)} files).")
    return 0


def split(path: Path) -> int:
    pins.verify_data(path)
    s = draw_split(structural_fields(path))
    print(json.dumps({"unit": s.unit, "dev": sorted(s.dev), "test": sorted(s.test)}, indent=2))
    return 0


def run(data: Path, manifest: Path = MANIFEST) -> int:
    try:
        open_locked_manifest(manifest, REPO_ROOT, REQUIRED_FILES)
    except RunRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    print("REFUSING: the gate passed, but this PR ships no BFCL environment glue or provider "
          "clients; the sealing PR wires them to experiments.routing_baselines.study.run_study.",
          file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-upstream", type=Path, metavar="PATH")
    mode.add_argument("--split", type=Path, metavar="PATH")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--data", type=Path, help="bfcl_eval/data directory for --run")
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.verify_upstream:
        return verify_upstream(args.verify_upstream)
    if args.split:
        return split(args.split)
    if args.data is None:
        parser.error("--run needs --data")
    return run(args.data, args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
