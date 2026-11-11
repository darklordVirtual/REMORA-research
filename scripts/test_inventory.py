#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Test inventory and environment manifest for a CI run (SDD-AS-v1 AS-003).

Two outputs, both safe to publish as CI artifacts:

* the test inventory: the sorted node ids that ``pytest --collect-only``
  reports, with a SHA-256 over the canonical newline-joined list. Two
  collections of the same commit on the same Python must give the same hash;
  if they do not, the suite is not collected deterministically (a random or
  time-based parametrization id, an import that depends on the machine).
* the environment manifest: Python version and implementation, platform,
  the installed distributions with versions, the SHA-256 of each committed
  lock file, and the git SHA. It holds no environment-variable values, no
  host or user name and no filesystem path.

Usage::

    python scripts/test_inventory.py collect --inventory test-inventory.json \
        --manifest environment-manifest.json
    python scripts/test_inventory.py compare a/test-inventory.json b/test-inventory.json

``compare`` recomputes each hash from the listed node ids rather than
trusting the stored one, prints the symmetric difference and exits 1 when
the inventories differ.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1

# Same marker expression as `addopts` in pyproject.toml (a test pins this).
# addopts is cleared for the collection because its -v changes the output
# shape that parse_collect_output reads.
MARKER_EXPRESSION = "not live and not live_replay_heavy and not slow_replay"

LOCK_FILES = (
    "requirements-lock.txt",
    "requirements-federation.lock",
    "requirements-federation-bootstrap.lock",
)


def parse_collect_output(text: str) -> list[str]:
    """Node ids from ``pytest --collect-only -q`` output, sorted.

    A node id is a line with a ``::`` and no leading whitespace. The count
    line, blank lines and warnings are not node ids.
    """
    ids = [
        line.rstrip()
        for line in text.splitlines()
        if "::" in line and not line[:1].isspace() and not line.startswith(("=", "-", "!"))
    ]
    return sorted(ids)


def inventory_hash(node_ids: list[str]) -> str:
    """SHA-256 over the sorted, newline-joined node ids."""
    canonical = "\n".join(sorted(node_ids)) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_inventory(node_ids: list[str]) -> dict:
    ordered = sorted(node_ids)
    return {
        "schema": SCHEMA,
        "count": len(ordered),
        "sha256": inventory_hash(ordered),
        "node_ids": ordered,
    }


def _file_sha256(path: Path) -> str:
    # Line endings normalised so a CRLF checkout hashes like an LF one.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _git_sha(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and len(sha) == 40 else None


def installed_distributions() -> dict[str, str]:
    dists: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            dists[name.lower().replace("_", "-")] = dist.version
    return dict(sorted(dists.items()))


def build_manifest(root: Path = ROOT) -> dict:
    locks = {
        name: _file_sha256(root / name) for name in LOCK_FILES if (root / name).is_file()
    }
    return {
        "schema": SCHEMA,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "lock_files_sha256": locks,
        "git_sha": _git_sha(root),
        "distributions": installed_distributions(),
    }


def collect_node_ids(root: Path = ROOT) -> list[str]:
    cmd = [
        sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
        "-o", "addopts=", "-m", MARKER_EXPRESSION, "-p", "no:cacheprovider",
    ]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-4000:])
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit(f"pytest --collect-only failed with exit code {proc.returncode}")
    ids = parse_collect_output(proc.stdout)
    if not ids:
        raise SystemExit("pytest --collect-only produced no node ids")
    return ids


def _recomputed(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted(data["node_ids"])


def compare(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
    """Node ids only in ``a`` and only in ``b``. Duplicates count."""
    from collections import Counter

    ca, cb = Counter(a), Counter(b)
    only_a = sorted((ca - cb).elements())
    only_b = sorted((cb - ca).elements())
    return only_a, only_b


def _cmd_collect(args: argparse.Namespace) -> int:
    ids = collect_node_ids()
    inv = build_inventory(ids)
    for out in (args.inventory, args.manifest):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.inventory).write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    Path(args.manifest).write_text(
        json.dumps(build_manifest(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"test inventory: {inv['count']} node ids, sha256 {inv['sha256']}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    a, b = _recomputed(Path(args.a)), _recomputed(Path(args.b))
    ha, hb = inventory_hash(a), inventory_hash(b)
    print(f"{args.a}: {len(a)} node ids, sha256 {ha}")
    print(f"{args.b}: {len(b)} node ids, sha256 {hb}")
    if ha == hb:
        print("test inventories are identical")
        return 0
    only_a, only_b = compare(a, b)
    print(f"test inventories DIFFER: {len(only_a)} only in first, {len(only_b)} only in second")
    for label, items in (("only in first", only_a), ("only in second", only_b)):
        for item in items[:50]:
            print(f"  {label}: {item}")
        if len(items) > 50:
            print(f"  {label}: ... and {len(items) - 50} more")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="write the inventory and the environment manifest")
    c.add_argument("--inventory", required=True)
    c.add_argument("--manifest", required=True)
    c.set_defaults(func=_cmd_collect)
    d = sub.add_parser("compare", help="fail when two inventories differ")
    d.add_argument("a")
    d.add_argument("b")
    d.set_defaults(func=_cmd_compare)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
