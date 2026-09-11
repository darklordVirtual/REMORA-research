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
  It is REFUSED on a pull request or a push (2026-09-03): as an unguarded
  escape hatch it turned the whole gate off in one line, in the same commit
  that introduced whatever it was hiding.

Because the accepted set lives in the branch, a pull request could also
accept a new vulnerability by adding its id to the baseline in the same
commit. In CI the accepted set is therefore taken from ``origin/master``:
widening it is a change to the base branch, made and reviewed on its own,
not a side effect of the change that needs it.

The baseline is the machine-readable record that the listed vulnerabilities
are KNOWN and tracked, never silently accepted.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _baseline_ratchet import base_blob, is_gated_ci, skip_note  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REL = ".github/pip_audit_baseline.json"
BASELINE_PATH = ROOT / BASELINE_REL


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pip-audit baseline gate")
    parser.add_argument(
        "--root", type=Path, default=None,
        help="use this tree's baseline instead of the repository's",
    )
    parser.add_argument(
        "--skip-audit", action="store_true",
        help="do not run pip-audit; check baseline hygiene only",
    )
    args = parser.parse_args(argv)

    global ROOT, BASELINE_PATH
    if args.root is not None:
        ROOT = args.root.resolve()
        BASELINE_PATH = ROOT / BASELINE_REL

    found: dict[str, list[str]] = {} if args.skip_audit else run_audit()

    if not BASELINE_PATH.exists():
        print("[FAIL] missing .github/pip_audit_baseline.json - generated baseline:")
        print(json.dumps({"packages": found}, indent=2, sort_keys=True))
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if baseline.get("bootstrap"):
        if is_gated_ci():
            print("[FAIL] the pip-audit baseline is in BOOTSTRAP mode, which "
                  "disables this gate entirely. Bootstrap is refused on a "
                  "pull request or a push: commit the real baseline.",
                  file=sys.stderr)
            return 1
        print("[WARN] pip-audit baseline is in BOOTSTRAP mode: known set below "
              "is NOT yet gated. Commit it as the real baseline.")
        print(json.dumps({"packages": found}, indent=2, sort_keys=True))
        return 0

    known: dict[str, list[str]] = baseline.get("packages", {})
    known_ids = {i for ids in known.values() for i in ids}

    # In CI the accepted set is the base branch's, so this pull request
    # cannot accept a vulnerability by adding its id to its own baseline.
    blob = base_blob(BASELINE_REL, ROOT)
    if blob is None:
        print(skip_note(BASELINE_REL))
        if is_gated_ci():
            print("[FAIL] cannot read the base baseline in CI", file=sys.stderr)
            return 1
    else:
        try:
            base = json.loads(blob)
        except json.JSONDecodeError:
            base = {}
        if base.get("bootstrap") and is_gated_ci():
            print("[FAIL] the base branch's pip-audit baseline is in bootstrap "
                  "mode; this gate has never been armed.", file=sys.stderr)
            return 1
        base_ids = {i for ids in base.get("packages", {}).values() for i in ids}
        widened = sorted(known_ids - base_ids)
        if widened:
            print("[FAIL] this branch accepts vulnerability id(s) that "
                  f"origin/master does not: {', '.join(widened)}. Widening the "
                  "accepted set is a change to the base branch, reviewed on "
                  "its own.", file=sys.stderr)
            return 1
        known_ids = base_ids

    if args.skip_audit:
        print("[OK]   pip-audit baseline hygiene checked (audit skipped)")
        return 0

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
