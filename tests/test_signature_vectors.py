# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Golden signature vectors (RMR-CR-011): v1 frozen, v2 new.

``vectors/v1`` describes what REMORA signed before domain separation. It is
pinned byte for byte here: a change to any v1 file, or to the production
code's v1 preimages, fails this suite. ``vectors/v2`` is checked against the
code the same way, and may change only together with a format version.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "vectors" / "v1"
V2 = ROOT / "vectors" / "v2"

#: sha256 of vectors/v1/MANIFEST.sha256. Never update this to make a test pass:
#: a changed v1 vector no longer describes what was signed.
V1_MANIFEST_SHA256 = "421816d5e48106cf36f37e04003ebea40238c1a4c1a71659bbd7541c4dfb6d5a"


def _load(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def test_v1_vectors_are_frozen() -> None:
    manifest = (V1 / "MANIFEST.sha256").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == V1_MANIFEST_SHA256
    for line in manifest.decode().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((V1 / name).read_bytes()).hexdigest() == digest, name


def test_the_generator_reproduces_every_vector() -> None:
    result = subprocess.run([sys.executable, "scripts/generate_signature_vectors.py", "--check"],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_generator_refuses_to_rewrite_v1(tmp_path, monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_signature_vectors as gen

    monkeypatch.setattr(gen, "VECTORS", tmp_path)
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "execution_lease.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        gen.write("v1")


# -- the production code agrees with the vectors ----------------------------------------

def _lease(case: dict):
    from remora.enforcement.lease import ExecutionLease

    return ExecutionLease(**case["signed_fields"], signature=case["signature"], is_signed=True)


@pytest.fixture
def keys(monkeypatch):
    for name in ("REMORA_RUNTIME_PROFILE", "REMORA_SIGNATURE_FORMAT", "REMORA_PDP_ISSUER",
                 "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", "REMORA_PDP_REVOKED_KIDS"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_lease_v1_vectors_verify_with_the_frozen_code(keys) -> None:
    from remora.enforcement.lease import ExecutionLease

    vector = _load(V1, "execution_lease.json")
    keys.setenv("REMORA_LEASE_SIGNING_KEY", vector["keys"]["hmac_key"])
    keys.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", vector["keys"]["ed25519_public_hex"])
    keys.setenv("REMORA_LEASE_ACCEPT_HMAC", "1")
    for case in vector["cases"]:
        lease = _lease(case)
        assert ExecutionLease._canonical_payload(lease._signed_fields()).decode() == (
            case["payload"]), case["name"]
        result = lease.verify_historical()
        assert result.verified and result.reason == "historical_v1", case["name"]


def test_lease_v2_vector_verifies_and_names_its_derived_key(keys) -> None:
    from remora.crypto import SignatureDomain, derive_kid, preimage
    from remora.enforcement.lease import ExecutionLease

    vector = _load(V2, "execution_lease.json")
    keys.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", vector["keys"]["ed25519_public_hex"])
    (case,) = vector["cases"]
    lease = _lease(case)
    payload = ExecutionLease._canonical_payload(lease._signed_fields())
    assert payload.decode() == case["payload"]
    import base64

    assert base64.b64decode(case["preimage_b64"]) == preimage(
        SignatureDomain.EXECUTION_LEASE, payload)
    assert lease.kid == derive_kid(bytes.fromhex(vector["keys"]["ed25519_public_hex"]))
    assert lease.verify_historical().reason == "ok"


def test_a_v1_lease_signature_never_verifies_as_v2(keys) -> None:
    """The same key, the same fields: the untagged signature is not a v2 one."""
    import dataclasses

    from remora.enforcement.lease_signing import ALG_ED25519_V2

    vector = _load(V1, "execution_lease.json")
    keys.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", vector["keys"]["ed25519_public_hex"])
    case = next(c for c in vector["cases"] if c["name"] == "lease-v1-ed25519")
    import base64

    v1 = _lease(case)
    from remora.crypto import derive_kid

    as_v2 = dataclasses.replace(
        v1, sig_alg=ALG_ED25519_V2,
        kid=derive_kid(bytes.fromhex(vector["keys"]["ed25519_public_hex"])),
        signature=base64.b64encode(bytes.fromhex(case["signature"])).decode())
    assert as_v2.verify_historical().reason == "signature_invalid"


def test_policy_grant_v1_vector_verifies_with_the_frozen_code(keys) -> None:
    from remora.enforcement.token import PolicyDecisionToken, _canonical_payload

    vector = _load(V1, "policy_grant.json")
    (case,) = vector["cases"]
    fields = json.loads(case["payload"])
    keys.setenv("REMORA_PDP_SIGNING_KEY", vector["keys"]["hmac_key"])
    keys.setenv("REMORA_PDP_SIGNING_KID", fields["kid"])
    assert _canonical_payload(
        fields["action"], fields["observation_hash"], fields["request_id"],
        fields["issued_at"], fields["expires_at"], fields["jti"], fields["audience"],
        fields["kid"], fields["issuer"], fields["context_hash"]).decode() == case["payload"]
    token = PolicyDecisionToken(**fields, signature=case["signature"], is_signed=True)
    result = token.verify(now="2026-10-07T12:01:00+00:00")
    assert result.verified, result.reason


def test_audit_v1_vector_verifies_with_the_frozen_code(keys) -> None:
    import hmac

    from remora.governance.tenant_chain import compute_entry_hash

    vector = _load(V1, "audit_chain.json")
    key = vector["keys"]["hmac_key"].encode()
    for case in vector["cases"]:
        assert compute_entry_hash(case["previous_hash"], case["payload"], case["tenant_id"],
                                  case["sequence_no"], case["timestamp"]) == case["entry_hash"]
        assert hmac.new(key, case["entry_hash"].encode(), hashlib.sha256).hexdigest() == (
            case["signature"])


def test_policy_grant_v2_vector_verifies(keys) -> None:
    from remora.enforcement.token import PolicyDecisionToken

    vector = _load(V2, "policy_grant.json")
    (case,) = vector["cases"]
    fields = json.loads(case["payload"])
    keys.setenv("REMORA_PDP_SIGNING_KEY", vector["keys"]["hmac_key"])
    keys.setenv("REMORA_PDP_SIGNING_KID", fields["kid"])
    token = PolicyDecisionToken(**fields, signature=case["signature"], is_signed=True)
    assert token.verify(now="2026-10-07T12:01:00+00:00").verified
    assert token.verify_historical().reason == "ok"
    v1 = PolicyDecisionToken(**{**fields, "format": ""}, signature=case["signature"],
                             is_signed=True)
    assert v1.verify_historical().reason == "signature_invalid"


def test_audit_v2_vector_crosses_its_transition_without_re_signing() -> None:
    from remora.governance.audit_signing import signature_problems
    from remora.governance.tenant_chain import ChainEntry, compute_entry_hash

    vector = _load(V2, "audit_chain.json")
    entries = [ChainEntry(c["tenant_id"], c["sequence_no"], c["timestamp"], c["payload"],
                          c["previous_hash"], c["entry_hash"], c["signature"])
               for c in vector["cases"]]
    for e in entries:
        assert compute_entry_hash(e.previous_hash, e.payload, e.tenant_id, e.sequence_no,
                                  e.timestamp) == e.entry_hash
    assert signature_problems(entries, vector["keys"]["hmac_key"].encode()) == []
    # The v1 entry before the transition is byte-identical to the frozen v1 vector.
    v1 = _load(V1, "audit_chain.json")["cases"][0]
    assert vector["cases"][0]["signature"] == v1["signature"]

