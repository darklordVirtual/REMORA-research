#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Refuse retired model identifiers in code that still runs.

A retired identifier fails only when it is called, so a default that names
one looks fine in review and breaks the first live run. PR #582 found two
such defaults (a live benchmark on claude-3-5-sonnet-latest, the recommended
swarm on anthropic/claude-3.5-haiku). This gate keeps them from coming back
(quality program Q5.4).

The retired list comes from Anthropic's published model table and names each
model with the date it was retired. Only dated retirements are listed; a
provider without a dated list here is simply not checked yet.

Paths where an old identifier is history, not a default, are listed in
``FROZEN`` with the reason. Tests, documentation, results and archives are
out of scope: they record what was run.

    python scripts/check_retired_models.py

Exit 1 on any identifier outside ``FROZEN``.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: (pattern, model, retired on). Patterns accept both the API spelling
#: (claude-3-5-sonnet) and the OpenRouter spelling (claude-3.5-sonnet).
RETIRED: tuple[tuple[str, str, str], ...] = (
    (r"claude-3[-.]7-sonnet", "Claude Sonnet 3.7", "2026-02-19"),
    (r"claude-3[-.]5-haiku", "Claude Haiku 3.5", "2026-02-19"),
    (r"claude-3[-.]5-sonnet", "Claude Sonnet 3.5", "2025-10-28"),
    (r"claude-3-opus", "Claude Opus 3", "2026-01-05"),
    (r"claude-3-sonnet", "Claude Sonnet 3", "2025-07-21"),
    (r"claude-3-haiku", "Claude Haiku 3", "2026-04-19"),
    (r"claude-opus-4[-.]1\b", "Claude Opus 4.1", "2026-08-05"),
    (r"claude-2(?:\.[01])?\b", "Claude 2", "2025-07-21"),
    (r"claude-instant", "Claude Instant", "2025-07-21"),
)

#: Directories whose code runs, or ships as a default.
SCANNED = ("remora", "servers", "scripts", "experiments", "workers", "frontend/src")

#: Old identifiers kept on purpose: path, the exact identifiers allowed there,
#: and the reason. Any other retired identifier in the same file still fails.
FROZEN: dict[str, tuple[tuple[str, ...], str]] = {
    "experiments/ablation.py": (
        ("claude-3.5-sonnet",),
        "ablation v1 instrument; its committed results were measured on this "
        "pool and are frozen with the retirement noted (Q2.4, 2026-09-28).",
    ),
    "remora/oracles/factory.py": (
        ("claude-3.5-sonnet",),
        "build_mixed_swarm feeds the ablation and calibration experiments whose "
        "results used this pool; both are frozen (Q2.4, 2026-09-28). "
        "build_recommended_swarm is current.",
    ),
    "remora/aromer/seeds/07_strategy_patterns.seed.json": (
        ("claude-3.5-sonnet",),
        "records the measured ablation v1 correlation and the models it was "
        "measured on; history, not a default.",
    ),
}

#: The gate's own source names every retired pattern.
_SELF = "scripts/check_retired_models.py"

_PATTERN = re.compile("|".join(f"(?:{p})" for p, _, _ in RETIRED))


def _tracked(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", *SCANNED], cwd=root,
        capture_output=True, text=True, check=True).stdout.split()
    return [p for p in out if "/node_modules/" not in p]


def _describe(match: str) -> str:
    for pattern, model, date in RETIRED:
        if re.fullmatch(pattern, match):
            return f"{model}, retired {date}"
    return "retired"


def find_violations(root: Path, paths: list[str] | None = None) -> list[str]:
    violations = []
    for rel in paths if paths is not None else _tracked(root):
        if rel == _SELF:
            continue
        allowed = FROZEN.get(rel, ((), ""))[0]
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in _PATTERN.finditer(line):
                if m.group(0) in allowed:
                    continue
                violations.append(f"{rel}:{lineno}: {m.group(0)} ({_describe(m.group(0))})")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="retired model identifier gate")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    violations = find_violations(args.root)
    if violations:
        print("[FAIL] retired model identifiers in code that runs:")
        for v in violations:
            print(f"  - {v}")
        print("Use a current model, or add the path to FROZEN with the reason.")
        return 1
    print(f"[PASS] no retired model identifiers outside {len(FROZEN)} frozen paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
