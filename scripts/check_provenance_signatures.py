#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signature gate for the provenance ledger.

Commits that touch a protected path (provenance/POLICY.yaml) after
``signatures.enforced_from`` must be signed and verified. Until
``enforced_from`` is set the gate reports what it would enforce and exits 0;
once set, an unsigned or unverified commit fails the build.

Verification source, in order:

1. GitHub's commit verification record, when ``GITHUB_TOKEN`` and
   ``GITHUB_REPOSITORY`` are set (the record GitHub keeps when it verified a
   signature, which survives later key rotation or revocation);
2. ``git log --format=%G?`` otherwise, which needs the signer's public key in
   the local keyring and is therefore advisory outside CI.

    python scripts/check_provenance_signatures.py            # gate
    python scripts/check_provenance_signatures.py --report   # list, never fail
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "provenance" / "POLICY.yaml"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def protected_commits(paths: list[str], since: str | None) -> list[tuple[str, str, str]]:
    """(sha, git signature status, subject) for every commit touching a protected path."""
    rng = f"{since}..HEAD" if since else "HEAD"
    out = _git("log", "--format=%H%x00%G?%x00%s", rng, "--", *paths)
    rows = []
    for line in out.splitlines():
        sha, status, subject = line.split("\x00", 2)
        rows.append((sha, status, subject))
    return rows


def github_verified(sha: str) -> bool | None:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/commits/{sha}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
            data: dict[str, Any] = json.load(resp)
    except Exception as exc:  # network or auth: say so, never pass silently
        print(f"[WARN] GitHub verification lookup failed for {sha[:12]}: {exc}")
        return None
    return bool(data.get("commit", {}).get("verification", {}).get("verified"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--report", action="store_true", help="list the commits and their status; never fail")
    args = parser.parse_args(argv)
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    paths = policy["protected_paths"]
    since = policy["signatures"]["enforced_from"]
    accepted = set(policy["signatures"]["accepted_git_status"])
    rows = protected_commits(paths, since)
    enforcing = since is not None and not args.report
    failures = []
    for sha, status, subject in rows:
        verified = github_verified(sha)
        ok = verified if verified is not None else status in accepted
        source = "github" if verified is not None else f"git %G?={status}"
        print(f"[{'OK' if ok else 'UNSIGNED'}] {sha[:12]} {source}: {subject[:70]}")
        if not ok:
            failures.append(sha)
    if not enforcing:
        print(f"[REPORT] {len(rows)} commit(s) touch protected paths; {len(failures)} not verified. "
              f"The gate is {'armed from ' + since[:12] if since else 'not armed (signatures.enforced_from is null)'}.")
        return 0
    if failures:
        print(f"[FAIL] {len(failures)} commit(s) after {since[:12]} touch provenance paths without a verified signature")
        return 1
    print(f"[PASS] every commit after {since[:12]} touching provenance paths is signed and verified ({len(rows)} checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
