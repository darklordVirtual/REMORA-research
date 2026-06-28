# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for REM-013: PDP/PEP architectural separation with signed tokens.

Verifies that:
1. PolicyDecisionToken is issued by the PDP layer.
2. EnforcementGate (PEP) verifies the token before allowing execution.
3. Unsigned tokens are rejected in strict mode.
4. Invalid/forged signatures are rejected.
5. Observation hash mismatch is rejected (prevents token reuse).
6. Only ACCEPT decisions allow execution; others are blocked.
7. Non-strict mode allows unsigned tokens with a warning.
"""
from __future__ import annotations

import warnings

import pytest

from remora.enforcement import (
    EnforcementGate,
    PolicyDecisionToken,
    _hash_observation,
)
from remora.enforcement.token import _compute_signature, _canonical_payload


TEST_KEY = "test-pdp-signing-key-rem013"
FIXED_TIME = "2026-06-28T03:00:00Z"


def _issue_with_key(action: str, obs_hash: str = "abc123", req_id: str = "req-1") -> PolicyDecisionToken:
    """Issue a properly signed token using the test key."""
    payload = _canonical_payload(action, obs_hash, req_id, FIXED_TIME)
    sig = _compute_signature(payload, TEST_KEY.encode())
    return PolicyDecisionToken(
        action=action,
        observation_hash=obs_hash,
        request_id=req_id,
        issued_at=FIXED_TIME,
        signature=sig,
        is_signed=True,
    )


class TestTokenIssuance:
    """PolicyDecisionToken issuance and structure."""

    def test_issue_without_key_is_unsigned(self, monkeypatch) -> None:
        monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
        token = PolicyDecisionToken.issue("accept", "hash1", "req-1", FIXED_TIME)
        assert not token.is_signed
        assert token.signature == ""

    def test_issue_with_key_is_signed(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken.issue("accept", "hash1", "req-1", FIXED_TIME)
        assert token.is_signed
        assert len(token.signature) == 64  # SHA-256 hex digest

    def test_token_action_preserved(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        for action in ("accept", "verify", "abstain", "escalate"):
            token = PolicyDecisionToken.issue(action, "hash", "req", FIXED_TIME)
            assert token.action == action

    def test_token_to_dict_roundtrip(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken.issue("accept", "hash1", "req-1", FIXED_TIME)
        d = token.to_dict()
        assert d["action"] == "accept"
        assert d["is_signed"] is True
        assert "signature" in d


class TestTokenVerification:
    """Signature and observation hash verification."""

    def test_valid_signed_token_verifies(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken.issue("accept", "hashX", "req-1", FIXED_TIME)
        result = token.verify()
        assert result.verified
        assert result.reason == "ok"

    def test_tampered_signature_fails_verification(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken.issue("accept", "hashX", "req-1", FIXED_TIME)
        # Tamper: change signature
        tampered = PolicyDecisionToken(
            action=token.action,
            observation_hash=token.observation_hash,
            request_id=token.request_id,
            issued_at=token.issued_at,
            signature="deadbeef" + token.signature[8:],
            is_signed=True,
        )
        result = tampered.verify()
        assert not result.verified
        assert result.reason == "signature_invalid"

    def test_tampered_action_fails_verification(self, monkeypatch) -> None:
        """Changing the action invalidates the signature (payload mismatch)."""
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken.issue("accept", "hashX", "req-1", FIXED_TIME)
        # Tamper: change action while keeping original signature
        tampered = PolicyDecisionToken(
            action="escalate",   # changed from accept
            observation_hash=token.observation_hash,
            request_id=token.request_id,
            issued_at=token.issued_at,
            signature=token.signature,
            is_signed=True,
        )
        result = tampered.verify()
        assert not result.verified, "Changed action must invalidate signature"

    def test_unsigned_token_fails_verification(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken(
            action="accept", observation_hash="h", request_id="r",
            issued_at=FIXED_TIME, signature="", is_signed=False,
        )
        result = token.verify()
        assert not result.verified
        assert result.reason == "token_not_signed"

    def test_observation_hash_mismatch_fails(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken.issue("accept", "original-hash", "req-1", FIXED_TIME)
        result = token.verify(observation_hash="different-hash")
        assert not result.verified
        assert result.reason == "observation_hash_mismatch"

    def test_observation_hash_match_succeeds(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        token = PolicyDecisionToken.issue("accept", "my-hash", "req-1", FIXED_TIME)
        result = token.verify(observation_hash="my-hash")
        assert result.verified

    def test_verification_fails_without_signing_key(self, monkeypatch) -> None:
        monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
        token = _issue_with_key("accept")  # signed externally
        result = token.verify()  # no key to verify with
        assert not result.verified
        assert result.reason == "no_signing_key"


class TestEnforcementGateStrict:
    """EnforcementGate in strict mode (production default)."""

    def test_valid_accept_token_allows(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        gate = EnforcementGate(strict=True)
        token = PolicyDecisionToken.issue("accept", "hashX", "req-1", FIXED_TIME)
        result = gate.check(token)
        assert result.allowed
        assert result.token_verified
        assert result.reason == "accept"

    def test_valid_verify_token_blocks(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        gate = EnforcementGate(strict=True)
        token = PolicyDecisionToken.issue("verify", "hashX", "req-1", FIXED_TIME)
        result = gate.check(token)
        assert not result.allowed
        assert result.reason == "decision_verify_not_accept"

    def test_escalate_token_blocks(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        gate = EnforcementGate(strict=True)
        token = PolicyDecisionToken.issue("escalate", "hashX", "req-1", FIXED_TIME)
        result = gate.check(token)
        assert not result.allowed

    def test_unsigned_token_rejected_in_strict_mode(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        gate = EnforcementGate(strict=True)
        token = PolicyDecisionToken(
            action="accept", observation_hash="h", request_id="r",
            issued_at=FIXED_TIME, signature="", is_signed=False,
        )
        result = gate.check(token)
        assert not result.allowed
        assert "token_verification_failed" in result.reason

    def test_enforce_executes_on_valid_accept(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        gate = EnforcementGate(strict=True)
        token = PolicyDecisionToken.issue("accept", "h", "r", FIXED_TIME)
        executed = []
        gate.enforce(token, lambda: executed.append(True))
        assert executed == [True]

    def test_enforce_raises_on_blocked_decision(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        gate = EnforcementGate(strict=True)
        token = PolicyDecisionToken.issue("escalate", "h", "r", FIXED_TIME)
        with pytest.raises(PermissionError):
            gate.enforce(token, lambda: None)

    def test_enforce_raises_on_invalid_signature(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        gate = EnforcementGate(strict=True)
        token = PolicyDecisionToken(
            action="accept", observation_hash="h", request_id="r",
            issued_at=FIXED_TIME, signature="forged", is_signed=True,
        )
        with pytest.raises(PermissionError):
            gate.enforce(token, lambda: None)


class TestEnforcementGateNonStrict:
    """EnforcementGate in non-strict mode (development)."""

    def test_unsigned_accept_allowed_with_warning(self, monkeypatch) -> None:
        monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
        gate = EnforcementGate(strict=False)
        token = PolicyDecisionToken(
            action="accept", observation_hash="h", request_id="r",
            issued_at=FIXED_TIME, signature="", is_signed=False,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = gate.check(token)
            assert result.allowed
            assert any("unsigned" in str(warning.message).lower() for warning in w), (
                "Non-strict gate should warn about unsigned tokens"
            )

    def test_unsigned_verify_still_blocks(self, monkeypatch) -> None:
        monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
        gate = EnforcementGate(strict=False)
        token = PolicyDecisionToken(
            action="verify", observation_hash="h", request_id="r",
            issued_at=FIXED_TIME, signature="", is_signed=False,
        )
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = gate.check(token)
        assert not result.allowed, "Non-ACCEPT decisions must still be blocked"


class TestObservationHashBinding:
    """Tests that tokens are bound to a specific observation (prevents reuse)."""

    def test_hash_observation_is_deterministic(self) -> None:
        from remora.policy.observation import PolicyObservation
        obs = PolicyObservation(question="test", phase="ordered", trust_score=0.85)
        h1 = _hash_observation(obs)
        h2 = _hash_observation(obs)
        assert h1 == h2, "Observation hash must be deterministic"

    def test_different_observations_produce_different_hashes(self) -> None:
        from remora.policy.observation import PolicyObservation
        obs1 = PolicyObservation(question="test A", phase="ordered", trust_score=0.85)
        obs2 = PolicyObservation(question="test B", phase="ordered", trust_score=0.85)
        assert _hash_observation(obs1) != _hash_observation(obs2)

    def test_token_issued_for_obs_rejected_for_different_obs(self, monkeypatch) -> None:
        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", TEST_KEY)
        from remora.policy.observation import PolicyObservation
        obs_a = PolicyObservation(question="action A", phase="ordered", trust_score=0.9)
        obs_b = PolicyObservation(question="action B", phase="ordered", trust_score=0.9)
        hash_a = _hash_observation(obs_a)
        hash_b = _hash_observation(obs_b)
        token = PolicyDecisionToken.issue("accept", hash_a, "req-a", FIXED_TIME)
        # Token was issued for obs_a — must be rejected if presented with obs_b's hash
        gate = EnforcementGate(strict=True)
        result = gate.check(token, expected_observation_hash=hash_b)
        assert not result.allowed, (
            "Token issued for obs_a must be rejected when presented for obs_b"
        )
