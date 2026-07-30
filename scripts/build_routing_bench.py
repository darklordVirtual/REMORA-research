# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Build the routing benchmark from pinned upstream sources.

Derived episodes are written to ``data/routing_bench_v1/`` with a manifest
pinning the upstream commit, license, and per-file SHA-256, plus the route
table version and content hash. Output is deterministic: sorted keys, LF
endings, no timestamps.

Sources whose license forbids redistributing derived data (ToolSandbox) are
marked ``redistributable: false`` and written to the gitignored local cache
instead. Nothing non-redistributable ever reaches ``data/``.

Usage:
    python scripts/build_routing_bench.py            # build and write
    python scripts/build_routing_bench.py --verify   # check hashes, no network
    python scripts/build_routing_bench.py --fetch    # refresh the source cache

Exit codes: 0 = success, 1 = source cache missing, 2 = verification failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.toolcall.routing.episode import RoutingEpisode  # noqa: E402
from remora.toolcall.routing.leakage import check_all  # noqa: E402
from remora.toolcall.routing.route_table import (  # noqa: E402
    ROUTE_TABLE_VERSION,
    readable_table,
    table_content_hash,
)
from remora.toolcall.routing.sources.agentdojo import AgentDojoAdapter  # noqa: E402
from remora.toolcall.routing.sources.tau2 import (  # noqa: E402
    REFUSAL_PATTERN_VERSION,
    Tau2Adapter,
)
from remora.toolcall.routing.sources.toolsandbox import ToolSandboxAdapter  # noqa: E402

CACHE = REPO_ROOT / ".cache" / "routing_bench"
OUT = REPO_ROOT / "data" / "routing_bench_v1"
#: Non-redistributable episodes never leave the gitignored cache.
LOCAL_OUT = CACHE / "local"

AGENTDOJO_COMMIT = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"
AGENTDOJO_SUITES = ("banking", "slack", "travel", "workspace")

TAU2_COMMIT = "363133ada1936491fb5bcec33cd62c3518a99f65"
TAU2_FILES = [
    ("airline", "tasks.json"),
    ("airline", "policy.md"),
    ("retail", "tasks.json"),
    ("retail", "policy.md"),
    ("telecom", "tasks_small.json"),
    ("telecom", "main_policy.md"),
]

SOURCES: dict[str, dict[str, Any]] = {
    "tau2": {
        "repo": "https://github.com/sierra-research/tau2-bench",
        "commit": TAU2_COMMIT,
        "license": "MIT",
        "attribution": (
            "tau2-bench, (c) Sierra Research. MIT for upstream benchmark "
            "data only; REMORA itself is BUSL-1.1."
        ),
        "redistributable": True,
    },
    "agentdojo": {
        "repo": "https://github.com/ethz-spylab/agentdojo",
        "commit": AGENTDOJO_COMMIT,
        "license": "MIT",
        "attribution": (
            "AgentDojo, (c) ETH Zurich SPY Lab. MIT for upstream benchmark "
            "data only; REMORA itself is BUSL-1.1."
        ),
        "redistributable": True,
    },
    "toolsandbox": {
        "repo": "https://github.com/apple/ToolSandbox",
        "commit": "main",
        "license": "Apple proprietary (not OSI)",
        "attribution": (
            "ToolSandbox, (c) Apple Inc. Not redistributable: derived episodes "
            "are built locally and never committed."
        ),
        "redistributable": False,
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_agentdojo() -> None:
    base = (
        "https://raw.githubusercontent.com/ethz-spylab/agentdojo/"
        f"{AGENTDOJO_COMMIT}/src/agentdojo/default_suites/v1"
    )
    root = CACHE / "agentdojo"
    for suite in AGENTDOJO_SUITES:
        target = root / suite
        target.mkdir(parents=True, exist_ok=True)
        for name in ("user_tasks.py", "injection_tasks.py"):
            req = urllib.request.Request(
                f"{base}/{suite}/{name}", headers={"User-Agent": "remora-routing-bench"}
            )
            data = urllib.request.urlopen(req, timeout=120).read()
            (target / name).write_bytes(data)
            print(f"  fetched {suite}/{name}  {len(data)} bytes")


def fetch_toolsandbox() -> None:
    """Fetch ToolSandbox sources into the cache only. Never committed."""
    base = "https://raw.githubusercontent.com/apple/ToolSandbox/main"
    root = CACHE / "toolsandbox"
    root.mkdir(parents=True, exist_ok=True)
    for url, name in (
        (f"{base}/tool_sandbox/scenarios/insufficient_information_scenarios.py",
         "insufficient_information_scenarios.py"),
        (f"{base}/LICENSE", "LICENSE"),
    ):
        req = urllib.request.Request(url, headers={"User-Agent": "remora-routing-bench"})
        data = urllib.request.urlopen(req, timeout=120).read()
        (root / name).write_bytes(data)
        print(f"  fetched toolsandbox/{name}  {len(data)} bytes")


def fetch_tau2() -> None:
    base = f"https://raw.githubusercontent.com/sierra-research/tau2-bench/{TAU2_COMMIT}/data/tau2/domains"
    root = CACHE / "tau2"
    for domain, name in TAU2_FILES:
        target = root / domain
        target.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            f"{base}/{domain}/{name}", headers={"User-Agent": "remora-routing-bench"}
        )
        data = urllib.request.urlopen(req, timeout=120).read()
        (target / name).write_bytes(data)
        print(f"  fetched {domain}/{name}  {len(data)} bytes")


def write_jsonl(path: Path, episodes: list[RoutingEpisode]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(e.to_jsonl() + "\n" for e in episodes)
    path.write_bytes(body.encode("utf-8"))
    return _sha256(body.encode("utf-8"))


def build() -> int:
    tau2_root = CACHE / "tau2"
    if not tau2_root.exists():
        print(
            f"ERROR: source cache missing at {tau2_root}\n"
            "Run with --fetch first (requires network).",
            file=sys.stderr,
        )
        return 1

    print(readable_table())
    print()

    episodes: list[RoutingEpisode] = []
    episodes.extend(Tau2Adapter(root=tau2_root, commit=TAU2_COMMIT).build_episodes())

    agentdojo_root = CACHE / "agentdojo"
    if agentdojo_root.exists():
        episodes.extend(
            AgentDojoAdapter(root=agentdojo_root, commit=AGENTDOJO_COMMIT).build_episodes()
        )
    else:
        print("NOTE: agentdojo cache absent — untrusted-origin axis will be empty")

    # ToolSandbox is not redistributable. Its episodes are built into the
    # gitignored cache and are filtered out of data/ by the redistributable flag
    # below, so the licence posture does not depend on remembering to exclude it.
    ts_module = CACHE / "toolsandbox" / "insufficient_information_scenarios.py"
    if ts_module.exists():
        episodes.extend(
            ToolSandboxAdapter(paths=[ts_module], commit="main").build_episodes()
        )
    else:
        print("NOTE: toolsandbox cache absent — ABSTAIN axis will be empty")

    check_all(episodes)

    by_source: dict[str, int] = {}
    for episode in episodes:
        by_source[episode.source_dataset] = by_source.get(episode.source_dataset, 0) + 1
    for name, count in sorted(by_source.items()):
        print(f"{name}: {count} episodes")

    redistributable = [e for e in episodes if e.redistributable]
    local_only = [e for e in episodes if not e.redistributable]

    files: dict[str, dict[str, Any]] = {}
    for dataset in sorted({e.source_dataset for e in redistributable}):
        subset = [e for e in redistributable if e.source_dataset == dataset]
        digest = write_jsonl(OUT / f"{dataset}.jsonl", subset)
        files[f"{dataset}.jsonl"] = {"sha256": digest, "n_episodes": len(subset)}
        print(f"wrote {OUT / f'{dataset}.jsonl'}  sha256={digest[:16]}")

    if local_only:
        LOCAL_OUT.mkdir(parents=True, exist_ok=True)
        for dataset in sorted({e.source_dataset for e in local_only}):
            subset = [e for e in local_only if e.source_dataset == dataset]
            write_jsonl(LOCAL_OUT / f"{dataset}.jsonl", subset)
            print(
                f"wrote {LOCAL_OUT / f'{dataset}.jsonl'}  "
                f"({len(subset)} episodes, local-only, not committed)"
            )

    manifest = {
        "schema": "routing_bench_manifest_v1",
        "route_table_version": ROUTE_TABLE_VERSION,
        "route_table_content_hash": table_content_hash(),
        "refusal_pattern_version": REFUSAL_PATTERN_VERSION,
        "sources": SOURCES,
        "files": files,
        "local_only_sources": sorted({e.source_dataset for e in local_only}),
    }
    (OUT / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"wrote {OUT / 'manifest.json'}")
    return 0


def verify() -> int:
    manifest_path = OUT / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} missing", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest["route_table_content_hash"] != table_content_hash():
        print(
            "GATE FAIL: route table content hash differs from the manifest.\n"
            f"  manifest: {manifest['route_table_content_hash']}\n"
            f"  current:  {table_content_hash()}\n"
            "Bump ROUTE_TABLE_VERSION and rebuild.",
            file=sys.stderr,
        )
        return 2

    for name, meta in manifest["files"].items():
        path = OUT / name
        if not path.exists():
            print(f"GATE FAIL: {path} missing", file=sys.stderr)
            return 2
        actual = _sha256(path.read_bytes())
        if actual != meta["sha256"]:
            print(
                f"GATE FAIL: {name} hash mismatch\n"
                f"  manifest: {meta['sha256']}\n  actual:   {actual}",
                file=sys.stderr,
            )
            return 2
        print(f"OK {name}  sha256={actual[:16]}  n={meta['n_episodes']}")

    print("routing benchmark manifest verified")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="refresh the source cache")
    ap.add_argument("--verify", action="store_true", help="verify hashes offline")
    args = ap.parse_args()

    if args.verify:
        raise SystemExit(verify())
    if args.fetch:
        print("fetching pinned upstream sources...")
        fetch_tau2()
        fetch_agentdojo()
        fetch_toolsandbox()
    raise SystemExit(build())


if __name__ == "__main__":
    main()
