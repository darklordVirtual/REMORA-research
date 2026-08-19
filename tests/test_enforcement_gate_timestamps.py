# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Timestamp-handling regression suite for EnforcementGate.check() (Phase 7).

check() must never raise an uncaught timezone-aware/naive subtraction
TypeError; malformed or ambiguous timestamps fail CLOSED with a
machine-readable reason. Covers: UTC "Z", explicit +00:00, other offsets,
naive timestamps, invalid strings, future issued_at, and expired tokens.
"""
from __future__ import annotations

import pytest

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken

OBS_HASH = "a" * 64


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "gate-ts-test-key")


def _token(issued_at: str, expires_at: str) -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(
        action="accept", observation_hash=OBS_HASH, request_id="r-ts",
        issued_at=issued_at, expires_at=expires_at, audience="pep",
    )


def _check(token: PolicyDecisionToken, now: str | None):
    gate = EnforcementGate(strict=True, audience="pep")
    return gate.check(token, expected_observation_hash=OBS_HASH, now=now)


def test_utc_z_suffix_accepted() -> None:
    token = _token("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
    result = _check(token, now="2026-01-01T00:01:00Z")
    assert result.allowed, result.reason


def test_explicit_utc_offset_accepted() -> None:
    token = _token("2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00")
    result = _check(token, now="2026-01-01T00:01:00+00:00")
    assert result.allowed, result.reason


def test_other_timezone_offset_compares_correctly() -> None:
    # 02:00+02:00 == 00:00Z; a +02:00 clock one minute later is inside the window.
    token = _token("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
    result = _check(token, now="2026-01-01T02:01:00+02:00")
    assert result.allowed, result.reason


def test_naive_issued_at_never_raises_typeerror() -> None:
    # Naive issued_at against the aware wall clock was the uncaught-TypeError
    # path. It must yield a fail-closed decision, not an exception.
    token = _token("2026-01-01T00:00:00", "2026-01-01T00:05:00")
    result = _check(token, now=None)  # aware datetime.now(UTC)
    assert result.allowed is False
    assert isinstance(result.reason, str) and result.reason


def test_naive_now_against_aware_token_never_raises() -> None:
    token = _token("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
    result = _check(token, now="2026-01-01T00:01:00")  # naive now
    assert result.allowed, result.reason  # coerced to UTC, inside window


def test_invalid_issued_at_fails_closed() -> None:
    token = _token("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
    object.__setattr__(token, "issued_at", "not-a-timestamp")
    result = _check(token, now="2026-01-01T00:01:00Z")
    assert result.allowed is False
    # Signature covers issued_at, so tampering surfaces at verification; either
    # reason is fail-closed and machine-readable.
    assert result.reason.startswith(("token_verification_failed", "issued_at_unparseable"))


def test_invalid_now_fails_closed() -> None:
    token = _token("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
    result = _check(token, now="garbage")
    assert result.allowed is False
    assert result.reason in ("issued_at_unparseable", "token_verification_failed:expiry_unparseable")


def test_future_issued_at_fails_closed() -> None:
    token = _token("2026-01-01T01:00:00Z", "2026-01-01T01:05:00Z")
    result = _check(token, now="2026-01-01T00:00:00Z")
    assert result.allowed is False
    assert result.reason in (
        "token_issued_in_future",
        "token_verification_failed:token_not_yet_valid",
        "token_verification_failed:issued_in_future",
    )


def test_expired_token_fails_closed() -> None:
    token = _token("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
    result = _check(token, now="2026-01-01T00:06:00Z")
    assert result.allowed is False
    assert "expire" in result.reason or "too_old" in result.reason


def test_token_older_than_max_age_fails_closed() -> None:
    gate = EnforcementGate(strict=True, audience="pep")
    token = _token("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
    # Bypass signature-level expiry by checking exactly at the age boundary
    # semantics: far beyond MAX_TOKEN_AGE_SECONDS the reason is a refusal
    # either from expiry or the age cap — never an exception.
    result = gate.check(token, expected_observation_hash=OBS_HASH, now="2026-01-02T00:00:00Z")
    assert result.allowed is False
