#!/usr/bin/env python3
"""Zero-dependency reference verifier for REMORA effect-evidence-v2 fixtures.

This file imports no REMORA code. A cross-project verifier should implement
the contract independently rather than treating this program as an oracle.

v2 keeps the effect-evidence-v1.1 comparison unchanged and adds the three
facts the v1 input had no field for (issue #918, Probity's invocation_axes
corpus): the call the bundle is bound to, the decision captured for the
invocation, and who observed. Each case therefore names

* ``invocation``: the call under judgement, as ``sha256:<hex>``;
* ``decision``: the captured decision, bound to a call, or ``null``;
* ``bundle_call``: the call the dispatch, report and observation are bound to;
* ``executor``: who proposed and who executed, and their control domain;
* ``observer``: who read the system of record, from which control domain,
  and whether its credential there is read-only; or ``null``.

The lineage is checked before the comparison, in this order: the decision
(dispatchable, approved where it must be, bound to the invocation), then the
bundle's call binding. Independence is derived from the observer's and the
executor's facts, never declared. Only an independent observation of the
declared delta raises the state to EFFECT_VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RULES = ("exact", "present", "absent", "version_increment", "hash")
#: Decisions that may lead to a dispatch, and whether an approval must stand
#: between the decision and the dispatch.
DISPATCHABLE = {"accept": False, "verify": True, "escalate": True}
DENYING = ("abstain", "deny", "reject", "rejected")


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
    """The effect-evidence-v1.1 comparison, unchanged."""
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
            if not (type(have) is int and type(want) is int) or not have > want:
                return "EFFECT_MISMATCH"
        elif rule == "hash":
            if _digest(have) != str(want):
                return "EFFECT_MISMATCH"
        elif rule == "exact":
            if not strict_equal(want, have):
                return "EFFECT_MISMATCH"
    return "EFFECT_VERIFIED"


def lineage_status(case: dict) -> str:
    """BOUND, or the first lineage fact that fails, in the contract's order."""
    decision = case.get("decision") or {}
    verdict = str(decision.get("verdict") or "").lower()
    if verdict in DENYING:
        return "dispatched_after_deny"
    if verdict not in DISPATCHABLE:
        return "assessment_decision_unknown"
    if DISPATCHABLE[verdict] and decision.get("approved") is not True:
        return "dispatched_without_approval"
    if decision.get("call") != case["invocation"]:
        return "dispatch_not_authorized"
    if case["bundle_call"] != case["invocation"]:
        return "tool_call_hash_mismatch"
    return "BOUND"


def vantage(case: dict) -> str:
    """Derived from facts: an executor, or anyone who can write, is not
    independent; the same or an undeclared control domain is not established."""
    observer = case.get("observer")
    if observer is None:
        return "not_established"
    executor = case["executor"]
    if observer["id"] in (executor["proposed_by"], executor["executed_by"]):
        return "not_independent"
    if observer.get("read_only") is not True:
        return "not_independent"
    executor_domain = executor.get("control_domain") or observer["control_domain"]
    if observer["control_domain"] != executor_domain:
        return "independent"
    return "not_established"


def evaluate(case: dict) -> dict:
    if case["dispatch"]["outcome"] == "REFUSED":
        return {"lineage_status": "NOT_EVALUATED", "effect_status": "NOT_EVALUATED",
                "vantage": "NOT_EVALUATED", "highest_established_state": "NOT_DISPATCHED"}
    lineage = lineage_status(case)
    if lineage == "tool_call_hash_mismatch":
        # The dispatch, report and observation are about another call: none of
        # it is evidence about this invocation.
        return {"lineage_status": lineage, "effect_status": "NOT_EVALUATED",
                "vantage": "NOT_EVALUATED", "highest_established_state": "NOT_DISPATCHED"}
    state = "DISPATCHED"
    report = case.get("execution_report")
    if report is not None and report.get("status") == "success":
        state = "EXECUTION_REPORTED_SUCCESS"
    if lineage != "BOUND":
        # A dispatch the decision did not allow: no effect is attested to.
        return {"lineage_status": lineage, "effect_status": "NOT_EVALUATED",
                "vantage": "NOT_EVALUATED", "highest_established_state": state}
    seen_from = vantage(case)
    try:
        status = effect_status(case.get("postcondition"), case.get("observed"))
    except ValueError:
        return {"lineage_status": lineage, "effect_status": "CONTRACT_REJECTED",
                "vantage": seen_from, "highest_established_state": state}
    if status == "EFFECT_VERIFIED" and seen_from == "independent":
        state = "EFFECT_VERIFIED"
    elif status == "EFFECT_MISMATCH":
        # A contradicted report is not supported, whoever contradicts it.
        state = "DISPATCHED"
    return {"lineage_status": lineage, "effect_status": status,
            "vantage": seen_from, "highest_established_state": state}


OUTCOME_KEYS = ("lineage_status", "effect_status", "vantage", "highest_established_state")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("fixtures.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    results, failures = [], []
    for case in doc["cases"]:
        actual = evaluate(case)
        expected = {k: case["expected"][k] for k in OUTCOME_KEYS}
        ok = actual == expected
        results.append({"id": case["id"], "claim_id": case["claim_id"], "ok": ok, "actual": actual, "expected": expected,
                        "claim_result": case["expected"]["claim_result"] if ok else "CONTRADICTED"})
        if not ok:
            failures.append(case["id"])
    print(json.dumps({"schema_version": doc["schema_version"], "results": results, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
