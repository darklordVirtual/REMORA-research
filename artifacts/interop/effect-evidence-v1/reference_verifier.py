#!/usr/bin/env python3
"""Zero-dependency reference verifier for REMORA effect-evidence-v1 fixtures.

This file imports no REMORA code. It computes the effect status from the
declared delta and the observed object, and the highest state the evidence
supports. A cross-project verifier should implement the contract
independently rather than treating this program as an oracle.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def effect_status(postcondition: dict | None, observed: dict | None) -> str:
    if postcondition is None:
        return "NOT_EVALUATED"
    expected = postcondition["expected_fields"]
    if not expected:
        return "EFFECT_UNSUPPORTED"
    if observed is None:
        return "EFFECT_UNOBSERVABLE"
    rules = postcondition.get("comparison_rules", {})
    for name, want in expected.items():
        rule = rules.get(name, "exact")
        have = observed.get(name)
        if rule == "present":
            if name not in observed:
                return "EFFECT_MISMATCH"
        elif rule == "absent":
            if name in observed:
                return "EFFECT_MISMATCH"
        elif rule == "version_increment":
            try:
                if have is None or not int(have) > int(want):
                    return "EFFECT_MISMATCH"
            except (TypeError, ValueError):
                return "EFFECT_MISMATCH"
        elif rule == "hash":
            if _digest(have) != str(want):
                return "EFFECT_MISMATCH"
        else:
            if isinstance(have, bool) != isinstance(want, bool) or have != want:
                return "EFFECT_MISMATCH"
    return "EFFECT_VERIFIED"


def evaluate(case: dict) -> dict:
    dispatch = case["dispatch"]["outcome"]
    if dispatch == "REFUSED":
        return {"effect_status": "NOT_EVALUATED", "highest_established_state": "NOT_DISPATCHED"}
    state = "DISPATCHED"
    report = case.get("execution_report")
    if report is not None and report.get("status") == "success":
        state = "EXECUTION_REPORTED_SUCCESS"
    status = effect_status(case.get("postcondition"), case.get("observed"))
    if status == "EFFECT_VERIFIED":
        state = "EFFECT_VERIFIED"
    elif status == "EFFECT_MISMATCH":
        state = "DISPATCHED"
    return {"effect_status": status, "highest_established_state": state}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("fixtures.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    results, failures = [], []
    for case in doc["cases"]:
        actual = evaluate(case)
        expected = {k: case["expected"][k] for k in ("effect_status", "highest_established_state")}
        ok = actual == expected
        results.append({"id": case["id"], "claim_id": case["claim_id"], "ok": ok, "actual": actual, "expected": expected,
                        "claim_result": case["expected"]["claim_result"] if ok else "CONTRADICTED"})
        if not ok:
            failures.append(case["id"])
    print(json.dumps({"schema_version": doc["schema_version"], "results": results, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
