#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate a comprehensive quality report for REMORA.

Checks:
  1. Test collection (no import errors)
  2. Ruff lint
  3. py.typed marker present
  4. Security module (remora/safety/adversarial.py)
  5. Eval pack harness runnable
  6. ARCHITECTURE.md contains Mermaid diagram
  7. mkdocs.yml present
  8. stability.py present

Usage:
    python scripts/quality_report.py
    python scripts/quality_report.py --json
    python scripts/quality_report.py --fail-on-warnings
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    return r.returncode, (r.stdout + r.stderr).strip()


def check(name: str, fn) -> dict:
    try:
        status, detail = fn()
        return {"name": name, "status": status, "detail": detail}
    except Exception as exc:
        return {"name": name, "status": "ERROR", "detail": str(exc)}


CHECKS = [
    (
        "test_collection",
        lambda: (
            ("PASS", f"{_run([sys.executable, '-m', 'pytest', '--co', '-q'])[1].split(chr(10))[-1]}")
            if _run([sys.executable, "-m", "pytest", "--co", "-q"])[0] == 0
            else ("FAIL", "collection errors — run: pytest --co -q")
        ),
    ),
    (
        "ruff_lint",
        lambda: (
            ("PASS", "0 lint errors")
            if _run(["ruff", "check", "."])[0] == 0
            else ("WARN", "lint errors — run: ruff check .")
        ),
    ),
    (
        "py_typed",
        lambda: (
            ("PASS", "remora/py.typed present")
            if (ROOT / "remora" / "py.typed").exists()
            else ("FAIL", "remora/py.typed missing — add empty file")
        ),
    ),
    (
        "security_module",
        lambda: (
            ("PASS", "remora/safety/adversarial.py present")
            if (ROOT / "remora" / "safety" / "adversarial.py").exists()
            else ("WARN", "run Task A1 to add adversarial.py")
        ),
    ),
    (
        "eval_pack_harness",
        lambda: (
            ("PASS", "eval_pack/run_validation.py runnable")
            if (ROOT / "eval_pack" / "run_validation.py").exists()
            and _run([sys.executable, "eval_pack/run_validation.py", "--dry-run", "--json"])[0] == 0
            else ("WARN", "eval_pack/run_validation.py missing or broken — run Task C2")
        ),
    ),
    (
        "architecture_mermaid",
        lambda: (
            ("PASS", "ARCHITECTURE.md contains Mermaid diagram")
            if "mermaid" in (ROOT / "ARCHITECTURE.md").read_text()
            else ("WARN", "ARCHITECTURE.md lacks Mermaid — run Task D1")
        ),
    ),
    (
        "mkdocs_config",
        lambda: (
            ("PASS", "mkdocs.yml present")
            if (ROOT / "mkdocs.yml").exists()
            else ("WARN", "mkdocs.yml missing — run Task D2")
        ),
    ),
    (
        "stability_module",
        lambda: (
            ("PASS", "remora/stability.py present")
            if (ROOT / "remora" / "stability.py").exists()
            else ("WARN", "remora/stability.py missing — run Task B1")
        ),
    ),
]


def main() -> int:
    results = [check(name, fn) for name, fn in CHECKS]

    if "--json" in sys.argv:
        print(json.dumps(results, indent=2))
        return 0

    print(f"\nREMORA Quality Report — {ROOT.name}\n")
    counts: dict[str, int] = {}
    for r in results:
        s = r["status"]
        counts[s] = counts.get(s, 0) + 1
        icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "ERROR": "!"}.get(s, "?")
        print(f"  {icon} [{s:<5}] {r['name']}")
        print(f"         {r['detail']}")

    print(
        f"\nSummary: {counts.get('PASS', 0)} passed, "
        f"{counts.get('WARN', 0)} warnings, "
        f"{counts.get('FAIL', 0)} failed, "
        f"{counts.get('ERROR', 0)} errors\n"
    )

    if "--fail-on-warnings" in sys.argv:
        return 1 if sum(counts.get(k, 0) for k in ("FAIL", "WARN", "ERROR")) > 0 else 0
    return 1 if sum(counts.get(k, 0) for k in ("FAIL", "ERROR")) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
