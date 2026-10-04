# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""E8: an AgentAvow-profile signed tool manifest bound to a REMORA authorization.

The adapter verifies a foreign artifact under a key the deployment supplies,
normalizes it, and compares its digest with the tool-definition identity
signed into an ``ExecutionLease``. These tests pin what the edge establishes
and, more importantly, what it must never do: admit evidence, carry a gate
field, trust a signer because of a registry, or report a pass when the
verifier is unavailable (FED-INV-001, FED-INV-005).
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from remora.enforcement.lease import ExecutionLease
from remora.interop import agentavow
from remora.interop.agentavow import adapter
from remora.interop.jcs import canonicalise

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "interop" / "agentavow-tool-manifest-e8-v0.1"
EVIDENCE_REF_SCHEMA = ROOT / "artifacts" / "interop" / "schemas" / "external-evidence-ref-v1.schema.json"


@pytest.fixture(autouse=True)
def _signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "agentavow-edge-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")


@pytest.fixture(scope="module")
def fixtures() -> dict[str, Any]:
    return json.loads((PACKAGE / "fixtures.json").read_text(encoding="utf-8"))


def _lease(toolspec_hash: str) -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-7", tool_name="update_ticket",
        arguments={"ticket_id": "T-1041", "status": "closed"}, target_environment="production",
        policy_bundle_hash="sha256:" + "f" * 64, issued_at="2026-10-04T12:00:00+00:00",
        toolspec_hash=toolspec_hash, toolspec_version=3,
    )


def _signed_manifest(key: Ed25519PrivateKey, kid: str = "k1", **over: Any) -> dict[str, Any]:
    tooldef = {"name": "update_ticket", "parameters": {"type": "object"}}
    body = {"profile": adapter.PROFILE_ID, "manifest_id": "m-1", "issuer": "test", "kid": kid,
            "issued_at": "2026-10-04T10:00:00+00:00", "tool_definition": tooldef,
            "tool_definition_digest": "sha256:" + __import__("hashlib").sha256(canonicalise(tooldef)).hexdigest()}
    body.update(over)
    sig = key.sign(canonicalise(body))
    return dict(body, signature={"alg": "ed25519", "value": base64.b64encode(sig).decode()})


def _pub(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


# ── The fixture contract ───────────────────────────────────────────────────


def test_reference_verifier_reproduces_every_expected_verdict() -> None:
    out = subprocess.run([sys.executable, str(PACKAGE / "reference_verifier.py")], cwd=ROOT,
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr or out.stdout
    payload = json.loads(out.stdout)
    assert payload["failures"] == []
    assert len(payload["results"]) == 8


def test_adapter_reproduces_every_expected_verdict(fixtures: dict[str, Any]) -> None:
    for case in fixtures["cases"]:
        observed = agentavow.evaluate_fixture_case(case, fixtures["trusted_signers"])
        assert observed == {k: case["expected"][k] for k in ("verdict", "reason")}, case["id"]


def test_fixture_canonical_form_agrees_with_remora_jcs(fixtures: dict[str, Any]) -> None:
    """The reference verifier uses json.dumps for the JCS-trivial subset; the
    adapter uses remora.interop.jcs. They must produce the same preimage."""
    for case in fixtures["cases"]:
        body = {k: v for k, v in case["manifest"].items() if k != "signature"}
        assert canonicalise(body) == json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# ── What the edge establishes ──────────────────────────────────────────────


def test_bound_definition_is_established_and_bounded() -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _signed_manifest(key)
    verification = adapter.verify_manifest(manifest, {"k1": _pub(key)})
    assert verification.ok and verification.observed is not None
    result = adapter.bind_to_authorization(verification, _lease(verification.observed.digest), now="2026-10-04T12:00:30+00:00")
    assert (result.status, result.reason) == ("ESTABLISHED", "digest_bound")
    assert result.establishes and result.does_not_establish
    assert any("semantically correct" in s for s in result.does_not_establish)
    assert any("UNADMITTED" in s for s in result.does_not_establish)


def test_redeployed_definition_is_contradicted() -> None:
    key = Ed25519PrivateKey.generate()
    verification = adapter.verify_manifest(_signed_manifest(key), {"k1": _pub(key)})
    result = adapter.bind_to_authorization(verification, _lease("a" * 64), now="2026-10-04T12:00:30+00:00")
    assert (result.status, result.reason) == ("CONTRADICTED", "digest_mismatch")
    assert result.establishes == ()


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda m, k: dict(m, tool_definition=dict(m["tool_definition"], name="delete_ticket")), "signature_invalid"),
        (lambda m, k: dict(m, kid="k9"), "signer_unknown"),
        (lambda m, k: dict(m, signature=dict(m["signature"], alg="hmac-sha256")), "algorithm_unsupported"),
        (lambda m, k: {x: v for x, v in m.items() if x != "tool_definition"}, "manifest_malformed"),
        (lambda m, k: {x: v for x, v in m.items() if x != "signature"}, "manifest_malformed"),
        (lambda m, k: _signed_manifest(k, tool_definition_digest="sha256:" + "0" * 64), "manifest_inconsistent"),
    ],
)
def test_every_failure_is_a_distinct_reason_and_never_a_pass(mutate: Any, reason: str) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = mutate(_signed_manifest(key), key)
    verification = adapter.verify_manifest(manifest, {"k1": _pub(key)})
    assert (verification.ok, verification.reason) == (False, reason)
    result = adapter.bind_to_authorization(verification, _lease("a" * 64), now="2026-10-04T12:00:30+00:00")
    assert result.status == "NOT_ESTABLISHED"
    assert result.reason == reason
    assert result.evidence_ref is None


def test_unverifiable_authorization_is_not_established() -> None:
    key = Ed25519PrivateKey.generate()
    verification = adapter.verify_manifest(_signed_manifest(key), {"k1": _pub(key)})
    assert verification.observed is not None
    unsigned = dataclasses.replace(_lease(verification.observed.digest), signature="", is_signed=False)
    result = adapter.bind_to_authorization(verification, unsigned, now="2026-10-04T12:00:30+00:00")
    assert (result.status, result.reason) == ("NOT_ESTABLISHED", "authorization_unverifiable")
    expired = _lease(verification.observed.digest)
    result = adapter.bind_to_authorization(verification, expired, now="2026-10-05T12:00:30+00:00")
    assert (result.status, result.reason) == ("NOT_ESTABLISHED", "authorization_unverifiable")
    unbound = _lease("")
    result = adapter.bind_to_authorization(verification, unbound, now="2026-10-04T12:00:30+00:00")
    assert (result.status, result.reason) == ("NOT_ESTABLISHED", "authorization_unbound_to_definition")


def test_verifier_unavailable_is_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(adapter, "Ed25519PublicKey", None)
    verification = adapter.verify_manifest(_signed_manifest(key), {"k1": _pub(key)})
    assert (verification.ok, verification.reason) == (False, "verifier_unavailable")


# ── What the edge must never do (FED-INV-001, FED-INV-005) ─────────────────


def test_evidence_ref_is_unadmitted_and_valid() -> None:
    key = Ed25519PrivateKey.generate()
    verification = adapter.verify_manifest(_signed_manifest(key), {"k1": _pub(key)})
    assert verification.observed is not None
    ref = verification.observed.evidence_ref("AgentAvow")
    jsonschema.Draft202012Validator(json.loads(EVIDENCE_REF_SCHEMA.read_text(encoding="utf-8"))).validate(ref)
    assert ref["admission_state"] == "UNADMITTED"
    result = adapter.bind_to_authorization(verification, _lease(verification.observed.digest), now="2026-10-04T12:00:30+00:00")
    assert result.evidence_ref == ref
    gate_words = {"accept", "verify", "abstain", "escalate", "grant", "lease", "authority", "authorize", "authorise", "decision"}
    for record in (ref, result.to_dict()):
        assert not (set(record) & gate_words), set(record) & gate_words


def test_signer_trust_comes_only_from_the_caller_supplied_keys() -> None:
    """A manifest from a key the deployment did not supply is signer_unknown,
    however it names its issuer. Nothing in the adapter resolves anything."""
    key = Ed25519PrivateKey.generate()
    manifest = _signed_manifest(key, issuer="federation-member.example")
    assert adapter.verify_manifest(manifest, {}).reason == "signer_unknown"
    assert adapter.verify_manifest(manifest, {"k1": _pub(key)}).ok
    source = (ROOT / "remora" / "interop" / "agentavow" / "adapter.py").read_text(encoding="utf-8")
    for forbidden in ("urllib", "requests", "httpx", "socket", "RemoraDecisionEngine", "remora.policy", "GovernedToolDispatcher"):
        assert forbidden not in source, forbidden


def test_adapter_does_not_mutate_the_lease_or_the_manifest() -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _signed_manifest(key)
    before = copy.deepcopy(manifest)
    verification = adapter.verify_manifest(manifest, {"k1": _pub(key)})
    assert manifest == before
    assert verification.observed is not None
    lease = _lease(verification.observed.digest)
    frozen = lease.to_dict()
    adapter.bind_to_authorization(verification, lease, now="2026-10-04T12:00:30+00:00")
    assert lease.to_dict() == frozen
