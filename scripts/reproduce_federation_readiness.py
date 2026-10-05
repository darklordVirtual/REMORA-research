#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Produce a bounded, inspectable REMORA handoff run; never promote lifecycle."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TESTS = (
    "tests/test_unknown_execution_state.py",
    "tests/test_execution_outbox_reconciler.py",
    "tests/test_execution_outbox_wiring.py",
    "tests/test_effect_receipt_lineage.py",
    "tests/test_surface_reference_integration.py",
    "tests/test_interop_boundary_fixtures.py",
    "tests/test_federation_interop_contract.py",
    "tests/test_interop_result_contract.py",
    "tests/test_remora_capability_declaration.py",
    "tests/test_remora_boundary_declaration.py",
)
GATES = (
    ("scripts/check_remora_capabilities.py",),
    ("scripts/check_remora_boundaries.py",),
    ("scripts/build_remora_boundary_summary.py", "--check"),
    ("scripts/interop_package.py", "--check"),
    ("scripts/interop_author_run.py", "--check"),
    ("scripts/build_interop_matrix.py", "--check"),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _files(root: Path) -> dict[str, str]:
    paths = sorted(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("evidence must not contain symlinks")
    return {path.relative_to(root).as_posix(): _sha(path) for path in paths
            if path.is_file() and path != root / "hashes.json"}


def seal(root: Path) -> str:
    _write(root / "hashes.json", {"schema_version": 1, "algorithm": "sha256", "files": _files(root)})
    return _sha(root / "hashes.json")


def verify(root: Path, expected_manifest_sha256: str) -> bool:
    try:
        manifest_path = root / "hashes.json"
        if manifest_path.is_symlink() or _sha(manifest_path) != expected_manifest_sha256:
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return (manifest.get("schema_version") == 1 and manifest.get("algorithm") == "sha256"
                and bool(manifest.get("files")) and manifest["files"] == _files(root))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def check_junit(path: Path) -> dict[str, int]:
    suites = list(ET.parse(path).getroot().iter("testsuite"))
    counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    if counts["tests"] == 0 or any(counts[key] for key in ("failures", "errors", "skipped")):
        raise ValueError(f"test evidence is incomplete or failed: {counts}")
    return counts


def _command(args: list[str], output: Path, name: str) -> dict:
    # Keep host secrets and pytest options out of the reproducible child environment.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=300, check=False)
    (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    row = {"command": args, "returncode": result.returncode, "log": f"{name}.log"}
    if result.returncode != 0:
        raise ValueError(f"{name} failed; inspect {output / row['log']}")
    return row


def run(output: Path) -> str:
    from scripts.reproduce_runtime_surface import _git_output

    output = output.resolve()
    # Evidence inside the source tree would contaminate the recorded tree state.
    if output.is_relative_to(ROOT):
        raise ValueError("choose an output directory outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "environment.json", {
        "git_revision": _git_output("rev-parse", "HEAD"),
        "working_tree_status": _git_output("status", "--porcelain=v1", "--untracked-files=all").splitlines(),
        "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": {name: importlib.metadata.version(name)
                         for name in ("pytest", "cryptography", "jsonschema", "PyYAML")},
        "runner_sha256": _sha(Path(__file__)),
    })
    commands = []
    try:
        commands.append(_command([sys.executable, "scripts/reproduce_runtime_surface.py",
                                  "--output", str(output / "runtime")], output, "runtime"))
        commands.append(_command([sys.executable, "scripts/reproduce_custody.py",
                                  "--output", str(output / "custody.json")], output, "custody"))
        with tempfile.TemporaryDirectory(prefix="remora-handoff-tests-") as temporary:
            commands.append(_command([
                sys.executable, "-m", "pytest", *TESTS, "-q", "-o", "addopts=",
                "-p", "no:cacheprovider", f"--basetemp={temporary}",
                f"--junitxml={output / 'tests.xml'}",
            ], output, "tests"))
        counts = check_junit(output / "tests.xml")
        for index, gate in enumerate(GATES):
            commands.append(_command([sys.executable, *gate], output, f"gate-{index}"))
        _write(output / "results.json", {"status": "PASSED", "commands": commands, "tests": counts})
    except (ValueError, subprocess.TimeoutExpired) as exc:
        _write(output / "results.json", {"status": "FAILED", "commands": commands, "error": str(exc)})
        raise
    _write(output / "claim-boundary.json", {
        "establishes": "recorded local runtime cases, process custody controls and listed repository tests/gates",
        "external_reproduction": False, "independent_verification": False,
        "production_enforcement": False, "federation_adoption": False,
        "runtime_capability_surface_completeness": "NOT_ESTABLISHED",
        "full_action_digest_lineage": "NOT_ESTABLISHED",
        "does_not_establish": ["host isolation or exhaustive credential inventory",
                               "external provider behavior", "effect causation",
                               "counterpart format acceptance or owner confirmation"],
    })
    return seal(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--manifest-sha256", help="manifest digest obtained through a trusted separate channel")
    args = parser.parse_args()
    if args.verify:
        if not args.manifest_sha256:
            parser.error("--verify requires --manifest-sha256")
        ok = verify(args.verify, args.manifest_sha256)
        print("PASS: bytes match pin" if ok else "FAIL: evidence differs from pin")
        return 0 if ok else 1
    try:
        pin = run(args.output)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"handoff reproduction failed: {exc}", file=sys.stderr)
        return 1
    print(f"manifest_sha256={pin}")
    print("Pin this digest separately. Byte integrity is not external verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
