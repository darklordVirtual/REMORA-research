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
from remora.toolcall.routing.sources.tau2 import (  # noqa: E402
    REFUSAL_PATTERN_VERSION,
    Tau2Adapter,
)

CACHE = REPO_ROOT / ".cache" / "routing_bench"
OUT = REPO_ROOT / "data" / "routing_bench_v1"

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
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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

    episodes = Tau2Adapter(root=tau2_root, commit=TAU2_COMMIT).build_episodes()
    check_all(episodes)
    print(f"tau2: {len(episodes)} episodes, {len({e.cluster_id for e in episodes})} clusters")

    redistributable = [e for e in episodes if e.redistributable]
    digest = write_jsonl(OUT / "tau2.jsonl", redistributable)

    manifest = {
        "schema": "routing_bench_manifest_v1",
        "route_table_version": ROUTE_TABLE_VERSION,
        "route_table_content_hash": table_content_hash(),
        "refusal_pattern_version": REFUSAL_PATTERN_VERSION,
        "sources": SOURCES,
        "files": {"tau2.jsonl": {"sha256": digest, "n_episodes": len(redistributable)}},
    }
    (OUT / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"wrote {OUT / 'tau2.jsonl'}  sha256={digest[:16]}")
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
    raise SystemExit(build())


if __name__ == "__main__":
    main()
