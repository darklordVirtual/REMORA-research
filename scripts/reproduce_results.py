#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regenerate every `regenerable` result and compare it with the commit (Q1.2).

Reads ``docs/assurance/results_manifest_v1.yaml``, runs each distinct
generator of a ``regenerable`` entry once, and compares every such file with
its committed version. Only the fields an entry lists under ``volatile``
(timestamps, commit hashes, host paths, wall-clock performance) are ignored;
``*`` in a volatile path matches one key at that level. Any other difference
fails, and the failure names the fields.

Entries verified by the 2026-07 deterministic round are skipped here: that
round already byte-compares them in the same CI job.

The script rewrites result files in place, so CI runs it in a throwaway
checkout and never commits. Locally, run it in a clean worktree, or
restore the files afterwards with ``git checkout -- results``.

    python scripts/reproduce_results.py            # run and compare
    python scripts/reproduce_results.py --list     # show what would run
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "assurance" / "results_manifest_v1.yaml"
#: The round byte-compares its own outputs; its entries say so this way.
ROUND_MARKER = "Deterministic reproduction round (byte-compare)"
TIMEOUT_S = 600


def _strip(obj: Any, patterns: list[list[str]]) -> Any:
    """Remove every path in ``patterns`` from ``obj``; ``*`` matches one key."""
    for parts in patterns:
        _remove(obj, parts)
    return obj


def _remove(node: Any, parts: list[str]) -> None:
    if not parts or not isinstance(node, dict):
        return
    head, rest = parts[0], parts[1:]
    keys = list(node) if head == "*" else [head] if head in node else []
    for key in keys:
        if rest:
            _remove(node[key], rest)
        else:
            node.pop(key, None)


def _diff(a: Any, b: Any, path: str = "") -> list[str]:
    if type(a) is not type(b):
        return [path or "<root>"]
    if isinstance(a, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{path}.{key}"
            out += [sub] if key not in a or key not in b else _diff(a[key], b[key], sub)
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}[len]"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [path]


def compare_entry(entry: dict, committed: Any, regenerated: Any) -> list[str]:
    """Fields that differ once the entry's declared volatile fields are removed."""
    patterns = [p.lstrip(".").split(".") for p in entry.get("volatile", [])]
    return _diff(_strip(committed, patterns), _strip(regenerated, patterns))


def _committed(path: str) -> Any:
    text = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout
    return json.loads(text)


def _entries() -> list[dict]:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return [e for e in data["results"]
            if e["class"] == "regenerable" and ROUND_MARKER not in e["verified_by"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="reproduce regenerable results")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    entries = _entries()
    generators = sorted({e["generator"] for e in entries})
    if not entries:
        # A gate that checks nothing is not evidence.
        print("[FAIL] no regenerable entries to reproduce; the manifest filter is wrong.")
        return 1
    if args.list:
        for g in generators:
            print(g)
        return 0

    failures: list[str] = []
    for gen in generators:
        cmd = shlex.split(gen)
        if cmd and cmd[0] == "python":
            cmd[0] = sys.executable
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_S)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            failures.append(f"{gen}: exit {proc.returncode}: {' | '.join(tail)}")

    for entry in entries:
        path = entry["path"]
        try:
            new = json.loads((ROOT / path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{path}: not readable after regeneration ({exc})")
            continue
        changed = compare_entry(entry, _committed(path), new)
        if changed:
            shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
            failures.append(f"{path}: {len(changed)} field(s) differ: {shown}")

    if failures:
        print("[FAIL] regenerable results no longer reproduce:")
        for f in failures:
            print(f"  - {f}")
        print("Regenerate, review the change, and update the claim or reclass the file.")
        return 1
    print(f"[PASS] {len(entries)} regenerable results reproduced by {len(generators)} generators.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
