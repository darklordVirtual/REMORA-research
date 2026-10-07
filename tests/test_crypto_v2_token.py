# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-011 (C2): PolicyDecisionToken v2, domain-separated, under strict v2.

Before: a token is HMAC-SHA256 over untagged canonical JSON, under the same
key the HMAC lease path falls back to. Probe at c8cc91d: under ``review/v2``
the PDP still issues and accepts untagged v1 tokens.

After: PolicyDecisionToken v1 is frozen (``vectors/v1/policy_grant.json``).
v2 signs ``REMORA/POLICY-GRANT/v2 || 0x00 || payload`` and carries
``format: v2`` inside the signed payload. A strict v2 contract issues only v2
and refuses a v1 token as live authority; v1 stays verifiable as historical
evidence.

The token stays a symmetric, in-process grant record (RMR-CR-002): v2 adds
domain separation, not a decision/enforcement trust boundary.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from remora.crypto import SignatureDomain, preimage
from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken, _canonical_payload

KEY = "pdp-test-key"
OBS = "e" * 64


@pytest.fixture
def pdp(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", KEY)
    for name in ("REMORA_RUNTIME_PROFILE", "REMORA_SIGNATURE_FORMAT", "REMORA_PDP_ISSUER",
                 "REMORA_PDP_SIGNING_KID", "REMORA_PDP_PREVIOUS_KEYS", "REMORA_PDP_REVOKED_KIDS"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _issue() -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(action="accept", observation_hash=OBS, request_id="r-1",
                                     issued_at=datetime.now(UTC).isoformat())


def test_a_strict_v2_pdp_issues_v2_tokens(pdp) -> None:
    pdp.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    token = _issue()
    assert token.format == "v2"
    assert token.verify(OBS).verified


def test_the_v2_signature_is_over_the_tagged_preimage(pdp) -> None:
    pdp.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    token = _issue()
    payload = json.loads(_canonical_payload(
        token.action, token.observation_hash, token.request_id, token.issued_at,
        token.expires_at, token.jti, token.audience, token.kid, token.issuer,
        token.context_hash, token.format))
    assert payload["format"] == "v2"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    tagged = hmac.new(KEY.encode(), preimage(SignatureDomain.POLICY_GRANT, raw),
                      hashlib.sha256).hexdigest()
    assert token.signature == tagged
    untagged = hmac.new(KEY.encode(), raw, hashlib.sha256).hexdigest()
    assert token.signature != untagged


def test_v1_is_frozen_outside_strict_v2(pdp) -> None:
    token = _issue()
    assert token.format == ""
    assert "format" not in token.to_dict()
    assert token.verify(OBS).verified


def test_the_v1_contract_keeps_v1(pdp) -> None:
    pdp.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    assert _issue().format == ""


def test_a_v1_token_is_refused_as_live_authority_under_strict_v2(pdp) -> None:
    legacy = _issue()
    pdp.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    assert legacy.verify(OBS).reason == "token_format_legacy"
    gate = EnforcementGate(strict=True)
    result = gate.check(legacy, OBS)
    assert not result.allowed and result.reason == "token_verification_failed:token_format_legacy"


def test_a_v1_token_stays_readable_as_historical_evidence(pdp) -> None:
    legacy = _issue()
    pdp.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    result = legacy.verify_historical()
    assert result.verified and result.reason == "historical_v1"
    pdp.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    pdp.delenv("REMORA_RUNTIME_PROFILE")
    assert _issue().verify_historical().reason == "ok"


def test_the_format_cannot_be_stripped(pdp) -> None:
    """format is signed: a v2 token relabelled as v1 fails its signature."""
    pdp.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    token = _issue()
    pdp.delenv("REMORA_SIGNATURE_FORMAT")
    assert dataclasses.replace(token, format="").verify(OBS).reason == "signature_invalid"


def test_an_unknown_format_is_refused(pdp) -> None:
    token = dataclasses.replace(_issue(), format="v9")
    assert token.verify(OBS).reason == "token_format_unknown"
    assert token.verify_historical().reason == "token_format_unknown"


def test_a_v2_token_round_trips_through_its_dict(pdp) -> None:
    pdp.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    token = _issue()
    restored = PolicyDecisionToken.from_dict(token.to_dict())
    assert restored == token and restored.verify(OBS).verified


def test_a_grant_signature_never_verifies_as_a_lease_preimage(pdp) -> None:
    """Same key, same bytes: the grant domain is not the lease domain."""
    pdp.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    token = _issue()
    raw = _canonical_payload(
        token.action, token.observation_hash, token.request_id, token.issued_at,
        token.expires_at, token.jti, token.audience, token.kid, token.issuer,
        token.context_hash, token.format)
    as_lease = hmac.new(KEY.encode(), preimage(SignatureDomain.EXECUTION_LEASE, raw),
                        hashlib.sha256).hexdigest()
    assert as_lease != token.signature


def test_rotation_and_revocation_hold_in_v2(pdp) -> None:
    pdp.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    pdp.setenv("REMORA_PDP_SIGNING_KID", "k1")
    token = _issue()
    pdp.setenv("REMORA_PDP_SIGNING_KEY", "rotated-key")
    pdp.setenv("REMORA_PDP_SIGNING_KID", "k2")
    pdp.setenv("REMORA_PDP_PREVIOUS_KEYS", f"k1={KEY}")
    assert token.verify(OBS).verified
    pdp.setenv("REMORA_PDP_REVOKED_KIDS", "k1")
    assert token.verify(OBS).reason == "kid_revoked"


def test_an_expired_v2_token_refuses(pdp) -> None:
    pdp.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    token = _issue()
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert token.verify(OBS, now=later).reason == "token_expired"
