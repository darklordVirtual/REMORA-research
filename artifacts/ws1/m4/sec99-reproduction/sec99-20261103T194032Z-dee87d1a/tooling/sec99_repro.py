#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reproduce NEGATIVE_RESULTS §99 against a rebuilt OT pilot, over HTTP.

Two processes from the same image: the pilot's API in the authority domain
(default role) and a second process in the executor domain. The script holds
what the 2026-11-02 review held, an agent token, plus the pilot's lease HMAC
key, and tries the original attack and the repaired boundary's other cases.
Every case states its expectation; a case that does not behave as expected is
a FAILURE. Tokens and keys never reach the output.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

AUTHORITY = os.environ.get("SEC99_AUTHORITY_URL", "http://127.0.0.1:8080")
EXECUTOR = os.environ.get("SEC99_EXECUTOR_URL", "http://127.0.0.1:8082")
TOKENS = {name: os.environ.get(var, "") for name, var in (
    ("agent", "OT_TOKEN_AGENT"), ("approver", "OT_TOKEN_APPROVER"),
    ("supervisor", "OT_TOKEN_SUPERVISOR"), ("viewer", "OT_TOKEN_VIEWER"),
    ("hop", "OT_TOKEN_HOP"))}
LEASE_KEY = os.environ.get("OT_LEASE_SIGNING_KEY", "")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "sec99-out")

# The original review moved a valve and a setpoint. The reproduction asks for
# a read: the property under test is who may dispatch under a lease, and a
# read leaves the simulated plant where it was.
CALL = {"tool_name": "read_sensor", "arguments": {"sensor_id": "PT-101"},
        "target_environment": "prod"}
TENANT = "ot-pilot"


def call(method: str, base: str, path: str, token: str, body: Any = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as err:
        raw = err.read()
        status = err.code
    try:
        return status, json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return status, raw.decode(errors="replace")[:500]


def lease(bundle_hash: str, *, proposal_id: str, grant_jti: str) -> dict[str, Any]:
    os.environ["REMORA_LEASE_SIGNING_KEY"] = LEASE_KEY
    for var in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"):
        os.environ.pop(var, None)
    from remora.execution.dispatch import issue_execution_lease

    return issue_execution_lease(
        tenant=TENANT, principal="ot-agent", tool_call=SimpleNamespace(**CALL),
        semantic={"tool_contract_bundle_hash": "", "intent_authority_hash": ""},
        now=datetime.now(UTC), policy_bundle_hash=bundle_hash,
        proposal_id=proposal_id, grant_jti=grant_jti).to_dict()


def dispatch(base: str, token_name: str, body_lease: dict[str, Any]) -> tuple[int, Any]:
    return call("POST", base, "/v1/execution/dispatch-leased", TOKENS[token_name],
                {"lease": body_lease, "tool_call": CALL, "tenant_id": TENANT})


def audit(base: str) -> tuple[int, Any]:
    return call("GET", base, "/v1/execution/audit/verify", TOKENS["viewer"])


def redact(obj: Any) -> Any:
    secrets = {v for v in TOKENS.values() if v} | ({LEASE_KEY} if LEASE_KEY else set())
    text = json.dumps(obj, default=str)
    for s in secrets:
        text = text.replace(s, "<redacted>")
    return json.loads(text)


def main() -> int:
    missing = [k for k, v in TOKENS.items() if not v]
    if missing or not LEASE_KEY:
        print("missing credentials:", missing, "lease key" if not LEASE_KEY else "")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    failures = 0

    def record(case_id: str, title: str, expected: str, observed: dict[str, Any], ok: bool) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        cases.append({"id": case_id, "title": title, "expected": expected,
                      "observed": redact(observed), "result": "PASS" if ok else "FAILURE"})
        print(f"[{'ok  ' if ok else 'FAIL'}] {case_id} {title}")

    status, policy = call("GET", AUTHORITY, "/v1/policy/version", TOKENS["viewer"])
    bundle = policy["policy_hash"] if status == 200 else ""
    _, exec_policy = call("GET", EXECUTOR, "/v1/policy/version", TOKENS["viewer"])

    _, audit_before = audit(AUTHORITY)

    linked = lease(bundle, proposal_id="prop-fabricated-1", grant_jti="grant-fabricated-1")
    unlinked = lease(bundle, proposal_id="", grant_jti="")

    # N1: the original attack. The authority process must not serve the route.
    for token_name in ("agent", "approver", "supervisor"):
        for kind, body in (("unlinked", unlinked), ("linked", linked)):
            st, resp = dispatch(AUTHORITY, token_name, body)
            record(f"N1-{token_name}-{kind}",
                   f"self-signed {kind} lease on the authority domain with the {token_name} token",
                   "HTTP 404; nothing dispatched",
                   {"status": st, "body": resp}, st == 404)

    # N2: the agent token on the executor domain.
    st, resp = dispatch(EXECUTOR, "agent", linked)
    record("N2-agent-executor", "agent (operator) token on the executor domain",
           "HTTP 403; the operator role holds no dispatch capability",
           {"status": st, "body": resp}, st == 403)

    # N3: the executor refuses a validly signed lease without proposal/grant linkage.
    st, resp = dispatch(EXECUTOR, "hop", unlinked)
    body = (resp or {}).get("tool_execution", {}) if isinstance(resp, dict) else {}
    record("N3-hop-unlinked", "dispatch_hop token, validly signed lease, no proposal or grant",
           "HTTP 200 with executed=false, refusal_reason=lease_unlinked",
           {"status": st, "body": resp},
           st == 200 and body.get("executed") is False and body.get("refusal_reason") == "lease_unlinked")

    # P1: an admitted dispatch is recorded before and after the tool runs.
    _, exec_audit_before = audit(EXECUTOR)
    st, resp = dispatch(EXECUTOR, "hop", linked)
    body = (resp or {}).get("tool_execution", {}) if isinstance(resp, dict) else {}
    _, exec_audit_after = audit(EXECUTOR)
    _, auth_audit_after = audit(AUTHORITY)
    record("P1-hop-linked", "dispatch_hop token, validly signed lease with non-empty linkage",
           "either executed=true with lease_dispatch_admitted and lease_dispatch_result on the "
           "chain, or a refusal naming its reason; never a silent dispatch",
           {"status": st, "body": resp,
            "executor_audit_before": exec_audit_before, "executor_audit_after": exec_audit_after,
            "authority_audit_after": auth_audit_after},
           st == 200 and isinstance(body, dict) and "executed" in body)
    linkage_note = ("The linkage values are fabricated; the executor does not look them up. "
                    "An executed=true here is the §99 limitation 'linked means non-empty', "
                    "not authenticated source linkage (RMR-SEC-0020 custody split).")

    # N4: a tampered lease (call changed after signing) is refused.
    tampered = dict(linked)
    tampered_call = dict(CALL, arguments={"sensor_id": "TT-204"})
    st, resp = call("POST", EXECUTOR, "/v1/execution/dispatch-leased", TOKENS["hop"],
                    {"lease": tampered, "tool_call": tampered_call, "tenant_id": TENANT})
    body = (resp or {}).get("tool_execution", {}) if isinstance(resp, dict) else {}
    record("N4-hop-tampered-call", "the call under a valid lease is changed after signing",
           "refused (409 or executed=false); nothing runs",
           {"status": st, "body": resp},
           st == 409 or (st == 200 and body.get("executed") is False))

    # N5: the same lease presented again (replay).
    st, resp = dispatch(EXECUTOR, "hop", linked)
    body = (resp or {}).get("tool_execution", {}) if isinstance(resp, dict) else {}
    record("N5-hop-replay", "the admitted lease from P1 is presented a second time",
           "refused (409 or executed=false); a lease nonce is consumed once",
           {"status": st, "body": resp},
           st == 409 or (st == 200 and body.get("executed") is False))

    _, audit_after = audit(AUTHORITY)
    manifest = {
        "run_id": OUT.name,
        "recorded_at": datetime.now(UTC).isoformat(),
        "authority_url": AUTHORITY, "executor_url": EXECUTOR,
        "policy_version_authority": redact(policy),
        "policy_version_executor": redact(exec_policy),
        "authority_audit_verify_before": redact(audit_before),
        "authority_audit_verify_after": redact(audit_after),
        "call_under_test": CALL,
        "p1_linkage_note": linkage_note,
        "cases_total": len(cases), "failures": failures,
    }
    (OUT / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (OUT / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\ncases: {len(cases)}  failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
