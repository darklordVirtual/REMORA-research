# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the AutoReview-to-Effect vectors against one adapter and emit a run record.

    python conformance/autoreview-to-effect-v1/run_benchmark.py --adapter remora
    python conformance/autoreview-to-effect-v1/run_benchmark.py --check

Each vector is reported with its outcome class, its coarse verdict and the
number of times a tool body ran. A BLOCK with a non-zero execution count is
DIVERGENT: a refusal reported after the effect happened is not a block.

The record carries no timestamp, interpreter version or commit, so ``--check``
can compare it byte-for-byte. There is no aggregate score.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from adapter import Unsupported  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run_vector(adapter: Any, vector: dict[str, Any], base_call: dict[str, Any]) -> str:
    adapter.reset()
    handle = ""
    outcome = "NO_STEPS"
    for step in vector["steps"]:
        op = step["op"]
        if op == "approve":
            handle = adapter.approve(dict(base_call))
            outcome = "APPROVED"
        elif op == "dispatch":
            call = dict(base_call)
            if "arguments" in step:
                call["arguments"] = step["arguments"]
            if "tool" in step:
                call["name"] = step["tool"]
            outcome = adapter.dispatch(handle, call, actor=step.get("actor"))
        elif op == "register_alternate_tool":
            adapter.register_alternate_tool(step["tool"])
            outcome = "ALTERNATE_REGISTERED"
        elif op == "change_policy_bundle":
            adapter.change_policy_bundle()
            outcome = "BUNDLE_CHANGED"
        elif op == "verify_effect":
            if outcome != "EXECUTED":
                return f"NOT_EXECUTED_BEFORE_VERIFY:{outcome}"
            outcome = adapter.verify_effect(handle, step["observed"], claimed=step["claimed"])
        else:
            raise Unsupported(f"unknown op {op!r}")
    return outcome


def build_record(adapter_name: str) -> dict[str, Any]:
    suite_path = HERE / "vectors.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    module = importlib.import_module(f"adapter_{adapter_name}")
    adapter = module.build()

    results = []
    for vector in suite["vectors"]:
        executions: int | None = None
        try:
            observed = run_vector(adapter, vector, suite["call"])
            executions = adapter.executions()
            verdict = suite["verdict_of_class"].get(observed, "UNCLASSIFIED")
            status = (
                "MATCH"
                if observed == vector["expect"] and executions == vector["executions"]
                else "DIVERGENT"
            )
        except Unsupported as exc:
            observed, verdict, status = f"UNSUPPORTED: {exc}", "UNSUPPORTED", "UNSUPPORTED"
        except Exception as exc:  # a crash is a result, not a reason to stop
            observed, verdict, status = f"ERROR: {type(exc).__name__}: {exc}", "ERROR", "ERROR"
        results.append({
            "id": vector["id"],
            "title": vector["title"],
            "property": vector["property"],
            "expected": vector["expect"],
            "expected_verdict": vector["expect_verdict"],
            "expected_executions": vector["executions"],
            "observed": observed,
            "verdict": verdict,
            "executions": executions,
            "status": status,
        })

    return {
        "suite": suite["suite"],
        "suite_sha256": sha256_file(suite_path),
        "adapter": adapter.name,
        "adapter_version": adapter.version,
        "adapter_sha256": sha256_file(HERE / f"adapter_{adapter_name}.py"),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "run_kind": "author-run",
        "counts": {
            s.lower(): sum(1 for r in results if r["status"] == s)
            for s in ("MATCH", "DIVERGENT", "UNSUPPORTED", "ERROR")
        } | {"total": len(results)},
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="remora")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    record = build_record(args.adapter)
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    committed = HERE / "run-record.json"
    if args.check:
        if not committed.exists() or committed.read_text(encoding="utf-8") != rendered:
            print("run-record.json is stale; regenerate with --out", file=sys.stderr)
            return 1
        print("run-record.json reproduces")
        return 0
    (args.out or committed).write_text(rendered, encoding="utf-8")
    for r in record["results"]:
        print(f"{r['id']:<6} {r['status']:<11} verdict={r['verdict']:<15} "
              f"observed={r['observed']} executions={r['executions']}")
    print(json.dumps(record["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
