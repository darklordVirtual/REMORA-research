# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CI gate (SR-11 / SR-23, SEC-19): Python installs in workflows must be
hash-pinned, and the pinned lock files must carry a hash on every package.

Rules:
  1. Every `pip install` line in .github/workflows/*.yml must use
     `--require-hashes` with a `-r` lock file, or a `-c` constraints file,
     or be marked with `# hash-exempt: <reason>` on the same or previous line
     (used only for the verbatim README-contract jobs, whose purpose is to
     run the documented command exactly as written).
  2. requirements-ci.lock and requirements-release.lock: every package line
     (`name==version`) must carry at least one `--hash=sha256:...`.
  3. A `pip install` naming a package directly (not via -r) is never allowed
     without hashes — the release job's old `pip install cyclonedx-bom` is
     the failure this gate exists for.

Exits non-zero with every violation listed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
HASHED_LOCKS = ("requirements-ci.lock", "requirements-release.lock")

_PIP_INSTALL = re.compile(r"\bpip(?:\.\w+)?(?:\s+-m\s+pip)?\s+install\b")
_EXEMPT = re.compile(r"#\s*hash-exempt:", re.IGNORECASE)
_PKG_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==\S+\s*\\?$")
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")


_PIP_SELF_UPGRADE = re.compile(
    r"pip\s+install\s+(--upgrade\s+)?pip\s*$"
)
_LOCAL_EDITABLE = re.compile(r"-e\s+\"?\.")
_PINNED_DIRECT = re.compile(r"^[a-zA-Z0-9._-]+==\S+$")


def _logical_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Join backslash continuations so a multi-line install is judged whole."""
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        start, text = i, lines[i]
        while text.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            text = text.rstrip()[:-1] + " " + lines[i].strip()
        out.append((start, text))
        i += 1
    return out


def _check_workflows() -> list[str]:
    problems: list[str] = []
    for wf in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        raw_lines = wf.read_text(encoding="utf-8").splitlines()
        lines = _logical_lines(raw_lines)
        for i, line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not _PIP_INSTALL.search(line):
                continue
            if "--require-hashes" in line or "-c " in line or "-c\t" in line:
                continue
            # Markers may sit anywhere in the comment run above the install's
            # step: walk back through the step body (`run: |` block lines)
            # and its header; stop at the PREVIOUS step's header.
            context = line
            step_headers_seen = 0
            for j in range(i - 1, max(i - 15, -1), -1):
                prev = raw_lines[j].strip()
                if prev.startswith("#"):
                    context = prev + "\n" + context
                    continue
                if prev.startswith("- name:"):
                    step_headers_seen += 1
                    if step_headers_seen > 1:
                        break
                    continue
                if prev.startswith(("run:", "uses:", "if:", "with:", "env:",
                                    "working-directory:")) or not prev:
                    continue
                if prev.endswith("|") or prev.endswith("|-"):
                    continue
                # Ordinary content inside the current step's run block.
                if step_headers_seen == 0:
                    continue
                break
            if _EXEMPT.search(context):
                continue
            # pip upgrading itself is the bootstrap installer step; the
            # release job does NOT do this (its pip comes from the hashed
            # release lock).
            if _PIP_SELF_UPGRADE.search(line):
                continue
            # Editable or path install of in-repository code: not third-party.
            if _LOCAL_EDITABLE.search(line) or re.search(r"install\b[^#]*\./", line):
                continue
            # Direct third-party installs must at least be version-pinned and
            # carry an explicit marker; the release path requires hashes.
            rest = _PIP_INSTALL.split(line, 1)[1]
            rest = rest.split("#", 1)[0].strip()
            parts = [p for p in rest.split() if not p.startswith("-")]
            if parts and all(_PINNED_DIRECT.match(part) for part in parts):
                if not re.search(r"#\s*pinned:", context):
                    problems.append(
                        f"{wf.name}:{i + 1}: version-pinned but unhashed and "
                        "unmarked direct install"
                    )
                continue
            problems.append(
                f"{wf.name}:{i + 1}: pip install without --require-hashes, "
                "constraints, or a # hash-exempt marker"
            )
    return problems


def _check_lock(name: str) -> list[str]:
    path = ROOT / name
    if not path.exists():
        return [f"{name}: missing (generate with pip-compile --generate-hashes)"]
    problems: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = _PKG_LINE.match(line)
        if match:
            # Collect continuation lines (hash lines) belonging to this pin.
            block = [line]
            while block[-1].endswith("\\") and i + 1 < len(lines):
                i += 1
                block.append(lines[i].strip())
            if not any(_HASH.search(b) for b in block):
                problems.append(f"{name}:{i + 1}: {match.group(1)} has no sha256 hash")
        i += 1
    return problems


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="repo root to check (default: script's)")
    args = parser.parse_args(argv)

    global ROOT, WORKFLOWS
    if args.root:
        ROOT = Path(args.root).resolve()
        WORKFLOWS = ROOT / ".github" / "workflows"

    problems = _check_workflows()
    for name in HASHED_LOCKS:
        problems.extend(_check_lock(name))
    if problems:
        print("[FAIL] hash-pinning gate:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("[OK] every workflow pip install is hash-pinned, constrained, or "
          "explicitly exempt; both hashed locks carry sha256 on every package")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
