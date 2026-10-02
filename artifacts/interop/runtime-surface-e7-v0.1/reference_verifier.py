#!/usr/bin/env python3
"""Zero-dependency reference verifier for REMORA E7 v0.1 fixtures.

This file intentionally imports no REMORA code. A cross-project verifier should
implement the contract independently rather than treating this program as an
oracle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def evaluate_surface(case: dict) -> dict:
    reasons = []
    if case["runtime_identity"] != case["expected_runtime_identity"]:
        reasons.append("runtime_identity_mismatch")
    if case["observation_source"] != "agent-runtime":
        reasons.append("observer_not_agent_runtime")
    if reasons:
        return {"surface_verdict": "NOT_ESTABLISHED", "claim_result": "NOT_ESTABLISHED", "reasons": reasons}

    if not case["complete"]:
        reasons.append("surface_incomplete")
    if any(t.get("offered_to_agent") is None or t.get("callable_at_dispatch") is None for t in case["tools"]):
        reasons.append("tool_visibility_unknown")

    callable_tools = {
        t["tool_id"]: t
        for t in case["tools"]
        if t.get("offered_to_agent") is True or t.get("callable_at_dispatch") is True
    }
    governed = case["governed_tools"]
    unexpected = sorted(set(callable_tools) - set(governed))
    missing = sorted(set(governed) - set(callable_tools)) if case["complete"] and not reasons else []
    changed = sorted(
        name for name, tool in callable_tools.items()
        if name in governed and tool.get("toolspec_hash") is not None
        and tool["toolspec_hash"] != governed[name]
    )

    if unexpected or missing or changed:
        out = {"surface_verdict": "MISMATCH", "claim_result": "CONTRADICTED"}
        if unexpected:
            out["unexpected_tools"] = unexpected
        if missing:
            out["missing_tools"] = missing
        if changed:
            out["identity_mismatches"] = changed
        return out

    if any(t.get("toolspec_hash") is None for t in callable_tools.values()):
        reasons.append("toolspec_identity_unknown")
    if reasons:
        return {"surface_verdict": "NOT_ESTABLISHED", "claim_result": "NOT_ESTABLISHED", "reasons": reasons}
    return {"surface_verdict": "MATCHED_OBSERVATION", "claim_result": "ESTABLISHED"}


def evaluate_effect_path(case: dict) -> dict:
    paths = case.get("alternative_effect_paths") or []
    if paths:
        return {
            "claim_id": "exclusive_effect_path",
            "claim_result": "CONTRADICTED",
            "reason": "alternative_effect_path_observed",
        }
    return {
        "claim_id": "exclusive_effect_path",
        "claim_result": "ESTABLISHED" if case.get("path_inventory_complete") is True else "NOT_ESTABLISHED",
        "reason": "complete_path_inventory_no_alternative" if case.get("path_inventory_complete") is True else "path_inventory_incomplete",
    }


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("fixtures.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    failures = []
    results = []
    for case in doc["cases"]:
        actual = evaluate_surface(case) if case["kind"] == "surface" else evaluate_effect_path(case)
        expected = case["expected"]
        ok = all(actual.get(k) == v for k, v in expected.items())
        results.append({"id": case["id"], "ok": ok, "actual": actual, "expected": expected})
        if not ok:
            failures.append(case["id"])
    print(json.dumps({"schema_version": doc["schema_version"], "results": results, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
