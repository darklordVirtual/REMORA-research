# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the decision-to-effect vectors against one adapter and emit a run record.

    python conformance/decision-to-effect-v1/run_conformance.py --adapter remora

The run record names the suite hash, the adapter hash, the repository commit and
the per-vector outcome. It is the artifact another party checks, and it is
designed so that a disagreement about a result is a disagreement about bytes
rather than about recollection.

There is no aggregate score and no pass/fail verdict for the system as a whole.
Vectors are reported individually, and an UNSUPPORTED vector is neither a pass
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
    """Hash the file's bytes with line endings normalized to LF.

    A checkout on Windows and a checkout on Linux otherwise disagree about the
    hash of an identical file, which turns a platform difference into an
    apparent conformance difference.
    """
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def repo_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def run_vector(adapter, vector: dict, base_call: dict) -> str:
    adapter.reset()
    handle = ""
    outcome = "NO_STEPS"
    for step in vector["steps"]:
        op = step["op"]
        call = dict(base_call)
        if "arguments" in step:
            call["arguments"] = step["arguments"]
        if op == "authorize":
            handle = adapter.authorize(base_call, audience=step.get("audience", "pep-a"))
            outcome = "AUTHORIZED"
        elif op == "redeem_grant":
            outcome = adapter.redeem_grant(handle, audience=step.get("audience", "pep-a"))
        elif op == "dispatch":
            outcome = adapter.dispatch(handle, call, now=step.get("now"))
        elif op == "dispatch_concurrent":
            outcome = adapter.dispatch_concurrent(handle, call, int(step["workers"]))
        elif op == "dispatch_indeterminate":
            outcome = adapter.dispatch_indeterminate(handle, call)
        elif op == "advance_clock":
            future = datetime.now(UTC).timestamp() + int(step["seconds"])
            base_call = dict(base_call)
            vector = dict(vector)
            # the clock is presented to the next dispatch, not mutated globally
            for later in vector["steps"]:
                if later["op"] == "dispatch" and "now" not in later:
                    later["now"] = datetime.fromtimestamp(future, UTC).isoformat()
            outcome = "CLOCK_ADVANCED"
        elif op == "revoke_principal":
            adapter.revoke_principal()
            outcome = "REVOKED"
        elif op == "change_toolspec":
            adapter.change_toolspec()
            outcome = "TOOLSPEC_CHANGED"
        elif op == "change_policy_bundle":
            adapter.change_policy_bundle()
            outcome = "BUNDLE_CHANGED"
        elif op == "change_runtime":
            adapter.change_runtime()
            outcome = "RUNTIME_CHANGED"
        elif op == "verify_effect":
            outcome = adapter.verify_effect(handle, step["observed"])
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
    module = importlib.import_module(f"adapter_{args.adapter}")
    adapter = module.build()

    results = []
    for vector in suite["vectors"]:
        try:
            observed = run_vector(adapter, vector, suite["call"])
            status = "MATCH" if observed == vector["expect"] else "DIVERGENT"
        except Unsupported as exc:
            observed, status = f"UNSUPPORTED: {exc}", "UNSUPPORTED"
        except Exception as exc:  # a crash is a result, not a reason to stop
            observed, status = f"ERROR: {type(exc).__name__}: {exc}", "ERROR"
        results.append({
            "id": vector["id"],
            "title": vector["title"],
            "property": vector["property"],
            "expected": vector["expect"],
            "observed": observed,
            "status": status,
        })

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
    Path(args.out).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for r in results:
        print(f"{r['id']:<6} {r['status']:<11} expected={r['expected']} observed={r['observed']}")
    print(json.dumps(record["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
