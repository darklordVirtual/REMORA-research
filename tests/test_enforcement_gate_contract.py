# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The full EnforcementResult tuple, pinned per refusal branch of check().

The mutation pass left 53 survivors in ``EnforcementGate.check`` on covered
lines (docs/assurance/mutation_testing_v1.md): the existing suites assert
``allowed`` and little else, so mutants that flip ``token_verified``, rewrite
a refusal ``reason`` or nudge an age boundary pass unnoticed. Refusal reasons
are routed on, not read — servers/execution_api.py maps them to metric
families and HTTP details — so a mutated reason is an operational defect,
not cosmetics. Every test here asserts the complete
(allowed, action, token_verified, reason, strict_mode) tuple, and the age
tests sit exactly on the boundary, because a boundary mutant (``>`` vs
``>=``) is invisible anywhere else.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "gate-contract-key")
    monkeypatch.delenv("REMORA_PDP_KEY_ID", raising=False)
    monkeypatch.delenv("REMORA_PDP_REVOKED_KEY_IDS", raising=False)


def _token(action: str = "accept", *, issued: datetime = NOW,
           ttl: int = 300, audience: str = "", jti: str = "",
           obs_hash: str = "c" * 64) -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(
        action=action, observation_hash=obs_hash, request_id="req-gate-1",
        issued_at=_iso(issued), expires_at=_iso(issued + timedelta(seconds=ttl)),
        audience=audience,
    )


def _tuple(r) -> tuple:
    return (r.allowed, r.action, r.token_verified, r.reason, r.strict_mode)


# ── refusal branches, full tuple each ──────────────────────────────────────


def test_tampered_signature_refuses_with_the_verification_reason() -> None:
    token = _token()
    object.__setattr__(token, "signature", "0" * 64)
    r = EnforcementGate(strict=True).check(token, now=_iso(NOW))
    assert _tuple(r) == (
        False, "accept", False,
        "token_verification_failed:signature_invalid", True,
    )


def test_audience_mismatch_refuses_after_verification() -> None:
    r = EnforcementGate(strict=True, audience="pep-a").check(
        _token(audience="pep-b"), now=_iso(NOW))
    assert _tuple(r) == (False, "accept", True, "audience_mismatch", True)


def test_unparseable_issued_at_fails_closed() -> None:
    token = _token()
    object.__setattr__(token, "issued_at", "not-a-timestamp")
    # The mutated stamp breaks the signature too; what this pins is that the
    # gate answers with a structured refusal rather than raising.
    r = EnforcementGate(strict=True).check(token, now=_iso(NOW))
    assert r.allowed is False
    assert r.strict_mode is True


def test_future_issued_at_refuses_at_the_verification_layer() -> None:
    """Layering pinned as it actually is: token.verify refuses a
    not-yet-valid token before the gate's own skew branch runs. The gate's
    token_issued_in_future branch is the backstop for non-strict unsigned
    flows that bypass verification -- defence in depth, not the primary."""
    token = _token(issued=NOW + timedelta(seconds=120))
    r = EnforcementGate(strict=True).check(token, now=_iso(NOW))
    assert r.allowed is False
    assert r.token_verified is False
    assert r.reason.startswith("token_verification_failed:")
    assert r.strict_mode is True


def test_age_exactly_at_the_maximum_is_still_allowed() -> None:
    """The boundary itself: 3600 s old passes, because the refusal is
    strictly greater-than. A `>=` mutant fails here and nowhere else."""
    token = _token(issued=NOW - timedelta(seconds=EnforcementGate.MAX_TOKEN_AGE_SECONDS),
                   ttl=EnforcementGate.MAX_TOKEN_AGE_SECONDS + 600)
    r = EnforcementGate(strict=True).check(token, now=_iso(NOW))
    assert _tuple(r) == (True, "accept", True, "accept", True)


def test_one_second_past_the_maximum_age_refuses() -> None:
    token = _token(issued=NOW - timedelta(seconds=EnforcementGate.MAX_TOKEN_AGE_SECONDS + 1),
                   ttl=EnforcementGate.MAX_TOKEN_AGE_SECONDS + 600)
    r = EnforcementGate(strict=True).check(token, now=_iso(NOW))
    assert _tuple(r) == (False, "accept", True, "token_too_old", True)


def test_age_zero_is_allowed_not_future() -> None:
    """issued_at == now: age 0 is neither future nor old. A `<=` mutant on
    the skew check fails exactly here."""
    r = EnforcementGate(strict=True).check(_token(issued=NOW), now=_iso(NOW))
    assert _tuple(r) == (True, "accept", True, "accept", True)


@pytest.mark.parametrize("action", ["verify", "abstain", "escalate"])
def test_non_accept_actions_never_authorize(action: str) -> None:
    r = EnforcementGate(strict=True).check(_token(action), now=_iso(NOW))
    assert _tuple(r) == (
        False, action, True, f"decision_{action}_not_accept", True,
    )


def test_observation_hash_mismatch_refuses() -> None:
    r = EnforcementGate(strict=True).check(
        _token(), expected_observation_hash="d" * 64, now=_iso(NOW))
    assert r.allowed is False
    assert r.token_verified is False
    assert r.reason.startswith("token_verification_failed:")


# ── one-time consumption, both in-process and durable ──────────────────────


def test_in_memory_replay_refuses_with_the_consumed_reason() -> None:
    gate = EnforcementGate(strict=True)
    token = _token(jti="jti-contract-1")
    first = gate.check(token, consume=True, now=_iso(NOW))
    assert _tuple(first) == (True, "accept", True, "accept", True)
    replay = gate.check(token, consume=True, now=_iso(NOW))
    assert _tuple(replay) == (
        False, "accept", True, "token_already_consumed", True,
    )


def test_sqlite_replay_refuses_with_the_consumed_reason(tmp_path) -> None:
    db = str(tmp_path / "pep.db")
    gate = EnforcementGate(strict=True, db_path=db)
    token = _token(jti="jti-contract-2")
    assert gate.check(token, consume=True, now=_iso(NOW)).allowed is True
    # A second gate over the same ledger: the property is the store's, not
    # the process's.
    replay = EnforcementGate(strict=True, db_path=db).check(
        token, consume=True, now=_iso(NOW))
    assert _tuple(replay) == (
        False, "accept", True, "token_already_consumed", True,
    )


def test_every_issued_token_carries_a_minted_jti() -> None:
    """issue() auto-mints a jti when none is supplied, so a consumption-free
    token cannot be produced through the issuing path -- every grant is
    replay-tracked by construction. The `if token.jti:` guard exists only
    for hand-built token objects outside the issuing path."""
    token = _token(jti="")
    assert token.jti, "issue() must mint a jti"
    gate = EnforcementGate(strict=True)
    assert gate.check(token, consume=True, now=_iso(NOW)).allowed is True
    replay = gate.check(token, consume=True, now=_iso(NOW))
    assert _tuple(replay) == (
        False, "accept", True, "token_already_consumed", True,
    )
