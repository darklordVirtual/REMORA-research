#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Python dependency vulnerability gate with an explicit committed baseline.

Runs ``pip-audit`` over the installed environment (CI installs exactly the
locked dependency set first) and compares the found vulnerability IDs against
``.github/pip_audit_baseline.json``:

- a vulnerability NOT in the baseline fails the job (new exposure);
- baseline entries no longer reported are printed as fixed (advisory) so the
  baseline can be shrunk;
- ``{"bootstrap": true}`` in the baseline makes the gate print the full
  generated baseline and exit 0 with a loud warning — used exactly once to
  capture the initial known set from CI, then replaced with the real data.

The baseline is the machine-readable record that the listed vulnerabilities
are KNOWN and tracked, never silently accepted.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / ".github" / "pip_audit_baseline.json"


def run_audit() -> dict[str, list[str]]:
    proc = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--local", "-f", "json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    # pip-audit exits 1 when vulnerabilities exist; that is data, not failure.
    if not proc.stdout.strip():
        print(proc.stderr[-2000:], file=sys.stderr)
        raise SystemExit("pip-audit produced no JSON output")
    data = json.loads(proc.stdout)
    found: dict[str, list[str]] = {}
    for dep in data.get("dependencies", []):
        ids = sorted(v.get("id", "") for v in dep.get("vulns", []) if v.get("id"))
        if ids:
            found[dep.get("name", "?")] = ids
    return found


def main() -> int:
    found = run_audit()

    if not BASELINE_PATH.exists():
        print("[FAIL] missing .github/pip_audit_baseline.json — generated baseline:")
        print(json.dumps({"packages": found}, indent=2, sort_keys=True))
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if baseline.get("bootstrap"):
        print("[WARN] pip-audit baseline is in BOOTSTRAP mode: known set below "
              "is NOT yet gated. Commit it as the real baseline.")
        print(json.dumps({"packages": found}, indent=2, sort_keys=True))
        return 0

    known: dict[str, list[str]] = baseline.get("packages", {})
    known_ids = {i for ids in known.values() for i in ids}
    found_ids = {i for ids in found.values() for i in ids}

    new = sorted(found_ids - known_ids)
    fixed = sorted(known_ids - found_ids)

    if fixed:
        print(f"[OK]   {len(fixed)} baseline vulnerabilities no longer reported "
              f"— shrink the baseline: {', '.join(fixed[:10])}"
              + (" …" if len(fixed) > 10 else ""))
    if new:
        print(f"[FAIL] {len(new)} NEW vulnerability id(s) not in baseline:")
        for pkg, ids in sorted(found.items()):
            fresh = [i for i in ids if i in set(new)]
            if fresh:
                print(f"  {pkg}: {', '.join(fresh)}")
        return 1

    print(f"[OK]   pip-audit gate: no new vulnerabilities "
          f"({len(found_ids)} known and tracked in baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
