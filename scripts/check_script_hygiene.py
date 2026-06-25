#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Check script metadata and basic source hygiene for files under scripts/.

This checker enforces lightweight repository conventions:
- Python scripts must include Author and License headers.
- Python scripts must include a top-level module docstring within the first 30 lines.
- If a script has a shebang, it must be on line 1.
- Files must not start with a UTF-8 BOM.

The check is intentionally conservative and CI-friendly.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def has_top_docstring(lines: list[str], max_scan: int = 30) -> bool:
    for line in lines[:max_scan]:
        if line.startswith('"""'):
            return True
    return False


def check_file(path: Path) -> list[str]:
    issues: list[str] = []

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append("starts with UTF-8 BOM")

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    author_count = sum(1 for line in lines if line.startswith("# Author:"))
    license_count = sum(1 for line in lines if line.startswith("# License:"))

    if author_count == 0:
        issues.append("missing '# Author:' header")
    if license_count == 0:
        issues.append("missing '# License:' header")

    if not has_top_docstring(lines):
        issues.append("missing top-level module docstring (within first 30 lines)")

    shebang_lines = [i + 1 for i, line in enumerate(lines) if line.startswith("#!")]
    if shebang_lines and shebang_lines[0] != 1:
        issues.append(f"shebang on line {shebang_lines[0]} (must be line 1)")

    return issues


def main() -> None:
    script_files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "legacy").glob("*.py"))
    if not script_files:
        fail("No script files found under scripts/")

    failures = 0
    for path in script_files:
        issues = check_file(path)
        rel = path.relative_to(ROOT.parent)
        if issues:
            failures += 1
            for issue in issues:
                print(f"[FAIL] {rel}: {issue}")
        else:
            ok(f"{rel}")

    if failures:
        fail(f"Script hygiene check failed for {failures} file(s)")

    print("\n[PASS] Script hygiene checks passed.")


if __name__ == "__main__":
    main()
