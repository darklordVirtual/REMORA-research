#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reproduce the bounded REMORA runtime artifact; --check fails on drift."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from remora.toolcall.surface_evaluation import evaluate_reference


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "artifacts/runtime_surface/reference_runtime_v1.json"
    rendered = json.dumps(evaluate_reference(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != rendered:
            print("Runtime surface artifact differs; reproduce and review the change.")
            return 1
        print("Runtime surface artifact reproduced.")
    else:
        path.write_text(rendered, encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
