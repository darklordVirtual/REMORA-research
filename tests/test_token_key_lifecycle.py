# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Phase 6: PolicyDecisionToken key lifecycle (kid, rotation overlap, revocation).

Old tokens must not break silently: a pre-lifecycle token (no kid) verifies
against the current key and, across a rotation, against the previous keys
until it expires. A token that names a kid is bound to exactly that key —
the kid is inside the signed payload, so it cannot be stripped or swapped.
"""
from __future__ import annotations

import pytest

from remora.enforcement.token import PolicyDecisionToken

OBS = "a" * 64
ISSUED = "2026-01-01T00:00:00+00:00"
EXPIRES = "2026-01-01T00:05:00+00:00"
NOW = "2026-01-01T00:01:00+00:00"


def _issue() -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(
        action="accept", observation_hash=OBS, request_id="r-1",
        issued_at=ISSUED, expires_at=EXPIRES, audience="pep",
    )


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in ("REMORA_PDP_SIGNING_KEY", "REMORA_PDP_SIGNING_KID",
                "REMORA_PDP_PREVIOUS_KEYS", "REMORA_PDP_REVOKED_KIDS",
                "REMORA_PDP_ISSUER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "key-2026")
    return monkeypatch


def test_kid_and_issuer_are_signed_and_round_trip(env) -> None:
    env.setenv("REMORA_PDP_SIGNING_KID", "k2026")
    env.setenv("REMORA_PDP_ISSUER", "pdp://remora")
    token = _issue()
    assert token.kid == "k2026" and token.issuer == "pdp://remora"
    assert PolicyDecisionToken.from_dict(token.to_dict()) == token
    assert token.verify(OBS, now=NOW).verified is True


def test_kid_cannot_be_stripped_or_swapped(env) -> None:
    env.setenv("REMORA_PDP_SIGNING_KID", "k2026")
    token = _issue()
    stripped = PolicyDecisionToken.from_dict({**token.to_dict(), "kid": ""})
    assert stripped.verify(OBS, now=NOW).verified is False
    env.setenv("REMORA_PDP_PREVIOUS_KEYS", "k-old=key-2026")
    swapped = PolicyDecisionToken.from_dict({**token.to_dict(), "kid": "k-old"})
    assert swapped.verify(OBS, now=NOW).verified is False


def test_rotation_overlap_keeps_old_kid_token_valid(env) -> None:
    env.setenv("REMORA_PDP_SIGNING_KID", "k-old")
    old_token = _issue()
    # Rotate: new current key, old key moves to the previous list.
    env.setenv("REMORA_PDP_SIGNING_KEY", "key-new")
    env.setenv("REMORA_PDP_SIGNING_KID", "k-new")
    env.setenv("REMORA_PDP_PREVIOUS_KEYS", "k-old=key-2026")
    assert old_token.verify(OBS, now=NOW).verified is True
    assert _issue().verify(OBS, now=NOW).verified is True  # new tokens too


def test_rotation_overlap_covers_pre_lifecycle_tokens(env) -> None:
    legacy = _issue()  # no kid configured
    assert legacy.kid == ""
    env.setenv("REMORA_PDP_SIGNING_KEY", "key-new")
    env.setenv("REMORA_PDP_PREVIOUS_KEYS", "k-old=key-2026")
    assert legacy.verify(OBS, now=NOW).verified is True


def test_revoked_kid_refuses_even_with_key_present(env) -> None:
    env.setenv("REMORA_PDP_SIGNING_KID", "k-bad")
    token = _issue()
    env.setenv("REMORA_PDP_REVOKED_KIDS", "k-bad")
    result = token.verify(OBS, now=NOW)
    assert result.verified is False
    assert result.reason == "kid_revoked"


def test_unknown_kid_refuses(env) -> None:
    env.setenv("REMORA_PDP_SIGNING_KID", "k-x")
    token = _issue()
    env.setenv("REMORA_PDP_SIGNING_KID", "k-y")  # k-x no longer current, not in previous
    result = token.verify(OBS, now=NOW)
    assert result.verified is False
    assert result.reason == "unknown_kid"


def test_dropped_previous_key_expires_old_tokens(env) -> None:
    env.setenv("REMORA_PDP_SIGNING_KID", "k-old")
    old_token = _issue()
    env.setenv("REMORA_PDP_SIGNING_KEY", "key-new")
    env.setenv("REMORA_PDP_SIGNING_KID", "k-new")
    # Overlap window closed: previous list emptied.
    assert old_token.verify(OBS, now=NOW).verified is False
