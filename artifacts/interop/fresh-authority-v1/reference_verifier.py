#!/usr/bin/env python3
"""Zero-dependency reference verifier for REMORA fresh-authority-v1 fixtures.

This file imports no REMORA code. It re-evaluates an authorization at the
moment of each presentation: validity window, revocation of the signing key,
the observation it was decided for, single-use redemption, and at dispatch the
policy bundle and tool definition in force. A cross-project verifier should
implement the contract independently rather than treating this program as an
oracle.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def _t(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _window(authorization: dict, at: str) -> str | None:
    now = _t(at)
    if now < _t(authorization["issued_at"]):
        return "authority_not_yet_valid"
    if now >= _t(authorization["expires_at"]):
        return "authority_expired"
    return None


def evaluate_grant(case: dict) -> list[dict]:
    authorization = case["authorization"]
    consumed = False
    outcomes = []
    for presentation in case["presentations"]:
        if authorization.get("integrity", "intact") != "intact":
            reason = "authority_unverifiable"
        elif authorization["kid"] in presentation.get("revoked_kids", []):
            reason = "authority_revoked"
        elif authorization["decision"] != "accept":
            reason = "decision_not_accept"
        else:
            reason = _window(authorization, presentation["at"])
            if reason is None and presentation["observation"] != authorization["observation"]:
                reason = "authority_stale"
            if reason is None and consumed:
                reason = "authority_consumed"
        if reason is None:
            consumed = True
            outcomes.append({"outcome": "ADMITTED", "refusal_class": None})
        else:
            outcomes.append({"outcome": "REFUSED", "refusal_class": reason})
    return outcomes


def evaluate_dispatch(case: dict) -> list[dict]:
    authorization = case["authorization"]
    dispatch = case["dispatch"]
    if authorization.get("integrity", "intact") != "intact":
        reason = "authority_unverifiable"
    else:
        reason = _window(authorization, dispatch["at"])
        if reason is None and (
            dispatch["policy_bundle"] != authorization["policy_bundle"]
            or dispatch["toolspec_hash"] != authorization["toolspec_hash"]
            or dispatch["toolspec_version"] != authorization["toolspec_version"]
        ):
            reason = "authority_stale"
    if reason is None:
        return [{"outcome": "DISPATCHED", "refusal_class": None}]
    return [{"outcome": "REFUSED", "refusal_class": reason}]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("fixtures.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    results, failures = [], []
    for case in doc["cases"]:
        actual = evaluate_grant(case) if case["stage"] == "grant" else evaluate_dispatch(case)
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
