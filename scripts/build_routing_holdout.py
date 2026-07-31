# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Build the blind held-out routing benchmark. Run once, then never again.

Why a separate script. Every one of the 72 development clusters has already
been used to develop and tune the routing signals, so any later split of them
would not be blind. This builds a holdout from tau2 telecom tasks that have
never been loaded by any development command: the development set uses
``tasks_small.json`` (20 tasks) while the full ``tasks.json`` holds 2285.

Protocol, deliberately awkward to run by accident:

1. This script writes ``data/routing_bench_holdout/``. No other build or
   evaluation script reads that directory — a test asserts it.
2. The holdout is generated once and its hash recorded. Regenerating it after
   seeing a result would silently turn it into a second development set.
3. Evaluating it requires ``scripts/run_routing_bench.py --holdout``, which
   refuses to run unless ``HOLDOUT_STATUS.md`` records the code as locked.
4. A failed holdout result is published without retuning against it.

Usage:
    python scripts/build_routing_holdout.py            # build (once)
    python scripts/build_routing_holdout.py --verify   # check hash offline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.toolcall.routing.leakage import check_all  # noqa: E402
from remora.toolcall.routing.mutations import mutate_episodes  # noqa: E402
from remora.toolcall.routing.sources.tau2 import Tau2Adapter  # noqa: E402
from remora.toolcall.routing.tool_registry import (  # noqa: E402
    ToolRegistry,
    extract_from_python,
)

CACHE = REPO_ROOT / ".cache" / "routing_bench"
DEV = REPO_ROOT / "data" / "routing_bench_v1"
OUT = REPO_ROOT / "data" / "routing_bench_holdout"

#: Number of untouched source clusters to reserve. Fixed in advance so the
#: holdout size is not chosen after seeing any result.
N_CLUSTERS = 300

TAU2_COMMIT = "363133ada1936491fb5bcec33cd62c3518a99f65"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dev_task_ids() -> set[str]:
    """Task ids already used in development, which must be excluded."""
    small = CACHE / "tau2" / "telecom" / "tasks_small.json"
    if not small.exists():
        return set()
    return {str(e["id"]) for e in json.loads(small.read_text(encoding="utf-8"))}


def build() -> int:
    source = CACHE / "tau2_holdout" / "telecom_full.json"
    if not source.exists():
        print(f"ERROR: {source} missing (fetch the full telecom task set first)",
              file=sys.stderr)
        return 1
    if (OUT / "manifest.json").exists():
        print(
            "REFUSING: a holdout manifest already exists.\n"
            "Rebuilding after any result has been seen turns the holdout into a "
            "second development set. Delete it deliberately if that is intended.",
            file=sys.stderr,
        )
        return 2

    tasks = json.loads(source.read_text(encoding="utf-8"))
    used = _dev_task_ids()
    untouched = [t for t in tasks if str(t["id"]) not in used]
    # Deterministic selection by sorted id — no sampling seed to record, and no
    # opportunity to pick a favourable subset.
    selected = sorted(untouched, key=lambda t: str(t["id"]))[:N_CLUSTERS]
    print(f"telecom: {len(tasks)} total, {len(used)} used in development, "
          f"{len(untouched)} untouched, {len(selected)} reserved")

    staging = OUT / "_source"
    (staging / "telecom").mkdir(parents=True, exist_ok=True)
    (staging / "telecom" / "tasks.json").write_text(
        json.dumps(selected, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )

    base = Tau2Adapter(root=staging, commit=TAU2_COMMIT).build_episodes()
    tool_paths = [
        q for root in (CACHE / "toolsandbox" / "tools", CACHE / "tau2_tools")
        if root.exists() for q in sorted(root.glob("*.py"))
    ]
    registry = ToolRegistry(extract_from_python(tool_paths) if tool_paths else {})
    mutants = mutate_episodes(base, registry)
    check_all(mutants)

    body = "".join(e.to_jsonl() + "\n" for e in mutants)
    (OUT / "telecom_holdout.jsonl").write_bytes(body.encode("utf-8"))
    digest = _sha256(body.encode("utf-8"))

    labelled = sum(1 for e in mutants if e.route is not None)
    manifest = {
        "schema": "routing_bench_holdout_v1",
        "status": "sealed_never_run",
        "source": "tau2 telecom tasks.json, excluding every task in tasks_small.json",
        "source_commit": TAU2_COMMIT,
        "n_source_clusters": len(selected),
        "n_episodes": len(mutants),
        "n_labelled": labelled,
        "sha256": digest,
        "files": {"telecom_holdout.jsonl": {"sha256": digest}},
    }
    (OUT / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"wrote {OUT / 'telecom_holdout.jsonl'}  "
          f"{len(mutants)} episodes ({labelled} labelled)  sha256={digest[:16]}")
    print("SEALED. Do not evaluate until the code and acceptance criteria are locked.")
    return 0


def verify() -> int:
    manifest_path = OUT / "manifest.json"
    if not manifest_path.exists():
        print("no holdout built", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = _sha256((OUT / "telecom_holdout.jsonl").read_bytes())
    if actual != manifest["sha256"]:
        print(f"GATE FAIL: holdout hash mismatch\n  manifest: {manifest['sha256']}\n"
              f"  actual:   {actual}", file=sys.stderr)
        return 2
    print(f"holdout verified  sha256={actual[:16]}  status={manifest['status']}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    raise SystemExit(verify() if args.verify else build())


if __name__ == "__main__":
    main()
