#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Fixtures for REMORA's federation-port/v0 adapter (Federation Bridge, Mode A).

Writes ``artifacts/interop/federation-port-v0/fixtures.json``: signed REMORA
evidence for a small set of authorizations, each with the federation-port
request it authorizes, the evaluation instant, the claim results the adapter
must return and the projection records the bridge produces. The keys are test
keys, published so the fixtures are checkable; they are used nowhere else.

``--seal`` writes the adapter manifest's artifact digest (federation-port/v0
section 3). ``--check`` regenerates in memory and fails on any difference.

    python scripts/build_federation_port_v0_fixtures.py --seal --write
    python scripts/build_federation_port_v0_fixtures.py --check
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.crypto import SignatureDomain, SigningKey  # noqa: E402
from remora.federation import (  # noqa: E402
    NativeFederationAction,
    load_capabilities,
    load_projection_map,
)
from remora.federation.transports.federation_port_v0 import (  # noqa: E402
    FederationPortV0Transport,
    artifact_digest,
)

BASE = ROOT / "artifacts" / "interop" / "federation-port-v0"
ADAPTER = ROOT / "integrations" / "federation-port" / "remora-adapter"
REPORT_COMPONENT = ROOT / "integrations" / "federation-port" / "remora-report-result"
FIXTURES = BASE / "fixtures.json"
REPORT_FIXTURES = BASE / "report-results.json"
TEST_SEED = "c3" * 32
OTHER_SEED = "d4" * 32
#: Test key for REMORA/FEDERATION-RESULT/v1 results; published, used nowhere else.
RESULT_SEED = "b8" * 32
RESULT_OTHER_SEED = "a9" * 32
COMPONENTS = (ADAPTER, REPORT_COMPONENT)
TRANSPORT_REVISION = "aeoess/federation-port@3a2f6ce405d1c4f86ac8f2591e136deb5dfbb333"
VALID_UNTIL = "2026-10-07T12:05:00.000Z"
NOW = "2026-10-07T12:01:00.000Z"
LATE = "2026-10-07T12:05:00.001Z"
REFUND = {"payment_id": "pay_A", "amount_minor": 4000, "currency": "EUR"}


def _key(seed: str) -> SigningKey:
    return SigningKey.from_text(seed, [SignatureDomain.FEDERATION_ACTION])


def _native(op: str, approval: str, arguments: dict, principal: str = "agent-A",
            tenant: str = "tenant-a") -> NativeFederationAction:
    return NativeFederationAction(
        operation_id=op, workflow_id="refund", tool="refund", arguments=arguments,
        authority={"authorization_id": approval, "principal": principal, "tenant": tenant,
                   "valid_until": VALID_UNTIL, "lease_id": f"lease-{op}"},
        execution_context={"policy_digest": "sha256:" + "1" * 64,
                           "toolspec_digest": "sha256:" + "2" * 64},
        evidence={"authorization_digest": "sha256:" + "3" * 64})


def _transport(seed: str = TEST_SEED) -> FederationPortV0Transport:
    manifest = json.loads((ADAPTER / "manifest.json").read_text(encoding="utf-8"))
    return FederationPortV0Transport(
        capabilities=load_capabilities(BASE / "capabilities.yaml"),
        projection_map=load_projection_map(BASE / "projection-map.yaml"),
        signing_key=_key(seed), adapter_digest=manifest["artifact"]["digest"],
        remora_revision="fixture", transport_revision=TRANSPORT_REVISION)


def _case(name: str, native: NativeFederationAction, now: str, expected: dict[str, str],
          seed: str = TEST_SEED, note: str = "") -> dict[str, Any]:
    projected = _transport(seed).project_action(native)
    return {
        "name": name, "note": note, "now": now,
        "request": projected.request,
        "evidence_b64": base64.b64encode(projected.evidence).decode("ascii"),
        "native_action_digest": native.digest(),
        "native_arguments_digest": native.canonical.digest,
        "expected_claims": expected,
        "projection_records": projected.projection_records,
    }


ALL_ESTABLISHED = {"remora.authorization_integrity": "established",
                   "remora.port_v0.bound_action": "established",
                   "remora.authorization_unexpired": "established"}


def build() -> dict[str, Any]:
    test_public = _key(TEST_SEED).verification_key().public_bytes.hex()
    cases = [
        _case("valid", _native("op-valid", "apr-valid", dict(REFUND)), NOW, ALL_ESTABLISHED,
              note="admitted; exact_call_binding projects NARROWED to remora.port_v0.bound_action"),
        _case("lossy_float", _native("op-lossy", "apr-lossy", {**REFUND, "amount_minor": 4000.0}),
              NOW, ALL_ESTABLISHED,
              note="native 4000.0 (float) and 4000 (int) have different native digests; V0 "
                   "carries both as 4000, so bound_action holds and the projection records "
                   "lexical_numeric_type as lost"),
        _case("other_principal", _native("op-principal", "apr-principal", dict(REFUND),
                                         principal="agent-B"), NOW, ALL_ESTABLISHED,
              note="same action under another principal: V0 cannot tell, so principal_binding "
                   "stays NOT_ESTABLISHED"),
        _case("expired", _native("op-expired", "apr-expired", dict(REFUND)), LATE,
              {**ALL_ESTABLISHED, "remora.authorization_unexpired": "not_established"},
              note="one millisecond past valid_until"),
        _case("untrusted_key", _native("op-untrusted", "apr-untrusted", dict(REFUND)), NOW,
              {"remora.authorization_integrity": "not_established",
               "remora.port_v0.bound_action": "not_established",
               "remora.authorization_unexpired": "not_established"},
              seed=OTHER_SEED, note="signed with a key the customer did not pin"),
    ]
    return {
        "schema_version": "remora-federation-port-v0-fixtures-v1",
        "transport_revision": TRANSPORT_REVISION,
        "component": "remora-research/authorization-evidence",
        "test_keys": {"signing_seed_hex": TEST_SEED, "public_key_hex": test_public,
                      "note": "test keys only, published so the fixtures are checkable"},
        "cases": cases,
    }


def _render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


# -- report-specific acceptance (LATE / LATE-CONFLICT) --------------------------------------
# Local synthetic reproductions of the semantics of Rul1an's public LATE and LATE-CONFLICT
# fixtures (aeoess/agent-governance-vocabulary#177, issuecomment-6047105582); no material
# copied. Each operation has provider deliveries and two client reports; the native verifier
# answers definite_support per report.
REPORT_CASES: dict[str, dict[str, Any]] = {
    "LATE": {"deliveries": [{"at": 2, "result": "succeeded"}],
             "reports": [{"report_id": "report-1", "at": 1}, {"report_id": "report-2", "at": 3}],
             "expected": {"report-1": "CONTRADICTED", "report-2": "ESTABLISHED"}},
    "LATE-CONFLICT": {"deliveries": [{"at": 1, "result": "succeeded"},
                                     {"at": 3, "result": "failed"}],
                      "reports": [{"report_id": "report-1", "at": 2},
                                  {"report_id": "report-2", "at": 4}],
                      "expected": {"report-1": "ESTABLISHED", "report-2": "CONTRADICTED"}},
}


def _definite_support(deliveries: list[dict[str, Any]], report: Any) -> Any:
    from remora.federation import NativeResult

    seen = [d for d in deliveries if d["at"] <= report.body["reported_at"]]
    if not seen:
        return NativeResult("CONTRADICTED", "result_not_delivered_at_report_time")
    if max(seen, key=lambda d: d["at"])["result"] != report.body["relies_on"]:
        return NativeResult("CONTRADICTED", "conflicting_result_delivered")
    return NativeResult("ESTABLISHED", "required_result_delivered")


def build_reports() -> dict[str, Any]:
    from remora.federation import Report, select_report
    from remora.federation.results import result_document, result_evidence

    key = SigningKey.from_text(RESULT_SEED, [SignatureDomain.FEDERATION_RESULT])
    other = SigningKey.from_text(RESULT_OTHER_SEED, [SignatureDomain.FEDERATION_RESULT])
    cases = []
    for name, case in REPORT_CASES.items():
        reports = [Report(operation_id=f"op-{name.lower()}", report_id=r["report_id"],
                          sequence=i + 1, body={"reported_at": r["at"], "relies_on": "succeeded"})
                   for i, r in enumerate(case["reports"])]
        results = []
        for report in reports:
            selected, selection = select_report(reports, report_id=report.report_id)
            document = result_document(
                native_claim="definite_support", subject=selected.subject(),
                selection=selection, native_result=_definite_support(case["deliveries"], selected))
            results.append({"report_id": report.report_id, "report_digest": report.digest,
                            "native_status": document["native_result"]["status"],
                            "native_reason": document["native_result"]["reason_code"],
                            "evidence_b64": base64.b64encode(
                                result_evidence(document, key)).decode("ascii")})
        foreign = result_evidence(result_document(
            native_claim="definite_support", subject=reports[0].subject(),
            selection=select_report(reports, report_id=reports[0].report_id)[1],
            native_result=_definite_support(case["deliveries"], reports[0])), other)
        cases.append({"name": name, "operation_id": reports[0].operation_id,
                      "expected": case["expected"], "results": results,
                      "untrusted_result_b64": base64.b64encode(foreign).decode("ascii")})
    return {
        "schema_version": "remora-federation-port-v0-report-fixtures-v1",
        "component": "remora-research/report-result",
        "native_claim": "definite_support",
        "attribution": "Semantics after Rul1an's public synthetic LATE and LATE-CONFLICT fixtures "
                       "(aeoess/agent-governance-vocabulary#177, issuecomment-6047105582); "
                       "local reproduction, no material copied",
        "test_keys": {"result_signing_seed_hex": RESULT_SEED,
                      "result_public_key_hex": key.verification_key().public_bytes.hex(),
                      "note": "test keys only, published so the fixtures are checkable"},
        "cases": cases,
    }


def _render_reports() -> str:
    return json.dumps(build_reports(), indent=2, sort_keys=True) + "\n"


def seal() -> None:
    for component in COMPONENTS:
        path = component / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["artifact"]["digest"] = artifact_digest(component, manifest["artifact"]["files"])
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.seal:
        seal()
    if args.write:
        FIXTURES.write_text(_render(), encoding="utf-8", newline="\n")
        REPORT_FIXTURES.write_text(_render_reports(), encoding="utf-8", newline="\n")
    if args.check:
        problems = []
        for component in COMPONENTS:
            manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
            if manifest["artifact"]["digest"] != artifact_digest(component,
                                                                  manifest["artifact"]["files"]):
                problems.append(f"{component.name} manifest digest is stale (run --seal)")
        if not FIXTURES.exists() or FIXTURES.read_text(encoding="utf-8") != _render():
            problems.append("fixtures.json does not match the code (run --write)")
        if (not REPORT_FIXTURES.exists()
                or REPORT_FIXTURES.read_text(encoding="utf-8") != _render_reports()):
            problems.append("report-results.json does not match the code (run --write)")
        for problem in problems:
            print(f"[FAIL] {problem}")
        if not problems:
            print("[PASS] federation-port/v0 fixtures and adapter seal match the code")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
