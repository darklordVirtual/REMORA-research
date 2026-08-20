#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Bind capability verification to the code state that was verified.

``capability_register_v1.yaml`` carries a status and a caveat per capability,
both of which are claims about code. Until now neither was bound to a revision,
so a core change could age every caveat in the file silently: the register said
``updated: 2026-08-03`` while the product truth contract had moved on to
2026-08-19, and nothing failed.

This gate closes that. A capability may carry ``verified_at_sha``: the commit
whose code state was actually audited. If any of its evidence sources changed
after that commit, the capability is **stale** — its status and caveat describe
code that no longer exists — and this script fails.

**Bootstrapping is deliberately not a mass re-audit.** Writing today's HEAD into
every capability would assert eighteen audits that nobody performed. Instead:

* a capability without ``verified_at_sha`` is reported as UNBOUND, not stale;
* the number of UNBOUND capabilities is ratcheted by ``unbound_baseline`` in the
  register, so the backlog can shrink but never grow. A new capability must be
  bound at the moment it is added, and re-auditing an old one is a one-way door.

Statuses this script reports:

``BOUND``      evidence unchanged since ``verified_at_sha`` — the caveat still
               describes the audited code.
``STALE``      evidence moved after ``verified_at_sha``. Re-audit and update the
               sha, or record why the change does not affect the claim.
``UNBOUND``    no ``verified_at_sha`` yet. Counted against the ratchet.
``UNKNOWN``    the recorded sha is not in this repository (shallow clone,
               rewritten history). Reported, and fatal only with --strict, so a
               CI checkout depth cannot silently disable the gate.

Usage::

    python scripts/check_capability_freshness.py [--strict]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "capability_register_v1.yaml"

#: Evidence prefixes that count as "the code this capability is a claim about".
#: Tests and scripts are evidence too, but a test moving is not what ages a
#: caveat — a change to the implementation is.
SOURCE_PREFIXES = ("remora/", "servers/")


def load_register(path: Path = REGISTER) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


def source_evidence(capability: dict) -> list[str]:
    """Evidence entries that are implementation sources, not tests or docs."""
    return [
        rel
        for rel in capability.get("evidence", [])
        if rel.startswith(SOURCE_PREFIXES) and not rel.startswith("tests/")
    ]


def _git(*args: str, cwd: Path = ROOT) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout.strip()


def commits_since(sha: str, paths: list[str], cwd: Path = ROOT) -> list[str] | None:
    """Commits touching ``paths`` after ``sha``. None if ``sha`` is unknown."""
    code, _ = _git("cat-file", "-e", f"{sha}^{{commit}}", cwd=cwd)
    if code != 0:
        return None
    code, out = _git("rev-list", f"{sha}..HEAD", "--", *paths, cwd=cwd)
    if code != 0:
        return None
    return [line for line in out.splitlines() if line]


def classify(capability: dict, cwd: Path = ROOT) -> tuple[str, str]:
    """(status, detail) for one capability."""
    sha = capability.get("verified_at_sha")
    if not sha:
        return "UNBOUND", "no verified_at_sha — status and caveat are unbound to a revision"
    sources = source_evidence(capability)
    if not sources:
        return "BOUND", "no implementation sources cited; nothing to age"
    moved = commits_since(str(sha), sources, cwd=cwd)
    if moved is None:
        return "UNKNOWN", f"verified_at_sha {sha[:12]} is not in this repository"
    if moved:
        shown = ", ".join(c[:12] for c in moved[:3])
        more = f" (+{len(moved) - 3} more)" if len(moved) > 3 else ""
        return "STALE", f"{len(moved)} commit(s) since {sha[:12]}: {shown}{more}"
    return "BOUND", f"unchanged since {sha[:12]}"


def main(argv: list[str]) -> int:
    strict = "--strict" in argv[1:]
    register = load_register()
    capabilities = register["capabilities"]
    baseline = int(
        (register.get("verification_binding") or {}).get("unbound_baseline", len(capabilities))
    )

    counts: dict[str, int] = {}
    failures: list[str] = []
    unknowns: list[str] = []

    for cap in capabilities:
        status, detail = classify(cap)
        counts[status] = counts.get(status, 0) + 1
        marker = {"BOUND": "OK  ", "STALE": "FAIL", "UNBOUND": "TODO", "UNKNOWN": "WARN"}[status]
        print(f"[{marker}] {cap['id']:<9} {status:<8} {detail}")
        if status == "STALE":
            failures.append(
                f"{cap['id']}: {detail} — re-audit and update verified_at_sha, "
                f"or drop the status to NEEDS_REVIEW"
            )
        elif status == "UNKNOWN":
            unknowns.append(f"{cap['id']}: {detail}")

    unbound = counts.get("UNBOUND", 0)
    print(
        f"\n{counts.get('BOUND', 0)} bound, {counts.get('STALE', 0)} stale, "
        f"{unbound} unbound (baseline {baseline}), {counts.get('UNKNOWN', 0)} unknown"
    )

    if unbound > baseline:
        failures.append(
            f"unbound capabilities rose to {unbound}, above the baseline of "
            f"{baseline}: a new capability must carry verified_at_sha"
        )
    if unknowns:
        for line in unknowns:
            print(f"  ! {line}", file=sys.stderr)
        if strict:
            failures.extend(unknowns)

    if failures:
        print("\n[FAIL] capability verification binding:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1

    if unbound:
        print(
            f"\n[PASS] no stale capability. {unbound} still unbound — bind one "
            f"whenever it is audited; the baseline ratchets down, never up."
        )
    else:
        print("\n[PASS] every capability is bound to the code state it was verified against.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
