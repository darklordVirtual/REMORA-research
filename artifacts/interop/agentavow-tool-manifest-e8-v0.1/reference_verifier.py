#!/usr/bin/env python3
"""Reference verifier for the assumed AgentAvow tool-manifest profile v0 (E8).

This file imports no REMORA code. Its one dependency is ``cryptography`` for
Ed25519 verification; without it every case is reported as NOT_ESTABLISHED
with reason ``verifier_unavailable`` and the run fails, never as a pass. The
canonical form is RFC 8785 restricted to the JCS-trivial subset the fixtures
use, which ``json.dumps`` with sorted keys and no whitespace reproduces.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - exercised only on a host without the dependency
    class InvalidSignature(Exception):  # type: ignore[no-redef]
        """Placeholder so the except clause below stays a real exception type."""

    Ed25519PublicKey = None  # type: ignore[assignment,misc]


def jcs(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def evaluate(case: dict, trusted_signers: dict[str, str]) -> dict:
    if Ed25519PublicKey is None:
        return {"verdict": "NOT_ESTABLISHED", "reason": "verifier_unavailable"}
    manifest = dict(case["manifest"])
    signature = manifest.pop("signature", None)
    for member in ("kid", "tool_definition", "tool_definition_digest"):
        if member not in manifest:
            return {"verdict": "NOT_ESTABLISHED", "reason": "manifest_malformed"}
    if not isinstance(signature, dict) or "alg" not in signature or "value" not in signature:
        return {"verdict": "NOT_ESTABLISHED", "reason": "manifest_malformed"}
    if signature["alg"] != "ed25519":
        return {"verdict": "NOT_ESTABLISHED", "reason": "algorithm_unsupported"}
    public = trusted_signers.get(manifest["kid"])
    if public is None:
        return {"verdict": "NOT_ESTABLISHED", "reason": "signer_unknown"}
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public)).verify(base64.b64decode(signature["value"]), jcs(manifest))
    except (InvalidSignature, ValueError):
        return {"verdict": "NOT_ESTABLISHED", "reason": "signature_invalid"}
    digest = "sha256:" + hashlib.sha256(jcs(manifest["tool_definition"])).hexdigest()
    if manifest["tool_definition_digest"] != digest:
        return {"verdict": "NOT_ESTABLISHED", "reason": "manifest_inconsistent"}
    authorization = case["authorization"]
    if authorization.get("integrity", "intact") != "intact":
        return {"verdict": "NOT_ESTABLISHED", "reason": "authorization_unverifiable"}
    if authorization["toolspec_hash"] == digest.split(":", 1)[1]:
        return {"verdict": "ESTABLISHED", "reason": "digest_bound"}
    return {"verdict": "CONTRADICTED", "reason": "digest_mismatch"}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("fixtures.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    results, failures = [], []
    for case in doc["cases"]:
        actual = evaluate(case, doc["trusted_signers"])
        expected = {k: case["expected"][k] for k in ("verdict", "reason")}
        ok = actual == expected
        results.append({"id": case["id"], "claim_id": case["claim_id"], "ok": ok, "actual": actual, "expected": expected,
                        "claim_result": case["expected"]["claim_result"] if ok else "CONTRADICTED"})
        if not ok:
            failures.append(case["id"])
    print(json.dumps({"schema_version": doc["schema_version"], "results": results, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
