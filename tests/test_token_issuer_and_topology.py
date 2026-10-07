# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-002: the PDP token's issuer is compared, and its scope is stated.

Before: ``issuer`` was signed into every token but never compared. Probe at
b9ade2b: a token minted with REMORA_PDP_ISSUER=attacker verified ``ok`` after
the issuer was reset to remora-pdp. The token was also described as a PDP to
PEP boundary although on the execution API both sides share one process and
one HMAC key.

After: a verifier that names an expected issuer refuses any other
(``issuer_mismatch``); with no issuer configured nothing changes. The module
and the gap audit describe the token as a one-time grant record.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from remora.enforcement.token import PolicyDecisionToken


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "issuer-test-key")
    monkeypatch.delenv("REMORA_PDP_ISSUER", raising=False)


def _mint(monkeypatch, issuer: str | None) -> PolicyDecisionToken:
    if issuer is None:
        monkeypatch.delenv("REMORA_PDP_ISSUER", raising=False)
    else:
        monkeypatch.setenv("REMORA_PDP_ISSUER", issuer)
    return PolicyDecisionToken.issue(
        action="accept", observation_hash="h" * 64, request_id="r-1",
        issued_at=datetime.now(UTC).isoformat(), audience="pep")


def test_a_token_from_another_issuer_is_refused(monkeypatch) -> None:
    token = _mint(monkeypatch, "attacker")
    monkeypatch.setenv("REMORA_PDP_ISSUER", "remora-pdp")
    result = token.verify()
    assert (result.verified, result.reason) == (False, "issuer_mismatch")


def test_a_token_from_the_expected_issuer_verifies(monkeypatch) -> None:
    token = _mint(monkeypatch, "remora-pdp")
    assert token.verify().verified is True


def test_an_issuer_less_token_is_refused_when_an_issuer_is_expected(monkeypatch) -> None:
    token = _mint(monkeypatch, None)
    monkeypatch.setenv("REMORA_PDP_ISSUER", "remora-pdp")
    assert token.verify().reason == "issuer_mismatch"


def test_without_an_expected_issuer_verification_is_unchanged(monkeypatch) -> None:
    token = _mint(monkeypatch, "anyone")
    monkeypatch.delenv("REMORA_PDP_ISSUER")
    assert token.verify().verified is True


def test_the_token_does_not_claim_a_decision_enforcement_boundary() -> None:
    import remora.enforcement.token as module

    doc = module.__doc__ or ""
    assert "does NOT establish" in doc and "one-time grant record" in doc
