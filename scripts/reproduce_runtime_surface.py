#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run REMORA's local reference runtime and emit a bounded reproduction record.

This exercises the actual SignedSurfaceRuntime. It does not inventory an
external host, test credential isolation, or constitute an independent run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FILES = (
    "environment.json", "inputs.json", "results.json",
    "negative-controls.json", "evidence.json", "claim-boundary.json",
)
SOURCES = (
    "scripts/reproduce_runtime_surface.py",
    "remora/toolcall/surface_evaluation.py",
    "remora/toolcall/signed_surface_runtime.py",
    "remora/toolcall/runtime_surface.py",
    "remora/toolcall/surface_authority.py",
    "remora/enforcement/lease.py",
    "remora/governance/effect_verification.py",
)


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True,
        text=True, check=True,
    )
    return result.stdout.rstrip("\r\n")


def run(output: Path) -> None:
    from remora.toolcall.surface_evaluation import evaluate_reference

    result = evaluate_reference()
    cases = result["cases"]
    expected = {
        "verified": {"property": "EFFECT_VERIFIED", "runtime": "SUCCEEDED",
                     "file_written": True, "receipt": "FRESH_AND_BOUND", "rechecked": True},
        "mismatch": {"property": "EFFECT_MISMATCH", "rechecked": True},
        "unobserved": {"property": "NOT_ESTABLISHED", "rechecked": True},
        "extra_tool": {"runtime": "REFUSED", "file_written": False},
        "replacement": {"runtime": "REFUSED", "file_written": False},
        "missing_lease": {"runtime": "REFUSED", "file_written": False},
        "shadow_drift": {"surface": "MISMATCH", "runtime": "SUCCEEDED"},
        "alternate_effect_path": {"verdict": "MISMATCH"},
        "incomplete_inventory": {"verdict": "NOT_ESTABLISHED"},
    }
    for name, fields in expected.items():
        for field, wanted in fields.items():
            if cases[name][field] != wanted:
                raise ValueError(f"{name}: expected {field}={wanted}")
    if any(not row["audit_valid"] for row in cases.values() if "audit_valid" in row):
        raise ValueError("runtime audit chain is invalid")
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "environment.json", {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_revision": _git_output("rev-parse", "HEAD"),
        "working_tree_status": _git_output(
            "status", "--porcelain=v1", "--untracked-files=all"
        ).splitlines(),
        "source_sha256": {name: _sha256(ROOT / name) for name in SOURCES},
        "runtime_module": "remora.toolcall.surface_evaluation",
    })
    _write(output / "inputs.json", {
        "tool": "write", "arguments": {"value": 1},
        "target": "local-record", "tenant": "reference",
        "cases": sorted(cases),
    })
    _write(output / "results.json", result)
    _write(output / "negative-controls.json", {
        name: cases[name] for name in (
            "alternate_effect_path", "extra_tool", "incomplete_inventory",
            "mismatch", "missing_lease", "replacement", "shadow_drift",
            "unobserved",
        )
    })
    _write(output / "evidence.json", {
        "runtime_executed": True,
        "verified_effect": cases["verified"]["property"] == "EFFECT_VERIFIED",
        "audit_valid_all_dispatch_cases": all(
            row["audit_valid"] for row in cases.values() if "audit_valid" in row
        ),
        "negative_controls_refused_or_bounded": (
            cases["extra_tool"]["runtime"] == "REFUSED"
            and cases["replacement"]["runtime"] == "REFUSED"
            and cases["missing_lease"]["runtime"] == "REFUSED"
            and cases["alternate_effect_path"]["verdict"] == "MISMATCH"
            and cases["incomplete_inventory"]["verdict"] == "NOT_ESTABLISHED"
        ),
    })
    _write(output / "claim-boundary.json", {
        "establishes": "local reference runtime behavior for the recorded cases",
        "runtime_capability_surface_completeness": "NOT_ESTABLISHED",
        "external_reproduction": False,
        "production_enforcement": False,
        "does_not_establish": [
            "host-wide tool or credential inventory",
            "absence of alternative external effect paths",
            "independent observation or credential custody",
            "causation of an external effect",
        ],
    })
    _write(output / "hashes.json", {
        "algorithm": "sha256",
        "files": {name: _sha256(output / name) for name in FILES},
        "note": "Pin this manifest externally before relying on its integrity.",
    })


def verify(output: Path) -> bool:
    try:
        manifest = json.loads((output / "hashes.json").read_text(encoding="utf-8"))
        if manifest["algorithm"] != "sha256" or set(manifest["files"]) != set(FILES):
            return False
        return all(
            _sha256(output / name) == manifest["files"][name] for name in FILES
        )
    except (OSError, KeyError, TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path, help="new directory for a fresh run")
    action.add_argument("--verify", type=Path, help="check a run's file hashes")
    args = parser.parse_args()
    if args.verify is not None:
        ok = verify(args.verify)
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    try:
        run(args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"runtime reproduction failed: {exc}", file=sys.stderr)
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
