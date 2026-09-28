#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A FAR claim must rest on enough independent harmful units (quality program Q2.1).

Zero false accepts in N harmful episodes bounds the one-sided 95 % false
accept rate at about 3/N (rule of three). At N = 299 that is about 1 %, the
precision a claim written as "FAR = 0 %" invites a reader to assume. Below
it, the honest claim is the upper bound, and the zero is mostly a statement
about how few cases were tried.

Every active claim in docs/assurance/claim_register_v1.yaml with a
``far_pct`` metric must declare ``far_denominator``: the number of
*independent* harmful units, which is the cluster count when variants of one
template are not independent. A claim below the minimum fails unless it is
listed in docs/assurance/far_claim_size_baseline.json with a reason and the
same denominator. The baseline may only shrink: an entry whose claim is gone,
no longer active, or now meets the minimum fails as stale.

    python scripts/check_far_claim_size.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"
BASELINE = ROOT / "docs" / "assurance" / "far_claim_size_baseline.json"


def violations(register: dict, baseline: dict) -> list[str]:
    minimum = int(baseline["minimum_denominator"])
    allowed = {e["id"]: e for e in baseline.get("entries", [])}
    problems: list[str] = []
    below: set[str] = set()
    active_far = {}
    for claim in register.get("claims", []):
        if claim.get("status") != "active" or "far_pct" not in (claim.get("metrics") or {}):
            continue
        cid = claim["id"]
        active_far[cid] = claim
        n = claim.get("far_denominator")
        if not isinstance(n, int) or n <= 0:
            problems.append(f"{cid}: a FAR claim must declare far_denominator, the "
                            "number of independent harmful units it rests on")
            continue
        if n >= minimum:
            continue
        below.add(cid)
        entry = allowed.get(cid)
        if entry is None:
            problems.append(f"{cid}: FAR claim on {n} independent harmful units, below "
                            f"the {minimum} a ~1% bound needs; state the upper bound "
                            "instead, or baseline it with a reason")
        elif int(entry.get("far_denominator", -1)) != n or not str(entry.get("reason", "")).strip():
            problems.append(f"{cid}: baseline entry must repeat far_denominator={n} "
                            "and give a reason")
    for cid in sorted(set(allowed) - below):
        problems.append(f"{cid}: stale baseline entry (claim not active, not a FAR "
                        f"claim, or now at least {minimum}); remove it")
    return problems


def main() -> int:
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    problems = violations(register, baseline)
    if problems:
        print("[FAIL] FAR claim size:")
        for p in problems:
            print(f"  - {p}")
        return 1
    n = len(baseline.get("entries", []))
    print(f"[PASS] FAR claim size: every active FAR claim declares its denominator; "
          f"{n} below {baseline['minimum_denominator']} baselined with reasons.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
