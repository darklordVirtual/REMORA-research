# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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


def test_future_dated_token_is_not_yet_valid() -> None:
    """External review 2026-07-24, F-03: a nominal five-minute token whose
    issued_at lies 30 days in the future was accepted by a strict gate NOW
    (its age was negative, so the max-age check passed, and verify() had no
    not-before). The token must be valid only inside [issued_at, expires_at)."""
    future_issue = (NOW + timedelta(days=30)).isoformat()
    token = _issue(
        issued_at=future_issue,
        expires_at=(NOW + timedelta(days=30, minutes=5)).isoformat(),
    )
    res = token.verify(now=ISSUED)
    assert res.verified is False
    assert res.reason == "token_not_yet_valid"

    gate = EnforcementGate(strict=True)
    out = gate.check(token, now=ISSUED)
    assert out.allowed is False
    assert "token_not_yet_valid" in out.reason

    # Inside its declared window the same token verifies.
    inside = (NOW + timedelta(days=30, minutes=1)).isoformat()
    assert token.verify(now=inside).verified


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


def test_in_process_ledger_does_not_survive_a_restart(tmp_path) -> None:
    """Pin the limitation, so it can never be silently assumed away.

    A second EnforcementGate stands in for a second uvicorn worker, or for
    the same process after a restart. Without a durable ledger it has no
    memory of what was consumed, so the one-time grant is accepted again.
    Production refuses this configuration
    (`servers.api._validate_production_prerequisites`); this test documents
    exactly what that gate is protecting against.
    """
    token = _issue()
    assert EnforcementGate(strict=True).check(token, consume=True).allowed is True
    # Fresh process, empty in-memory set: the replay goes through.
    assert EnforcementGate(strict=True).check(token, consume=True).allowed is True


def test_durable_ledger_refuses_the_replay_across_processes(tmp_path) -> None:
    """With a durable ledger the same replay is refused, which is the point."""
    db = str(tmp_path / "jti.db")
    token = _issue()

    first = EnforcementGate(strict=True, db_path=db)
    assert first.check(token, consume=True).allowed is True

    second = EnforcementGate(strict=True, db_path=db)
    result = second.check(token, consume=True)
    assert result.allowed is False
    assert result.reason == "token_already_consumed"


def test_durable_ledger_still_allows_a_fresh_token(tmp_path) -> None:
    """The ledger must block replays, not every token that follows one."""
    db = str(tmp_path / "jti.db")
    gate = EnforcementGate(strict=True, db_path=db)
    assert gate.check(_issue(), consume=True).allowed is True
    assert gate.check(_issue(request_id="req-2"), consume=True).allowed is True


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
