#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Golden vectors for REMORA's signed artifacts (RMR-CR-011).

    vectors/v1/   immutable: the frozen, untagged formats
    vectors/v2/   the domain-separated formats

Each vector carries the key material (test keys only), the signed fields,
the exact payload bytes and the expected signature, so an independent
implementation can check itself without running REMORA.
``tests/test_signature_vectors.py`` recomputes every vector with the
production code and pins the v1 files byte for byte.

``--write v2`` regenerates v2. v1 is never regenerated: the script refuses to
overwrite a v1 file, because a v1 vector that changes no longer describes
what was signed.

Usage::

    python scripts/generate_signature_vectors.py --write v2
    python scripts/generate_signature_vectors.py --check
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VECTORS = ROOT / "vectors"

#: Test keys. Never deployed anywhere; published so the vectors are checkable.
HMAC_KEY = "remora-vector-hmac-key-not-a-secret"
ED25519_SEED = "a1" * 32

_LEASE_FIELDS: dict[str, Any] = {
    "decision": "accept",
    "tenant_id": "tenant-a",
    "actor_identity": "agent-1",
    "tool_name": "wo_close",
    "tool_args_hash": "3" * 64,
    "target_environment": "prod",
    "policy_bundle_hash": "b" * 64,
    "nonce": "00000000-0000-4000-8000-000000000001",
    "issued_at": "2026-10-07T12:00:00+00:00",
    "expires_at": "2026-10-07T12:02:00+00:00",
    "tool_contract_bundle_hash": "",
    "intent_authority_hash": "",
    "toolspec_hash": "c" * 64,
    "toolspec_version": 1,
    "proposal_id": "proposal-1",
    "grant_jti": "00000000-0000-4000-8000-000000000002",
    "runtime_identity_hash": "",
}


def _canonical(fields: dict[str, Any]) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()


def _ed25519_sign(message: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(ED25519_SEED)).sign(message)


def _ed25519_public() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return ed25519.Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(ED25519_SEED)).public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw).hex()


def _keys() -> dict[str, str]:
    return {"hmac_key": HMAC_KEY, "ed25519_seed_hex": ED25519_SEED,
            "ed25519_public_hex": _ed25519_public()}


# -- v1: frozen --------------------------------------------------------------------

def lease_v1() -> dict[str, Any]:
    cases = []
    for alg in ("hmac-sha256", "ed25519"):
        fields = {**_LEASE_FIELDS, "sig_alg": alg, "kid": ""}
        payload = _canonical(fields)
        if alg == "hmac-sha256":
            signature = hmac.new(HMAC_KEY.encode(), payload, hashlib.sha256).hexdigest()
        else:
            signature = _ed25519_sign(payload).hex()
        cases.append({"name": f"lease-v1-{alg}", "signed_fields": fields,
                      "payload": payload.decode(), "signature": signature})
    return {"artifact": "ExecutionLease", "format": "v1",
            "preimage": "canonical JSON (sorted keys, compact), untagged",
            "keys": _keys(), "cases": cases}


def policy_grant_v1() -> dict[str, Any]:
    payload = _canonical({
        "action": "accept",
        "audience": "pep://remora-execution",
        "context_hash": "d" * 64,
        "expires_at": "2026-10-07T12:05:00+00:00",
        "issued_at": "2026-10-07T12:00:00+00:00",
        "issuer": "pdp-1",
        "jti": "00000000-0000-4000-8000-000000000003",
        "kid": "pdp-2026-10",
        "observation_hash": "e" * 64,
        "request_id": "req-1",
    })
    return {"artifact": "PolicyDecisionToken", "format": "v1",
            "preimage": "canonical JSON (sorted keys, compact), untagged; HMAC-SHA256 hex",
            "keys": {"hmac_key": HMAC_KEY},
            "cases": [{"name": "policy-grant-v1-hmac", "payload": payload.decode(),
                       "signature": hmac.new(HMAC_KEY.encode(), payload,
                                             hashlib.sha256).hexdigest()}]}


def audit_v1() -> dict[str, Any]:
    from remora.governance.tenant_chain import compute_entry_hash

    previous = "0" * 64
    cases = []
    for sequence_no, payload in enumerate(({"event": "assessed", "proposal_id": "p-1"},
                                           {"event": "executed", "proposal_id": "p-1"})):
        timestamp = f"2026-10-07T12:00:0{sequence_no}+00:00"
        entry_hash = compute_entry_hash(previous, payload, "tenant-a", sequence_no, timestamp)
        cases.append({
            "name": f"audit-v1-entry-{sequence_no}", "tenant_id": "tenant-a",
            "sequence_no": sequence_no, "timestamp": timestamp, "payload": payload,
            "previous_hash": previous, "entry_hash": entry_hash,
            "signature": hmac.new(HMAC_KEY.encode(), entry_hash.encode(),
                                  hashlib.sha256).hexdigest()})
        previous = entry_hash
    return {"artifact": "TenantAuditChain entry", "format": "v1",
            "preimage": "entry_hash = SHA256(previous || 0x1f || canonical(payload) || 0x1f "
                        "|| tenant || 0x1f || sequence || 0x1f || timestamp); "
                        "signature = HMAC-SHA256(key, entry_hash) hex, untagged",
            "keys": {"hmac_key": HMAC_KEY}, "cases": cases}


# -- v2 ----------------------------------------------------------------------------------

def lease_v2() -> dict[str, Any]:
    from remora.crypto import SignatureDomain, derive_kid, preimage

    fields = {**_LEASE_FIELDS, "sig_alg": "ed25519-domain-v2",
              "kid": derive_kid(bytes.fromhex(_ed25519_public()))}
    payload = _canonical(fields)
    signed = preimage(SignatureDomain.EXECUTION_LEASE, payload)
    return {"artifact": "ExecutionLease", "format": "v2",
            "domain": SignatureDomain.EXECUTION_LEASE.value,
            "preimage": "domain tag || 0x00 || canonical JSON (sorted keys, compact); "
                        "Ed25519, signature base64; kid = 'ed25519-' + sha256(public key)",
            "keys": _keys(),
            "cases": [{"name": "lease-v2-ed25519", "signed_fields": fields,
                       "payload": payload.decode(),
                       "preimage_b64": base64.b64encode(signed).decode(),
                       "signature": base64.b64encode(_ed25519_sign(signed)).decode()}]}


def policy_grant_v2() -> dict[str, Any]:
    from remora.crypto import SignatureDomain, preimage

    payload = _canonical({
        "action": "accept",
        "audience": "pep://remora-execution",
        "context_hash": "d" * 64,
        "expires_at": "2026-10-07T12:05:00+00:00",
        "format": "v2",
        "issued_at": "2026-10-07T12:00:00+00:00",
        "issuer": "pdp-1",
        "jti": "00000000-0000-4000-8000-000000000003",
        "kid": "pdp-2026-10",
        "observation_hash": "e" * 64,
        "request_id": "req-1",
    })
    signed = preimage(SignatureDomain.POLICY_GRANT, payload)
    return {"artifact": "PolicyDecisionToken", "format": "v2",
            "domain": SignatureDomain.POLICY_GRANT.value,
            "preimage": "domain tag || 0x00 || canonical JSON (sorted keys, compact, with "
                        "format=v2); HMAC-SHA256 hex",
            "keys": {"hmac_key": HMAC_KEY},
            "cases": [{"name": "policy-grant-v2-hmac", "payload": payload.decode(),
                       "preimage_b64": base64.b64encode(signed).decode(),
                       "signature": hmac.new(HMAC_KEY.encode(), signed,
                                             hashlib.sha256).hexdigest()}]}


def audit_v2() -> dict[str, Any]:
    """A v1 entry, the AUDIT_VERSION_TRANSITION record, and a v2 entry."""
    from remora.crypto import SignatureDomain
    from remora.governance.audit_signing import entry_signature, transition_payload
    from remora.governance.tenant_chain import compute_entry_hash

    key = HMAC_KEY.encode()
    previous = "0" * 64
    cases = []
    steps = [({"event": "assessed", "proposal_id": "p-1"}, False), (None, True),
             ({"event": "executed", "proposal_id": "p-1"}, True)]
    for sequence_no, (payload, v2) in enumerate(steps):
        if payload is None:
            payload = transition_payload(previous, first=False)
        timestamp = f"2026-10-07T12:00:0{sequence_no}+00:00"
        entry_hash = compute_entry_hash(previous, payload, "tenant-a", sequence_no, timestamp)
        cases.append({
            "name": f"audit-entry-{sequence_no}-{'v2' if v2 else 'v1'}",
            "tenant_id": "tenant-a", "sequence_no": sequence_no, "timestamp": timestamp,
            "payload": payload, "previous_hash": previous, "entry_hash": entry_hash,
            "signature": entry_signature(entry_hash, key, v2=v2)})
        previous = entry_hash
    return {"artifact": "TenantAuditChain entry", "format": "v2",
            "domain": SignatureDomain.AUDIT.value,
            "preimage": "entry_hash as in v1; from the AUDIT_VERSION_TRANSITION record on, "
                        "signature = 'v2:' + HMAC-SHA256(key, domain tag || 0x00 || "
                        "entry_hash) hex; v1 entries before it are never re-signed",
            "keys": {"hmac_key": HMAC_KEY}, "cases": cases}


V1 = {"execution_lease.json": lease_v1, "policy_grant.json": policy_grant_v1,
      "audit_chain.json": audit_v1}
V2 = {"execution_lease.json": lease_v2, "policy_grant.json": policy_grant_v2,
      "audit_chain.json": audit_v2}


def _render(builder: Any) -> str:
    return json.dumps(builder(), indent=2, sort_keys=True) + "\n"


def _manifest(directory: Path, names: list[str]) -> str:
    lines = [f"{hashlib.sha256((directory / n).read_bytes()).hexdigest()}  {n}"
             for n in sorted(names)]
    return "\n".join(lines) + "\n"


def write(version: str) -> None:
    directory = VECTORS / version
    directory.mkdir(parents=True, exist_ok=True)
    builders = V1 if version == "v1" else V2
    for name, builder in builders.items():
        path = directory / name
        if version == "v1" and path.exists():
            raise SystemExit(f"refusing to overwrite frozen vector {path}")
        path.write_text(_render(builder), encoding="utf-8", newline="\n")
    (directory / "MANIFEST.sha256").write_text(
        _manifest(directory, list(builders)), encoding="utf-8", newline="\n")


def check() -> list[str]:
    problems = []
    for version, builders in (("v1", V1), ("v2", V2)):
        directory = VECTORS / version
        for name, builder in builders.items():
            path = directory / name
            if not path.exists():
                problems.append(f"missing {path.relative_to(ROOT)}")
            elif path.read_text(encoding="utf-8") != _render(builder):
                problems.append(f"{path.relative_to(ROOT)} does not match the code")
        manifest = directory / "MANIFEST.sha256"
        if not manifest.exists() or manifest.read_text(encoding="utf-8") != _manifest(
                directory, list(builders)):
            problems.append(f"{manifest.relative_to(ROOT)} is stale")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", choices=["v1", "v2"])
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        write(args.write)
        return 0
    problems = check()
    for problem in problems:
        print(f"[FAIL] {problem}")
    if not problems:
        print("[PASS] signature vectors match the code")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
