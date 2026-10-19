#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 Q6 runner: InjecAgent through /v1/execution/assess (§13, PRF-042).

Modes:

``--verify-upstream PATH``
    Check an InjecAgent checkout against the §13.2 pins (data files) and the
    two upstream code files the harness loads. Hashes only; no model call.
``--run --injecagent PATH``
    The sealed run. Refused unless ``data/injection_injecagent_v1/manifest.json``
    exists with status ``locked_never_run`` and every recorded hash matches
    (§15.1), and refused for ever once the status is ``evaluated``.

No manifest exists. Owner approval of §12 to §15, the registry, the
strict-profile deployment for arm R and the pilot are open (§15.5), so
``--run`` refuses today.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from experiments.injection_eval import pins, upstream  # noqa: E402
from experiments.sap_v7_addenda.seal import RunRefused, open_locked_manifest  # noqa: E402

MANIFEST = REPO_ROOT / "data" / "injection_injecagent_v1" / "manifest.json"
REGISTRY = "data/injection_injecagent_v1/registry.json"
#: Repository files the run depends on; each must be hashed in the manifest.
REQUIRED_FILES = (
    "docs/assurance/statistical_analysis_plan_v7_control_eval.md",
    "scripts/run_injection_eval.py",
    "experiments/control_eval/metrics.py",
    "experiments/sap_v7_addenda/seal.py",
    "experiments/sap_v7_addenda/budget.py",
    "experiments/sap_v7_addenda/registry.py",
    "experiments/injection_eval/pins.py",
    "experiments/injection_eval/builder.py",
    "experiments/injection_eval/upstream.py",
    "experiments/injection_eval/agent.py",
    "experiments/injection_eval/arms.py",
    "experiments/injection_eval/study.py",
    "experiments/injection_eval/prompts/registry_labeller_v1.txt",
    REGISTRY,
)


def verify_upstream(path: Path) -> int:
    bad = pins.mismatches(path)
    import hashlib
    for rel, expected in sorted(upstream.CODE_FILES.items()):
        target = path / rel
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            bad.append(rel)
    if bad:
        print(f"MISMATCH against InjecAgent {pins.COMMIT[:8]}: {bad}", file=sys.stderr)
        return 1
    print(f"InjecAgent checkout matches {pins.COMMIT} ({len(pins.FILES)} data files, "
          f"{len(upstream.CODE_FILES)} code files).")
    return 0


def run(injecagent: Path, manifest: Path = MANIFEST) -> int:
    try:
        open_locked_manifest(manifest, REPO_ROOT, REQUIRED_FILES)
    except RunRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    # The gate passed. The strict-profile deployment of arm R (§13.3, §15.5
    # item 4) and the provider clients are configured at seal time; until a
    # sealing PR adds them, the run stops here rather than improvise them.
    print("REFUSING: the gate passed, but this PR ships no deployment for arm R or provider "
          "clients; the sealing PR wires them to experiments.injection_eval.study.run_study.",
          file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-upstream", type=Path, metavar="PATH")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--injecagent", type=Path, help="InjecAgent checkout for --run")
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.verify_upstream:
        return verify_upstream(args.verify_upstream)
    if args.injecagent is None:
        parser.error("--run needs --injecagent")
    return run(args.injecagent, args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
