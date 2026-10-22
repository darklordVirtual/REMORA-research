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
them installs. Those an earlier Dependabot group already matches stay there;
the rest are the ``measurement-env-N`` groups in .github/dependabot.yml,
split because Dependabot allows at most 100 patterns per group.

    python scripts/lock_measurement_only.py            # print the names
    python scripts/lock_measurement_only.py --check    # fail if dependabot.yml drifted
    python scripts/lock_measurement_only.py --write    # rewrite the groups

Needs network for the resolver; it downloads no wheels.
"""
from __future__ import annotations

import argparse
import fnmatch
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
#: Dependabot rejects a group with more than 100 patterns.
MAX_PATTERNS = 100
GROUP_PREFIX = "measurement-env-"


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


def _pip_groups() -> dict[str, list[str]]:
    """The groups of the root pip entry and their patterns.

    Read with the standard library: the CI job that runs --check has no
    PyYAML. It relies on the file's layout (groups at six spaces, patterns at
    ten), which ``--check`` exercises on every run.
    """
    lines = DEPENDABOT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.strip() == '- package-ecosystem: "pip"'
                 and lines[i + 1].strip() == 'directory: "/"')
    groups: dict[str, list[str]] = {}
    current: str | None = None
    in_groups = False
    for line in lines[start + 1:]:
        if line.startswith("  - "):
            break  # the next ecosystem entry
        if line.strip() == "groups:":
            in_groups = True
            continue
        if not in_groups or not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 4:
            break  # past the groups mapping (e.g. "ignore:")
        group = re.match(r"^ {6}([A-Za-z0-9_.-]+):\s*$", line)
        if group:
            current = group.group(1)
            groups[current] = []
            continue
        inline = re.match(r"^\s+patterns:\s*\[(.*)\]\s*$", line)
        if inline and current is not None:
            groups[current] += re.findall(r'"([^"]+)"', inline.group(1))
            continue
        pattern = re.match(r'^\s+- "([^"]+)"\s*$', line)
        if pattern and current is not None:
            groups[current].append(pattern.group(1))
    return groups


def uncovered(names: list[str]) -> list[str]:
    """The names no other version-update group of the root pip entry matches."""
    others = [p for name, patterns in _pip_groups().items()
              if not name.startswith(GROUP_PREFIX) and patterns != ["*"] for p in patterns]
    return [n for n in names
            if not any(fnmatch.fnmatch(_norm(n), _norm(p)) for p in others)]


def configured() -> list[str]:
    """Every name listed in the measurement-env-N groups."""
    return [p for name, patterns in _pip_groups().items()
            if name.startswith(GROUP_PREFIX) for p in patterns]


def write_groups(names: list[str]) -> None:
    """Replace the measurement-env-N groups with *names*, at most 100 each."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    start = text.index(f"      {GROUP_PREFIX}1:")
    end = text.index("\n\n", start)
    chunks = [names[i:i + MAX_PATTERNS] for i in range(0, len(names), MAX_PATTERNS)]
    block = "\n".join(
        f"      {GROUP_PREFIX}{n}:\n        applies-to: version-updates\n        patterns:\n"
        + "\n".join(f'          - "{name}"' for name in chunk)
        for n, chunk in enumerate(chunks, 1))
    DEPENDABOT.write_text(text[:start] + block + text[end:], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    names = uncovered(measurement_only())
    if args.write:
        write_groups(names)
        print(f"[WRITE] {len(names)} names in {GROUP_PREFIX}N groups")
        return 0
    if not args.check:
        print("\n".join(names))
        return 0
    groups = [g for name, g in _pip_groups().items() if name.startswith(GROUP_PREFIX)]
    if any(len(g) > MAX_PATTERNS for g in groups):
        print(f"[FAIL] a {GROUP_PREFIX}N group has more than {MAX_PATTERNS} patterns")
        return 1
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
