#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 §15.5 item 5: run arm IG once on a hand-written development trace.

Runs ``invariant-ai==0.3.5`` ``LocalPolicy`` with ``ig_rules_v1.gr`` through
the harness's own :class:`~experiments.routing_baselines.arms.InvariantArm`
on ``ig_dev_trace_v1.json`` and writes ``ig_dev_check_v1.json``. No model is
called and no BFCL data is read.

Invariant is not a project dependency. Install it in a separate virtual
environment and run this file with that interpreter::

    python -m venv /tmp/igvenv && /tmp/igvenv/bin/pip install invariant-ai==0.3.5
    /tmp/igvenv/bin/python -I experiments/routing_baselines/ig_dev_check.py
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from experiments.routing_baselines.arms import (  # noqa: E402
    IG_RULES,
    CallContext,
    InvariantArm,
    load_invariant_policy,
)

TRACE = HERE / "ig_dev_trace_v1.json"
OUT = HERE / "ig_dev_check_v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run() -> dict:
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    arm = InvariantArm(load_invariant_policy(), trace["catalogue"], trace["owner"],
                       frozenset(trace["write_tools"]))
    rows = []
    for i, case in enumerate(trace["cases"]):
        ctx = CallContext(
            call_id=f"dev-case-{i}", entry_id="dev", turn=0, tool_name=case["tool_name"],
            arguments=case["arguments"], user_turns=(trace["transcript"][0]["content"],),
            transcript=tuple(trace["transcript"]),
            function_docs=tuple(trace["catalogue"].values()),
            entry_classes=tuple(trace["entry_classes"]))
        decision = arm(ctx)
        rows.append({"case": case["case"], "passed": decision.passed,
                     "violations": list(decision.reasons), "expected": case["expected"],
                     "as_expected": sorted(decision.reasons) == sorted(case["expected"])})
    return {
        "schema": "remora/sap-v7-ig-dev-check/v1",
        "purpose": "SAP v7 §15.5 item 5: invariant-ai==0.3.5 installed and run once on a "
                   "hand-written development trace. No model call, no BFCL data.",
        "invariant_ai_version": metadata.version("invariant-ai"),
        "python": platform.python_version(),
        "rules_file": str(IG_RULES.relative_to(REPO_ROOT)),
        "rules_sha256_lf": _sha(IG_RULES),
        "trace_file": str(TRACE.relative_to(REPO_ROOT)),
        "trace_sha256_lf": _sha(TRACE),
        "cases": rows,
        "all_as_expected": all(r["as_expected"] for r in rows),
    }


def main() -> int:
    body = run()
    OUT.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}; all_as_expected={body['all_as_expected']}")
    return 0 if body["all_as_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
