#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""List the lock entries no declared install set installs.

requirements-lock.txt freezes the environment the evidence was measured in,
so it pins packages that no CI install set pulls (experiment SDKs, plotting,
platform wheels). A bump to one of them changes the lock digest and the
replication pack's history without any test running against it. This
resolves every install set in scripts/check_lock_resolvable.py against the
lock (``pip install --dry-run --report``) and prints the lock entries none of
them installs: the ``measurement-env`` group in .github/dependabot.yml.

    python scripts/lock_measurement_only.py            # print the names
    python scripts/lock_measurement_only.py --check    # fail if dependabot.yml drifted

Needs network for the resolver; it downloads no wheels.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_lock_resolvable import EXTRA_SETS, LOCK_FILE, _constraint_lines  # noqa: E402

DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def measurement_only() -> list[str]:
    lock_text = LOCK_FILE.read_text(encoding="utf-8")
    locked = [line.split("==")[0] for line in _constraint_lines(lock_text) if "==" in line]
    used: set[str] = set()
    with tempfile.TemporaryDirectory() as tmp:
        constraints = Path(tmp) / "constraints.txt"
        constraints.write_text("\n".join(_constraint_lines(lock_text)) + "\n", encoding="utf-8")
        for extras in EXTRA_SETS:
            report = Path(tmp) / "report.json"
            subprocess.run(  # noqa: S603 - fixed argv, no shell
                [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                 "--no-input", "-q", "--report", str(report), "-e", f".[{extras}]",
                 "-c", str(constraints)],
                cwd=REPO_ROOT, check=True, capture_output=True)
            for item in json.loads(report.read_text(encoding="utf-8"))["install"]:
                used.add(_norm(item["metadata"]["name"]))
    return sorted((name for name in locked if _norm(name) not in used), key=str.lower)


def configured() -> list[str]:
    """The names listed under the measurement-env group in dependabot.yml."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    block = text.split("measurement-env:", 1)[1].split("patterns:", 1)[1]
    names = []
    for line in block.splitlines()[1:]:
        match = re.match(r'^\s+- "([^"]+)"\s*$', line)
        if not match:
            break
        names.append(match.group(1))
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    names = measurement_only()
    if not args.check:
        print("\n".join(names))
        return 0
    have = configured()
    missing = sorted(set(names) - set(have), key=str.lower)
    extra = sorted(set(have) - set(names), key=str.lower)
    if missing or extra:
        print(f"[FAIL] measurement-env drifted: add {missing}, remove {extra}")
        return 1
    print(f"[OK] measurement-env lists the {len(names)} lock entries no install set installs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
