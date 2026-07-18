# Author: Stian Skogbrott
# License: Apache-2.0
"""Review findings: mandatory token expiry, jti one-time consumption,
audience binding, max token age, and lossless serialisation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import (
    DEFAULT_TOKEN_TTL_SECONDS,
    MAX_TOKEN_TTL_SECONDS,
    PolicyDecisionToken,
)

NOW = datetime.now(timezone.utc)
ISSUED = NOW.isoformat()
SOON = (NOW + timedelta(seconds=60)).isoformat()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "hardening-key")


def _issue(**kwargs) -> PolicyDecisionToken:
    defaults = dict(action="accept", observation_hash="h" * 64,
                    request_id="req-1", issued_at=ISSUED)
    defaults.update(kwargs)
    return PolicyDecisionToken.issue(**defaults)


def test_every_token_carries_signed_expiry_and_jti() -> None:
    token = _issue()
    assert token.expires_at is not None
    delta = (datetime.fromisoformat(token.expires_at)
             - datetime.fromisoformat(ISSUED)).total_seconds()
    assert delta == DEFAULT_TOKEN_TTL_SECONDS
    assert token.jti  # unique one-time id
    assert token.jti != _issue().jti


def test_excessive_ttl_is_rejected_at_issue() -> None:
    too_late = (NOW + timedelta(seconds=MAX_TOKEN_TTL_SECONDS + 1)).isoformat()
    with pytest.raises(ValueError, match="TTL"):
        _issue(expires_at=too_late)
    with pytest.raises(ValueError, match="TTL"):
        _issue(expires_at=ISSUED)  # zero/negative TTL


def test_serialisation_round_trips_all_signed_fields() -> None:
    token = _issue(audience="pep://ot-gateway")
    restored = PolicyDecisionToken.from_dict(token.to_dict())
    assert restored == token
    assert restored.verify(now=SOON).verified
    with pytest.raises(ValueError, match="unknown"):
        PolicyDecisionToken.from_dict({**token.to_dict(), "extra": 1})


def test_enforce_consumes_token_once() -> None:
    token = _issue()
    gate = EnforcementGate(strict=True)
    executed: list[bool] = []
    gate.enforce(token, lambda: executed.append(True))
    assert executed == [True]
    with pytest.raises(PermissionError, match="token_already_consumed"):
        gate.enforce(token, lambda: executed.append(True))
    assert executed == [True]  # second execution never ran


def test_audience_binding() -> None:
    gate = EnforcementGate(strict=True, audience="pep://ot-gateway")
    wrong = _issue(audience="pep://other")
    assert gate.check(wrong, now=SOON).reason == "audience_mismatch"
    unaddressed = _issue()
    assert gate.check(unaddressed, now=SOON).reason == "audience_mismatch"
    right = _issue(audience="pep://ot-gateway")
    assert gate.check(right, now=SOON).allowed


def test_token_too_old_is_rejected_even_if_unexpired() -> None:
    gate = EnforcementGate(strict=True)
    old_issue = (NOW - timedelta(seconds=gate.MAX_TOKEN_AGE_SECONDS + 60)).isoformat()
    # Explicit long expiry keeps it "unexpired", but age check refuses it.
    long_expiry = (NOW + timedelta(hours=1)).isoformat()
    token = _issue(issued_at=old_issue, expires_at=long_expiry)
    result = gate.check(token, now=NOW.isoformat())
    assert not result.allowed
    assert result.reason == "token_too_old"
