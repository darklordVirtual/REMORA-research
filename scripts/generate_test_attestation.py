# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate a commit-bound test attestation for the credibility pack.

Runs the full deterministic suite and writes:

  artifacts/credibility-pack/test-attestation.json  (machine-readable)
  artifacts/credibility-pack/test-report.txt        (pytest transcript + header)

The attestation binds the result to the exact repository state: full git
commit SHA, dirty-worktree flag, Python/pytest versions, platform, and the
SHA-256 of requirements-lock.txt (LF-normalized, matching the artifact
manifest hash protocol). An external reviewer can therefore decide exactly
which code a green test report attests — the gap that made the previous
undated, commit-less test-report.txt unverifiable.

Fails hard (exit 1) when the suite is not fully green; a failing run still
writes the attestation with gate: FAIL so a stale green attestation cannot
survive unnoticed.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "artifacts" / "credibility-pack"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    # Explicit UTF-8: without it, Windows decodes the child's output with the
    # locale codepage (cp1252, strict), and a failing test whose output holds
    # UTF-8 multibyte chars would crash this script BEFORE the gate=FAIL
    # attestation is written — exactly the stale-green hole this script exists
    # to close (2026-07-20 adversarial verify).
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=ROOT,
        encoding="utf-8", errors="replace",
    )


def _git(*args: str) -> str:
    return _run(["git", *args]).stdout.strip()


def main() -> int:
    commit = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    lock_bytes = (ROOT / "requirements-lock.txt").read_bytes().replace(b"\r\n", b"\n")
    lock_hash = hashlib.sha256(lock_bytes).hexdigest()
    generated_at = datetime.now(UTC).isoformat()

    proc = _run([sys.executable, "-m", "pytest", "tests/", "-q"])
    transcript = proc.stdout + (("\n" + proc.stderr) if proc.stderr.strip() else "")

    summary = ""
    for line in reversed(transcript.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            summary = line.strip("= ").strip()
            break

    def _count(word: str) -> int:
        m = re.search(rf"(\d+) {word}", summary)
        return int(m.group(1)) if m else 0

    pytest_version = ""
    m = re.search(r"pytest-([\d.]+)", transcript)
    if m:
        pytest_version = m.group(1)

    attestation = {
        "schema": "test_attestation_v1",
        "repository": "darklordVirtual/REMORA-research",
        "current_system_commit": commit,
        "git_dirty_worktree": dirty,
        "generated_at": generated_at,
        "command": "python -m pytest tests/ -q",
        "python_version": platform.python_version(),
        "pytest_version": pytest_version,
        "platform": platform.platform(),
        "dependency_lock_sha256_lf": lock_hash,
        "tests_passed": _count("passed"),
        "tests_failed": _count("failed"),
        "tests_skipped": _count("skipped"),
        "tests_deselected": _count("deselected"),
        "pytest_exit_code": proc.returncode,
        "summary_line": summary,
        "gate": "PASS" if proc.returncode == 0 else "FAIL",
    }

    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / "test-attestation.json").write_text(
        json.dumps(attestation, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    header = (
        "# REMORA test attestation transcript\n"
        f"# commit: {commit}{' (dirty worktree)' if dirty else ''}\n"
        f"# generated_at: {generated_at}\n"
        f"# python: {platform.python_version()}  platform: {platform.platform()}\n"
        f"# dependency_lock_sha256_lf: {lock_hash}\n"
        "# machine-readable attestation: test-attestation.json\n\n"
    )
    (PACK / "test-report.txt").write_text(
        header + transcript, encoding="utf-8", newline="\n"
    )

    print(f"attestation gate={attestation['gate']}: {summary}")
    print(f"commit={commit} dirty={dirty}")
    if proc.returncode != 0:
        print("ERROR: test suite not green; attestation gate=FAIL", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
