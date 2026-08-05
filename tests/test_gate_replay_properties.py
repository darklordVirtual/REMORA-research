# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Property-based proof of the PEP one-time-grant contract.

The documented claim: an ACCEPT token authorizes at most one execution —
a consumed jti refuses every later attempt, while non-consuming checks
never spend the grant. These properties assert it for any number of
attempts, not just the single-replay example (proof-depth track, slice 4).
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken

OBS_HASH = "a" * 64
ISSUED_AT = "2026-01-01T00:00:00+00:00"
EXPIRES_AT = "2026-01-01T00:05:00+00:00"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "gate-prop-test-key")


def _token() -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(
        action="accept", observation_hash=OBS_HASH, request_id="r-1",
        issued_at=ISSUED_AT, expires_at=EXPIRES_AT, audience="pep",
    )


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=10))
def test_consumed_grant_refuses_every_later_attempt(replays) -> None:
    gate = EnforcementGate(strict=True, audience="pep")
    token = _token()

    first = gate.check(token, expected_observation_hash=OBS_HASH,
                       consume=True, now=ISSUED_AT)
    assert first.allowed, first.reason

    for _ in range(replays):
        again = gate.check(token, expected_observation_hash=OBS_HASH,
                           consume=True, now=ISSUED_AT)
        assert not again.allowed
        assert again.reason == "token_already_consumed"


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=10))
def test_non_consuming_checks_never_spend_the_grant(peeks) -> None:
    gate = EnforcementGate(strict=True, audience="pep")
    token = _token()

    for _ in range(peeks):
        peek = gate.check(token, expected_observation_hash=OBS_HASH,
                          consume=False, now=ISSUED_AT)
        assert peek.allowed, peek.reason

    spend = gate.check(token, expected_observation_hash=OBS_HASH,
                       consume=True, now=ISSUED_AT)
    assert spend.allowed, spend.reason

    replay = gate.check(token, expected_observation_hash=OBS_HASH,
                        consume=True, now=ISSUED_AT)
    assert not replay.allowed
    assert replay.reason == "token_already_consumed"
