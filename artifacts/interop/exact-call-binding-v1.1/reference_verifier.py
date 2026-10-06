#!/usr/bin/env python3
"""Zero-dependency reference verifier for REMORA exact-call-binding-v1.1 fixtures.

This file imports no REMORA code. It models an authorization as the canonical
content of (tool, arguments, tenant, target, principal) plus a single-use
marker, and a dispatch as a presentation of a call against it. A
cross-project verifier should implement the contract independently rather
than treating this program as an oracle.

The comparison is the one exact-call-binding-v1 used. v1.1 adds cases
that a verifier with a lossier number model fails: the integer 1 and the
float 1.0 are different scalars, and two integers beyond 2**53 that a binary
double cannot tell apart are different arguments. A verifier whose JSON
parser maps every number to one double type must keep the source text, or
an exact integer and float representation, to implement this contract.

Every case is a static value. A call object mutated after the binding check
and before the tool reads it cannot be written down here; that temporal
boundary is outside the package ceiling (see README.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def canonical(call: dict) -> str:
    """Canonical content of a call: member order irrelevant, array order and
    scalar kinds significant. ``sort_keys`` orders members; ``separators``
    removes whitespace; bool stays distinct from int under json."""
    return json.dumps(
        {"tool": call["tool"], "arguments": call["arguments"], "tenant": call["tenant"], "target": call["target"]},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )


def evaluate(case: dict) -> list[dict]:
    authorization = case["authorization"]
    integrity = authorization.get("integrity", "intact")
    bound = canonical(authorization)
    consumed = False
    outcomes = []
    for presented in case["dispatches"]:
        if integrity != "intact":
            outcomes.append({"outcome": "REFUSED", "refusal_class": "authority_unverifiable"})
            continue
        if canonical(presented) != bound:
            outcomes.append({"outcome": "REFUSED", "refusal_class": "call_mismatch"})
            continue
        if presented.get("actor") != authorization.get("actor"):
            outcomes.append({"outcome": "REFUSED", "refusal_class": "principal_mismatch"})
            continue
        if consumed:
            outcomes.append({"outcome": "REFUSED", "refusal_class": "authority_consumed"})
            continue
        consumed = True
        outcomes.append({"outcome": "DISPATCHED", "refusal_class": None})
    return outcomes


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("fixtures.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    results, failures = [], []
    for case in doc["cases"]:
        actual = evaluate(case)
        expected = case["expected"]["outcomes"]
        ok = actual == expected
        results.append({"id": case["id"], "claim_id": case["claim_id"], "ok": ok, "actual": actual, "expected": expected,
                        "claim_result": case["expected"]["claim_result"] if ok else "CONTRADICTED"})
        if not ok:
            failures.append(case["id"])
    print(json.dumps({"schema_version": doc["schema_version"], "results": results, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
