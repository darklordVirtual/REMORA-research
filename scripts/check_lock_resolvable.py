#!/usr/bin/env python3
"""Check that requirements-lock.txt can actually resolve every install set CI uses.

The lock is a flat list of ``name==version`` pins applied as a pip *constraints*
file. Constraints do not participate in dependency resolution as a unit: each
line is checked only when pip is asked to install that distribution. A pin can
therefore contradict another pin for months without anyone noticing, until one
workflow installs the pair together and pip reports ResolutionImpossible in the
install step -- long after the pull request that introduced the contradiction
was merged green.

That is not hypothetical. On 2026-09-21 the weekly NLI parity run died on
``click==8.1.8`` against ``huggingface_hub==1.28.0`` (which requires
``click>=8.4.2``); repairing that one pin uncovered five further contradictions
in the same file, each introduced by a single-line dependency bump.

This script closes that gap by resolving, not by reading. For each declared
extra set it runs ``pip install --dry-run`` against the lock as constraints.
``--dry-run`` performs the full resolution and downloads nothing, so the check
costs metadata requests rather than wheels.

Scope (declared, not exhaustive): resolvability of the declared extra sets on
the running interpreter and platform. It does not check that the resolved
versions are the pinned ones, that the code works with them, or that a set not
listed in ``EXTRA_SETS`` resolves. It requires network access.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = REPO_ROOT / "requirements-lock.txt"

# Every extra set a workflow installs with the lock as constraints, plus the
# extras the lock claims to pin but no workflow currently exercises. Keep this
# list in step with the `pip install -e ".[...]" -c` lines under
# .github/workflows/.
EXTRA_SETS: tuple[str, ...] = (
    "dev",
    "dev,api",
    "dev,causal",
    "dev,causal,api",
    "dev,causal,api,security",
    "dev,causal,api,security,postgres",
    "dev,nli",
    "docs",
    "agentharm",
)


def declared_extra_sets() -> frozenset[frozenset[str]]:
    """EXTRA_SETS as unordered sets: ``dev,api`` and ``api,dev`` are one install set."""
    return frozenset(frozenset(entry.split(",")) for entry in EXTRA_SETS)

# Lines pip rejects in a constraints file: editable installs, comments and
# direct references. Mirrors the `grep -vE` filter the workflows apply.
def _constraint_lines(lock_text: str) -> list[str]:
    kept = []
    for line in lock_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-e")) or "file://" in stripped:
            continue
        kept.append(stripped)
    return kept


def _conflict_reason(output: str) -> str:
    """Pull pip's own explanation out of a failed resolution."""
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if "conflict is caused by" in line:
            reason = []
            for candidate in lines[index + 1 :]:
                if candidate.startswith("To fix this"):
                    break
                if candidate.strip():
                    reason.append(candidate.strip())
            return "; ".join(reason)
    for line in lines:
        if line.startswith("ERROR:"):
            return line
    return "resolution failed without a parseable reason"


def resolve(extras: str, constraints: Path) -> tuple[bool, str]:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--no-input",
            "-e",
            f".[{extras}]",
            "-c",
            str(constraints),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, ""
    return False, _conflict_reason(result.stdout + result.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extras",
        action="append",
        help="resolve only this extra set (repeatable); defaults to all declared sets",
    )
    args = parser.parse_args(argv)
    targets = tuple(args.extras) if args.extras else EXTRA_SETS

    with tempfile.TemporaryDirectory() as tmp:
        constraints = Path(tmp) / "constraints.txt"
        constraints.write_text(
            "\n".join(_constraint_lines(LOCK_FILE.read_text(encoding="utf-8"))) + "\n",
            encoding="utf-8",
        )
        failures = []
        for extras in targets:
            ok, reason = resolve(extras, constraints)
            print(f"{'ok  ' if ok else 'FAIL'}  .[{extras}]" + (f" -- {reason}" if reason else ""))
            if not ok:
                failures.append(extras)

    if failures:
        print(
            "\nrequirements-lock.txt cannot resolve: "
            + ", ".join(f".[{extras}]" for extras in failures),
            file=sys.stderr,
        )
        return 1
    print(f"\nall {len(targets)} declared install sets resolve against the lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
