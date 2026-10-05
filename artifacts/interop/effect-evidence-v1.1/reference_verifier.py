#!/usr/bin/env python3
"""Zero-dependency reference verifier for REMORA effect-evidence-v1.1 fixtures.

This file imports no REMORA code. It computes the effect status from the
declared delta and the observed object, and the highest state the evidence
supports. A cross-project verifier should implement the contract
independently rather than treating this program as an oracle.

Differences from effect-evidence-v1, each found by a probe that the v1
verifier passed by accident:

* a declared field that the observed object does not carry is a mismatch
  under ``exact`` and ``hash``, even when the declared value is ``null``;
  ``observed.get(name)`` read both as ``None``;
* a comparison rule outside the vocabulary, or a rule for a field the
  contract does not declare, rejects the contract (``ValueError`` here,
  ``CONTRACT_REJECTED`` in the fixture vocabulary) instead of falling back
  to ``exact`` or being ignored;
* ``exact`` keeps null, bool, int, float and string apart at every depth,
  so ``1`` is not ``1.0`` and ``{"a": true}`` is not ``{"a": 1}``;
* ``version_increment`` compares integers only, on both sides. The v1
  verifier coerced with ``int()``, so ``"4"``, ``true`` and ``4.0`` all
  counted as versions.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RULES = ("exact", "present", "absent", "version_increment", "hash")


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def strict_equal(left, right) -> bool:
    """Equality that keeps null, bool, int, float and str apart at every depth."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(strict_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(strict_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return False
    return type(left) is type(right) and left == right


def validate_rules(expected: dict, rules: dict) -> None:
    """Refuse a rule map that would change meaning without saying so."""
    unknown = sorted(r for r in rules.values() if r not in RULES)
    if unknown:
        raise ValueError(f"unsupported_comparison_rule: {unknown}")
    undeclared = sorted(set(rules) - set(expected))
    if undeclared:
        raise ValueError(f"comparison_rule_for_undeclared_field: {undeclared}")


def effect_status(postcondition: dict | None, observed: dict | None) -> str:
    """The effect status, or ``ValueError`` for a rule map the contract does
    not define. The rule map is checked before anything else, so a rejected
    contract is rejected whether or not the reader saw the object."""
    if postcondition is None:
        return "NOT_EVALUATED"
    expected = postcondition["expected_fields"]
    rules = postcondition.get("comparison_rules", {})
    validate_rules(expected, rules)
    if not expected:
        return "EFFECT_UNSUPPORTED"
    if observed is None:
        return "EFFECT_UNOBSERVABLE"
    for name, want in expected.items():
        rule = rules.get(name, "exact")
        if rule in ("exact", "hash", "present") and name not in observed:
            return "EFFECT_MISMATCH"
        have = observed.get(name)
        if rule == "absent":
            if name in observed:
                return "EFFECT_MISMATCH"
        elif rule == "version_increment":
            # Integers only, on both sides; bool is not an integer here.
            if not (type(have) is int and type(want) is int) or not have > want:
                return "EFFECT_MISMATCH"
        elif rule == "hash":
            if _digest(have) != str(want):
                return "EFFECT_MISMATCH"
        elif rule == "exact":
            if not strict_equal(want, have):
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
    try:
        status = effect_status(case.get("postcondition"), case.get("observed"))
    except ValueError:
        # A rejected contract is never evaluated; the state stays where it was.
        return {"effect_status": "CONTRACT_REJECTED", "highest_established_state": state}
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
