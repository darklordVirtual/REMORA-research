# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A signed token without a jti must not be consumable-by-bypass in strict mode."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken, _canonical_payload, _compute_signature

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
KEY = "jti-less-key"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", KEY)
    monkeypatch.delenv("REMORA_PDP_KEY_ID", raising=False)
    monkeypatch.delenv("REMORA_PDP_REVOKED_KEY_IDS", raising=False)
    monkeypatch.delenv("REMORA_PDP_ISSUER", raising=False)


def _jtiless() -> PolicyDecisionToken:
    issued, exp = NOW.isoformat(), (NOW + timedelta(seconds=300)).isoformat()
    payload = _canonical_payload("accept", "c" * 64, "r1", issued, exp, "", "", "", "", "")
    return PolicyDecisionToken(
        action="accept", observation_hash="c" * 64, request_id="r1", issued_at=issued,
        signature=_compute_signature(payload, KEY.encode()), is_signed=True, expires_at=exp,
    )


def test_strict_gate_refuses_jtiless_token_when_consuming():
    token = _jtiless()
    gate = EnforcementGate(strict=True)
    first = gate.check(token, consume=True, now=NOW.isoformat())
    assert first.token_verified is True  # precondition: signature is genuine
    assert first.allowed is False
    assert first.reason == "token_missing_jti"
