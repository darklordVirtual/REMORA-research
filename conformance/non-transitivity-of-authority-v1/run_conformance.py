# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the non-transitivity vectors against one adapter and emit a run record.

    python conformance/non-transitivity-of-authority-v1/run_conformance.py --adapter remora

Same record shape as the decision-to-effect suite: suite, adapter and runner
hashes over LF-normalized bytes, the repository commit, and one outcome per
vector. There is no aggregate score; an UNSUPPORTED vector is neither a pass
nor a failure.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from adapter import Unsupported  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def repo_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def run_vector(adapter, vector: dict, world: dict) -> str:
    adapter.reset(world)
    principal = world["principal"]
    outcome = "NO_STEPS"
    for step in vector["steps"]:
        op = step["op"]
        if op == "resolve":
            outcome = adapter.resolve(step["as"], task=step["task"])
        elif op == "delegate":
            outcome = adapter.delegate(
                step["as"], parent=step["from"], delegatee=step["delegatee"],
                tools=list(step["tools"]), transitive=bool(step.get("transitive", False)),
                extra_constraints=dict(step.get("extra_constraints") or {}))
        elif op == "authorize":
            outcome = adapter.authorize(
                step["as"], authority_set=step["set"], actor=step.get("actor", principal),
                tool=step["tool"], arguments=dict(step["arguments"]))
        elif op == "dispatch":
            outcome = adapter.dispatch(
                authority=step["authority"], authority_set=step["set"],
                actor=step.get("actor", principal), tool=step["tool"],
                arguments=dict(step["arguments"]))
        elif op == "revoke":
            outcome = adapter.revoke(step["set"])
        else:
            raise Unsupported(f"unknown op {op!r}")
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="remora")
    parser.add_argument("--out", default=str(HERE / "run-record.json"))
    args = parser.parse_args()

    suite_path = HERE / "vectors.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    adapter_path = HERE / f"adapter_{args.adapter}.py"
    adapter = importlib.import_module(f"adapter_{args.adapter}").build()

    results = []
    for vector in suite["vectors"]:
        try:
            observed = run_vector(adapter, vector, suite["world"])
            status = "MATCH" if observed == vector["expect"] else "DIVERGENT"
        except Unsupported as exc:
            observed, status = f"UNSUPPORTED: {exc}", "UNSUPPORTED"
        except Exception as exc:  # a crash is a result, not a reason to stop
            observed, status = f"ERROR: {type(exc).__name__}: {exc}", "ERROR"
        results.append({"id": vector["id"], "title": vector["title"], "form": vector["form"],
                        "expected": vector["expect"], "observed": observed, "status": status})

    record = {
        "suite": suite["suite"],
        "suite_sha256": sha256_file(suite_path),
        "adapter": adapter.name,
        "adapter_version": adapter.version,
        "adapter_sha256": sha256_file(adapter_path),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "repo_commit": repo_commit(),
        "run_kind": "author-run",
        "run_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "counts": {
            "match": sum(1 for r in results if r["status"] == "MATCH"),
            "divergent": sum(1 for r in results if r["status"] == "DIVERGENT"),
            "unsupported": sum(1 for r in results if r["status"] == "UNSUPPORTED"),
            "error": sum(1 for r in results if r["status"] == "ERROR"),
            "total": len(results),
        },
        "results": results,
    }
    Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    for r in results:
        print(f"{r['id']:<7} {r['status']:<11} expected={r['expected']} observed={r['observed']}")
    print(json.dumps(record["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
