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
FIXTURES = BASE / "fixtures.json"
TEST_SEED = "c3" * 32
OTHER_SEED = "d4" * 32
TRANSPORT_REVISION = "aeoess/federation-port@92d5078af3bbd3610ce4901378e913d5f370a68b"
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


def seal() -> None:
    path = ADAPTER / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifact"]["digest"] = artifact_digest(ADAPTER, manifest["artifact"]["files"])
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")


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
    if args.check:
        manifest = json.loads((ADAPTER / "manifest.json").read_text(encoding="utf-8"))
        problems = []
        if manifest["artifact"]["digest"] != artifact_digest(ADAPTER, manifest["artifact"]["files"]):
            problems.append("adapter manifest digest is stale (run --seal)")
        if not FIXTURES.exists() or FIXTURES.read_text(encoding="utf-8") != _render():
            problems.append("fixtures.json does not match the code (run --write)")
        for problem in problems:
            print(f"[FAIL] {problem}")
        if not problems:
            print("[PASS] federation-port/v0 fixtures and adapter seal match the code")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
