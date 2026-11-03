#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Readiness gates G0-G6 for the sealed control-evaluation run.

Prints a table of PASS / FAIL / PENDING with reasons and exits 0 only when
every gate passes. The gates are defined in
``experiments/control_eval/readiness.py``; ``run_control_eval.py --test``
runs the same check and refuses to start unless it passes.

    python scripts/check_study_readiness.py --config <run config.json>
    python scripts/check_study_readiness.py --config <cfg> --write-harness-marker
    python scripts/check_study_readiness.py --config <cfg> --offline   # G5 without network

``--write-harness-marker`` runs the configured harness tests and records
the pass together with the hashes of the harness files (gate G2).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from experiments.control_eval import readiness  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--write-harness-marker", action="store_true")
    parser.add_argument("--offline", action="store_true",
                        help="report G5 as PENDING instead of calling the OSF API")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    r = cfg.get("readiness") or {}
    if args.write_harness_marker:
        ok = readiness.write_harness_marker(args.root, r.get("harness_files") or [],
                                            r.get("harness_tests") or [],
                                            args.root / r["harness_marker"])
        print(f"harness tests {'passed' if ok else 'FAILED'}; marker {r['harness_marker']}")
    fetch = (lambda url: (_ for _ in ()).throw(OSError("offline"))) if args.offline else None
    results = readiness.check_readiness(cfg, args.root, fetch)
    if args.offline:
        results = [readiness.GateResult(g.gate, g.title, readiness.PENDING, "offline: not checked")
                   if g.gate == "G5" and g.status == readiness.FAIL else g for g in results]
    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        print(readiness.render(results))
    return 0 if readiness.all_pass(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
