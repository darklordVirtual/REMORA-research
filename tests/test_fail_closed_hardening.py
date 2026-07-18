"""Fail-closed hardening regressions (2026-07-02 external review).

Covers three findings from the code-level review:

1. ``query_opa_policy`` returned ALLOW when OPA answered HTTP 200 with an
   empty result (undefined rule at the queried policy path) — a misconfigured
   ``policy_path`` failed open. Now: empty/undefined result → DENY.
2. ``AdaptiveThresholdEngine.get_threshold`` returned 0.0 for an unregistered
   name — maximally permissive for a lower-bound trust threshold, so a typo'd
   threshold name silently disabled a gate. Now: raises KeyError.
3. ``PolicyDecisionToken`` had no expiry (audit finding F-2), so a signed
   "accept" token could be replayed indefinitely. Now: opt-in ``expires_at``
   is signed into the payload and enforced by ``verify()``.
"""
from __future__ import annotations

import io
import json

import pytest

from remora.policy.adaptive_thresholds import AdaptiveThresholdEngine
from remora.policy.opa_adapter import query_opa_policy


# ---------------------------------------------------------------------------
# 1. query_opa_policy: empty OPA result must DENY
# ---------------------------------------------------------------------------

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _mock_opa_response(monkeypatch, body: dict) -> None:
    import urllib.request

    def fake_urlopen(req, timeout=None):
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_empty_result_denies(monkeypatch) -> None:
    """OPA 200 with {} result (undefined rule) must fail closed."""
    _mock_opa_response(monkeypatch, {"result": {}})
    assert query_opa_policy("delete_rows", "production", "critical") == "DENY"


def test_missing_result_key_denies(monkeypatch) -> None:
    _mock_opa_response(monkeypatch, {})
    assert query_opa_policy("delete_rows", "production", "critical") == "DENY"


def test_non_dict_non_true_result_denies(monkeypatch) -> None:
    _mock_opa_response(monkeypatch, {"result": "unexpected-string"})
    assert query_opa_policy("read_rows", "staging", "low") == "DENY"


def test_explicit_allow_true_allows(monkeypatch) -> None:
    _mock_opa_response(monkeypatch, {"result": {"allow": True}})
    assert query_opa_policy("read_rows", "staging", "low") == "ALLOW"


def test_bare_true_result_allows(monkeypatch) -> None:
    _mock_opa_response(monkeypatch, {"result": True})
    assert query_opa_policy("read_rows", "staging", "low") == "ALLOW"


def test_explicit_deny_still_denies(monkeypatch) -> None:
    _mock_opa_response(monkeypatch, {"result": {"allow": False}})
    assert query_opa_policy("delete_rows", "production", "critical") == "DENY"


# ---------------------------------------------------------------------------
# 2. AdaptiveThresholdEngine: unknown threshold name must fail loud
# ---------------------------------------------------------------------------

def test_unknown_threshold_name_raises() -> None:
    engine = AdaptiveThresholdEngine()
    engine.register_threshold("trust_critical_min", base_value=0.72,
                              min_value=0.5, max_value=0.95)
    with pytest.raises(KeyError) as excinfo:
        engine.get_threshold("trust_critcal_min")  # typo'd name
    assert "not registered" in str(excinfo.value)


def test_registered_threshold_returns_value() -> None:
    engine = AdaptiveThresholdEngine()
    engine.register_threshold("trust_critical_min", base_value=0.72,
                              min_value=0.5, max_value=0.95)
    assert engine.get_threshold("trust_critical_min") == 0.72


# ---------------------------------------------------------------------------
# 3. PolicyDecisionToken expiry
# ---------------------------------------------------------------------------

@pytest.fixture()
def signing_key(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "hardening-test-key")


def _issue(expires_at=None):
    from remora.enforcement.token import PolicyDecisionToken

    return PolicyDecisionToken.issue(
        action="accept",
        observation_hash="a" * 64,
        request_id="req-expiry-1",
        issued_at="2026-07-02T10:00:00+00:00",
        expires_at=expires_at,
    )


def test_expired_token_rejected(signing_key) -> None:
    token = _issue(expires_at="2026-07-02T10:05:00+00:00")
    result = token.verify(now="2026-07-02T10:06:00+00:00")
    assert not result.verified
    assert result.reason == "token_expired"


def test_unexpired_token_verifies(signing_key) -> None:
    token = _issue(expires_at="2026-07-02T10:05:00+00:00")
    result = token.verify(now="2026-07-02T10:04:59+00:00")
    assert result.verified


def test_expiry_boundary_is_exclusive(signing_key) -> None:
    """At exactly expires_at the token is already expired (current >= expiry)."""
    token = _issue(expires_at="2026-07-02T10:05:00+00:00")
    result = token.verify(now="2026-07-02T10:05:00+00:00")
    assert not result.verified
    assert result.reason == "token_expired"


def test_expiry_cannot_be_stripped(signing_key) -> None:
    """Removing expires_at from an expiring token invalidates the signature."""
    import dataclasses

    token = _issue(expires_at="2026-07-02T10:05:00+00:00")
    stripped = dataclasses.replace(token, expires_at=None)
    result = stripped.verify(now="2026-07-02T10:00:01+00:00")
    assert not result.verified
    # The signed payload covers the expiry, so stripping it breaks the
    # signature; the mandatory-expiry check is defence in depth behind it.
    assert result.reason in {"signature_invalid", "missing_expiry"}


def test_expiry_cannot_be_extended(signing_key) -> None:
    import dataclasses

    token = _issue(expires_at="2026-07-02T10:05:00+00:00")
    extended = dataclasses.replace(token, expires_at="2027-01-01T00:00:00+00:00")
    result = extended.verify(now="2026-07-02T10:06:00+00:00")
    assert not result.verified
    assert result.reason == "signature_invalid"


def test_no_expiry_tokens_no_longer_exist(signing_key) -> None:
    """F-2 CLOSED: issue() always sets a signed expiry (default TTL), and a
    token whose expiry was stripped is rejected outright."""
    import dataclasses

    token = _issue(expires_at=None)  # default TTL applied at issue
    assert token.expires_at is not None
    assert token.verify(now="2026-07-02T10:01:00+00:00").verified
    # Far-future verification fails: the default TTL has long passed.
    late = token.verify(now="2030-01-01T00:00:00+00:00")
    assert not late.verified
    assert late.reason == "token_expired"
    # A hand-crafted no-expiry token is rejected before signature evaluation.
    stripped = dataclasses.replace(token, expires_at=None)
    result = stripped.verify(now="2026-07-02T10:00:01+00:00")
    assert not result.verified
    assert result.reason in {"signature_invalid", "missing_expiry"}


def test_unparseable_expiry_rejected(signing_key) -> None:
    import dataclasses

    import pytest

    # Issue-time validation refuses an unparseable expiry outright...
    with pytest.raises(ValueError):
        _issue(expires_at="not-a-timestamp")
    # ...and a token tampered to carry one is rejected at verify time.
    token = _issue(expires_at="2026-07-02T10:05:00+00:00")
    tampered = dataclasses.replace(token, expires_at="not-a-timestamp")
    result = tampered.verify(now="2026-07-02T10:00:00+00:00")
    assert not result.verified
    assert result.reason in {"expiry_unparseable", "signature_invalid"}


def test_zulu_suffix_supported(signing_key) -> None:
    token = _issue(expires_at="2026-07-02T10:05:00Z")
    assert token.verify(now="2026-07-02T10:04:00Z").verified
    assert not token.verify(now="2026-07-02T10:06:00Z").verified
