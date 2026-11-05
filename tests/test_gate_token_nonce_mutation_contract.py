# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Gate ledger, token and durable nonce store contracts the mutation sweep found unpinned.

The 2026-10-13 mutmut sweep over remora/enforcement/{gate,token,nonce_store}.py
left survivors in places that decide outcomes: the D1 ledger's SQL and
endpoint, the fail-closed ``consumed_ledger_unavailable`` refusal and its
event, the exact ``TokenVerificationResult`` of every signature refusal, the
key rotation and revocation lists, and the D1 commit discipline that tells a
replayed nonce apart from an outage. Each test below names the behaviour it
pins. Mutants argued equivalent, or reachable only on Postgres, are listed in
tests/data/mutation_equivalent_gate_token_nonce.txt instead of being covered
by vacuous tests.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from remora.enforcement import token as token_mod
from remora.enforcement.gate import EnforcementGate, EnforcementResult
from remora.enforcement.nonce_store import DurableNonceStore, NonceStoreUnavailable
from remora.enforcement.token import (
    MAX_TOKEN_TTL_SECONDS,
    AuthorizationContext,
    PolicyDecisionToken,
    TokenVerificationResult,
    _canonical_payload,
    _compute_signature,
    _hash_observation,
)
from remora.persistence import d1_connection as d1

KEY = "mutation-contract-key"
OBS = "o" * 64
ENDPOINT = "http://state.invalid/query"
LOGGER = "remora.governance"

_ENV = (
    "REMORA_RUNTIME_PROFILE", "REMORA_SIGNATURE_FORMAT", "REMORA_PDP_ISSUER",
    "REMORA_PDP_SIGNING_KID", "REMORA_PDP_PREVIOUS_KEYS", "REMORA_PDP_REVOKED_KIDS",
    d1.ENDPOINT_ENV,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", KEY)
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _grant(action: str = "accept", **kw: Any) -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(
        action=action, observation_hash=OBS, request_id="req-1",
        issued_at=kw.pop("issued_at", _now()), **kw)


def _hand_signed(key: bytes = KEY.encode(), **over: Any) -> PolicyDecisionToken:
    """A token signed outside issue(), for shapes issue() never mints."""
    issued = datetime.now(UTC)
    fields: dict[str, Any] = dict(
        action="accept", observation_hash=OBS, request_id="req-h",
        issued_at=issued.isoformat(),
        expires_at=(issued + timedelta(seconds=300)).isoformat(),
        jti="jti-h", audience="", kid="", issuer="", context_hash="", format="",
    )
    fields.update(over)
    payload = _canonical_payload(
        fields["action"], fields["observation_hash"], fields["request_id"],
        fields["issued_at"], fields["expires_at"], fields["jti"], fields["audience"],
        fields["kid"], fields["issuer"], fields["context_hash"], fields["format"])
    sig = _compute_signature(payload, key, fields["format"])
    return PolicyDecisionToken(signature=sig, is_signed=True, **fields)


def _events(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.name == LOGGER and r.getMessage().startswith(name + " ")]


class SqliteD1:
    """A D1 endpoint backed by real SQLite, one transaction per batch.

    Unlike a string-matching fake, it executes the gate's and the store's
    actual SQL, so a broken statement fails here the way it fails on D1, and
    a UNIQUE violation surfaces at the batch that carries the INSERT.
    """

    def __init__(self, path: Path) -> None:
        self.path = str(path)
        self.calls: list[tuple[str | None, list[dict[str, Any]]]] = []

    def post(self, statements: list[dict[str, Any]], url: str | None = None) -> list[list[dict[str, Any]]]:
        self.calls.append((url, statements))
        resolved = (url or "").strip() or d1.endpoint()
        if resolved != ENDPOINT:
            raise d1.D1Unavailable(f"{d1.ENDPOINT_ENV} is not set")
        conn = sqlite3.connect(self.path)
        try:
            out: list[list[dict[str, Any]]] = []
            for st in statements:
                cur = conn.execute(st["sql"], st.get("params") or [])
                cols = [c[0] for c in cur.description or []]
                out.append([dict(zip(cols, row, strict=True)) for row in cur.fetchall()])
            conn.commit()
            return out
        except sqlite3.Error as exc:
            conn.rollback()
            raise d1.D1Unavailable(f"state store refused: {exc}") from exc
        finally:
            conn.close()

    def sql(self) -> list[str]:
        return [st["sql"] for _, batch in self.calls for st in batch]


@pytest.fixture()
def fake_d1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SqliteD1:
    fake = SqliteD1(tmp_path / "d1.db")
    monkeypatch.setattr(d1, "_post", fake.post)
    return fake


# ══ EnforcementGate ════════════════════════════════════════════════════════


def test_a_default_gate_is_strict() -> None:
    """Production posture is the default: an unsigned token is refused."""
    gate = EnforcementGate()
    assert gate.strict is True
    unsigned = dataclasses.replace(_grant(), signature="", is_signed=False)
    result = gate.check(unsigned)
    assert (result.allowed, result.reason) == (
        False, "token_verification_failed:token_not_signed")


def test_an_in_memory_db_path_is_refused_naming_the_ledger() -> None:
    """The refusal says which guarantee an in-memory ledger would remove."""
    with pytest.raises(ValueError, match=r"^PEP consumed-jti ledger: ':memory:'"):
        EnforcementGate(db_path=":memory:")


def test_check_does_not_consume_by_default() -> None:
    """A plain check is a peek: the grant stays redeemable exactly once."""
    gate = EnforcementGate(strict=True)
    grant = _grant()
    assert gate.check(grant).allowed is True
    assert gate.check(grant).allowed is True
    assert gate.check(grant, consume=True).allowed is True
    assert gate.check(grant, consume=True).reason == "token_already_consumed"


def test_a_signed_grant_without_jti_is_refused_in_strict_mode() -> None:
    """A jti-less grant cannot be tracked, so strict mode refuses to spend it."""
    gate = EnforcementGate(strict=True)
    result = gate.check(_hand_signed(jti=""), consume=True)
    assert result == EnforcementResult(
        allowed=False, action="accept", token_verified=True,
        reason="token_missing_jti", strict_mode=True)


def test_a_naive_issued_at_is_read_as_utc_not_refused() -> None:
    """A naive issued_at is coerced to UTC; it must not trip the
    naive/aware subtraction into issued_at_unparseable."""
    naive_now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    result = EnforcementGate(strict=True).check(_grant(issued_at=naive_now))
    assert (result.allowed, result.reason) == (True, "accept")


@pytest.fixture()
def local_clock_not_utc() -> Iterator[None]:
    """Run with a local zone five hours east of UTC.

    The age and expiry checks must read the clock in UTC; a naive local
    clock relabelled as UTC is off by the local offset, which a UTC CI host
    can never notice.
    """
    if hasattr(time, "tzset"):
        old = os.environ.get("TZ")
        os.environ["TZ"] = "XYZ-5"
        time.tzset()
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
    else:
        if not datetime.now().astimezone().utcoffset():
            pytest.skip("local zone is UTC and cannot be changed on this platform")
        yield


def test_gate_age_check_reads_the_clock_in_utc(local_clock_not_utc: None) -> None:
    result = EnforcementGate(strict=True).check(_grant())
    assert (result.allowed, result.reason) == (True, "accept")


def test_token_expiry_reads_the_clock_in_utc(local_clock_not_utc: None) -> None:
    assert _grant().verify(OBS) == TokenVerificationResult(True, "ok", True)


def test_deprecated_enforce_still_binds_the_observation() -> None:
    """enforce() must pass the expected observation hash to check()."""
    gate = EnforcementGate(strict=True)
    ran: list[bool] = []
    with pytest.warns(DeprecationWarning), \
            pytest.raises(PermissionError, match="observation_hash_mismatch"):
        gate.enforce(_grant(), lambda: ran.append(True),
                     expected_observation_hash="x" * 64)
    assert ran == []


# ── ledger integrity report ────────────────────────────────────────────────


def test_the_in_process_ledger_reports_unknown_not_intact() -> None:
    gate = EnforcementGate(strict=True)
    gate.check(_grant(), consume=True)
    assert gate.verify_ledger() == {
        "durable": False,
        "intact": None,
        "consumed_rows": 1,
        "high_water_mark": None,
        "last_reset_reason": None,
        "problems": [
            "in-process ledger: consumed grants are lost on restart, "
            "so integrity cannot be verified. Set REMORA_PG_DSN or "
            "REMORA_CHAIN_DB."
        ],
    }


def test_a_fresh_durable_ledger_has_a_zero_watermark(tmp_path: Path) -> None:
    """No watermark row means nothing was ever consumed: mark 0, intact."""
    gate = EnforcementGate(strict=True, db_path=str(tmp_path / "l.db"))
    report = gate.verify_ledger()
    assert (report["high_water_mark"], report["intact"], report["problems"]) == (0, True, [])


def test_a_deleted_grant_is_reported_with_the_missing_count(tmp_path: Path) -> None:
    db = str(tmp_path / "l.db")
    gate = EnforcementGate(strict=True, db_path=db)
    for _ in range(3):
        assert gate.check(_grant(), consume=True).allowed
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM pep_consumed WHERE rowid IN "
                     "(SELECT rowid FROM pep_consumed LIMIT 1)")
    report = gate.verify_ledger()
    assert report["intact"] is False
    assert report["problems"][0].startswith(
        "ledger holds 2 consumed grants but 3 were consumed: 1 missing.")


def test_a_watermark_reset_requires_a_reason() -> None:
    gate = EnforcementGate(strict=True)
    for reason in ("", "   "):
        with pytest.raises(ValueError,
                           match=r"^resetting the ledger watermark requires a reason$"):
            gate.reset_ledger_watermark(reason=reason)


def test_the_in_process_ledger_has_no_watermark_to_reset() -> None:
    with pytest.raises(RuntimeError, match=r"^no durable ledger to re-baseline; "
                                           r"the in-process ledger has no watermark$"):
        EnforcementGate(strict=True).reset_ledger_watermark(reason="prune")


# ── the D1 ledger, against real SQL ────────────────────────────────────────


def test_the_d1_ledger_schema_and_watermark_are_real_sql(fake_d1: SqliteD1) -> None:
    """The D1 CREATE and watermark SELECT must run on SQLite, not just be sent."""
    gate = EnforcementGate(strict=True, state_endpoint=ENDPOINT)
    assert gate.check(_grant(), consume=True).allowed is True
    assert gate.verify_ledger() == {
        "durable": True, "intact": True, "consumed_rows": 1,
        "high_water_mark": 1, "last_reset_reason": None, "problems": [],
    }


def test_the_d1_ledger_talks_to_the_endpoint_it_was_given(fake_d1: SqliteD1) -> None:
    """An explicit state_endpoint wins over an empty environment: every
    ledger statement goes to it, so the gate never silently loses its store."""
    gate = EnforcementGate(strict=True, state_endpoint=ENDPOINT)
    assert gate.check(_grant(), consume=True).allowed is True
    assert gate.verify_ledger()["durable"] is True
    assert fake_d1.calls and {url for url, _ in fake_d1.calls} == {ENDPOINT}


def test_a_d1_peek_or_a_refused_decision_never_spends(fake_d1: SqliteD1) -> None:
    """Only an allowed, consuming check writes the ledger."""
    gate = EnforcementGate(strict=True, state_endpoint=ENDPOINT)
    reject = _grant(action="reject")
    assert gate.check(reject, consume=True).reason == "decision_reject_not_accept"
    assert gate.check(reject).reason == "decision_reject_not_accept"
    grant = _grant()
    assert gate.check(grant).allowed is True
    assert gate.check(grant, consume=True).allowed is True
    assert gate.check(grant, consume=True).reason == "token_already_consumed"
    assert gate.verify_ledger()["consumed_rows"] == 1


def test_a_d1_double_spend_is_refused_in_full(fake_d1: SqliteD1) -> None:
    """The second spend reaches D1's UNIQUE violation at commit, a branch of
    its own. Its refusal must carry the decision and the verified signature
    like every other refusal: a settlement or audit reader keys on them, and
    a None there reads as "never verified"."""
    gate = EnforcementGate(strict=True, state_endpoint=ENDPOINT)
    grant = _grant()
    assert gate.check(grant, consume=True).allowed is True
    assert gate.check(grant, consume=True) == EnforcementResult(
        allowed=False, action="accept", token_verified=True,
        reason="token_already_consumed", strict_mode=True)


def test_the_gate_holds_a_grant_to_the_context_it_was_minted_for() -> None:
    """A signed grant bound to one tenant's context is refused under another's:
    the context the caller hands check() must reach the token's verification."""
    minted = AuthorizationContext(tenant="acme", principal="agent-1")
    grant = _grant(context=minted)
    gate = EnforcementGate(strict=True)
    assert gate.check(grant, context=minted).allowed is True
    foreign = dataclasses.replace(minted, tenant="globex")
    assert gate.check(grant, context=foreign) == EnforcementResult(
        allowed=False, action="accept", token_verified=False,
        reason="token_verification_failed:context_mismatch", strict_mode=True)


def test_a_d1_ledger_can_be_rebaselined_after_an_authorized_prune(fake_d1: SqliteD1) -> None:
    """verify_ledger reported D1 but reset_ledger_watermark had no D1 branch
    (found by this sweep): a Cloudflare deployment could see the watermark and
    never re-baseline it, and was told its ledger was in-process."""
    gate = EnforcementGate(strict=True, state_endpoint=ENDPOINT)
    for _ in range(2):
        assert gate.check(_grant(), consume=True).allowed is True
    with sqlite3.connect(fake_d1.path) as conn:
        conn.execute("DELETE FROM pep_consumed WHERE rowid = (SELECT MIN(rowid) FROM pep_consumed)")
    assert gate.verify_ledger()["intact"] is False
    gate.reset_ledger_watermark(reason="pruned grants older than 90 days")
    assert gate.verify_ledger() == {
        "durable": True, "intact": True, "consumed_rows": 1, "high_water_mark": 1,
        "last_reset_reason": "pruned grants older than 90 days", "problems": [],
    }


def test_the_unsigned_token_warning_names_the_caller_of_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The warning used stacklevel=2 from _check_unlogged and so pointed at
    check() inside gate.py; it must point at the code that called check()."""
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
    gate = EnforcementGate(strict=False)
    with pytest.warns(UserWarning, match="unsigned token accepted") as caught:
        gate.check(_grant())
    assert caught[0].filename == __file__


# ── fail closed on an unavailable ledger ───────────────────────────────────


def _sqlite_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*_a: Any, **_k: Any) -> Any:
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(sqlite3, "connect", down)


@pytest.mark.parametrize("strict", [True, False])
def test_a_sqlite_outage_is_the_named_refusal_and_event(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture, strict: bool) -> None:
    gate = EnforcementGate(strict=strict, db_path=str(tmp_path / "l.db"))
    grant = _grant()
    _sqlite_outage(monkeypatch)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        result = gate.check(grant, consume=True)
    assert result == EnforcementResult(
        allowed=False, action="accept", token_verified=True,
        reason="consumed_ledger_unavailable", strict_mode=strict)
    (rec,) = _events(caplog, "grant.ledger_unavailable")
    assert rec.levelno == logging.WARNING
    assert rec.remora == {  # type: ignore[attr-defined]
        "backend": "sqlite", "error_class": "OperationalError",
        "token_jti": grant.jti}


def test_a_d1_outage_names_its_backend(
        fake_d1: SqliteD1, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    gate = EnforcementGate(strict=True, state_endpoint=ENDPOINT)
    grant = _grant()

    def down(statements: Any, url: Any = None) -> Any:
        raise d1.D1Unavailable("state store unreachable: injected")
    monkeypatch.setattr(d1, "_post", down)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        result = gate.check(grant, consume=True)
    assert result.reason == "consumed_ledger_unavailable"
    (rec,) = _events(caplog, "grant.ledger_unavailable")
    assert rec.remora == {  # type: ignore[attr-defined]
        "backend": "d1", "error_class": "D1Unavailable", "token_jti": grant.jti}


# ══ PolicyDecisionToken ════════════════════════════════════════════════════


def test_the_signing_key_is_none_when_unset_or_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    """None, not b"": a2a_envelope signs whenever the key is not None, so an
    empty key would sign envelopes with a known HMAC key."""
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY")
    assert token_mod._get_signing_key() is None
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "   ")
    assert token_mod._get_signing_key() is None
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", " k ")
    assert token_mod._get_signing_key() == b"k"


def test_previous_keys_parse_skips_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty, '='-less, kid-less and key-less entries are skipped; the
    rest of the list is still read."""
    assert token_mod._previous_keys() == {}
    monkeypatch.setenv("REMORA_PDP_PREVIOUS_KEYS",
                       " a = k1 ,,junk, =orphan, empty= ,b=k2")
    assert token_mod._previous_keys() == {"a": b"k1", "b": b"k2"}


def test_a_previous_key_may_end_in_base64_padding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the first '=' separates kid from key. A base64 key ends in '='
    padding; splitting at the last one would drop the rotated key and
    refuse every token it signed."""
    monkeypatch.setenv("REMORA_PDP_PREVIOUS_KEYS", "old=YQ==")
    assert token_mod._previous_keys() == {"old": b"YQ=="}
    assert _hand_signed(key=b"YQ==", kid="old").verify(OBS).verified is True


def test_a_kid_with_an_empty_previous_key_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """'old=' must not register b"" as old's key: anyone could sign with it."""
    monkeypatch.setenv("REMORA_PDP_PREVIOUS_KEYS", "old=")
    forged = _hand_signed(key=b"", kid="old")
    assert forged.verify(OBS) == TokenVerificationResult(False, "unknown_kid", True)


def test_a_previous_key_after_a_junk_entry_still_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_PDP_PREVIOUS_KEYS", "junk,k2=key-two")
    assert _hand_signed(key=b"key-two", kid="k2").verify(OBS).verified is True


def test_revoked_kids_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    assert token_mod._revoked_kids() == frozenset()
    monkeypatch.setenv("REMORA_PDP_REVOKED_KIDS", "k1,k2, ,k3 ")
    assert token_mod._revoked_kids() == frozenset({"k1", "k2", "k3"})


def test_a_kidless_token_is_refused_when_the_current_kid_is_revoked(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A token that omits its kid cannot dodge revocation of the key."""
    grant = _grant()  # minted with no kid configured
    monkeypatch.setenv("REMORA_PDP_SIGNING_KID", "cur")
    monkeypatch.setenv("REMORA_PDP_REVOKED_KIDS", "cur")
    assert grant.verify(OBS) == TokenVerificationResult(False, "kid_revoked", True)


def test_a_named_revoked_kid_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_PDP_SIGNING_KID", "cur")
    grant = _grant()
    monkeypatch.setenv("REMORA_PDP_REVOKED_KIDS", "cur")
    assert grant.verify(OBS) == TokenVerificationResult(False, "kid_revoked", True)


def test_an_unknown_kid_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_PDP_SIGNING_KID", "gone")
    grant = _grant()
    monkeypatch.setenv("REMORA_PDP_SIGNING_KID", "cur")
    assert grant.verify(OBS) == TokenVerificationResult(False, "unknown_kid", True)


def test_no_signing_key_refuses_as_unsigned(monkeypatch: pytest.MonkeyPatch) -> None:
    grant = _grant()
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY")
    assert grant.verify(OBS) == TokenVerificationResult(False, "no_signing_key", False)


@pytest.mark.parametrize("over", [{"is_signed": False}, {"signature": ""}])
def test_either_unsigned_marker_refuses(over: dict[str, Any]) -> None:
    """is_signed is not inside the signed payload, so a valid signature on
    a token marked unsigned is still refused; either marker alone suffices."""
    token = dataclasses.replace(_grant(), **over)
    assert token.verify(OBS) == TokenVerificationResult(False, "token_not_signed", False)


def test_an_unknown_format_is_refused() -> None:
    token = dataclasses.replace(_grant(), format="v9")
    assert token.verify(OBS) == TokenVerificationResult(False, "token_format_unknown", True)


def test_a_live_v1_token_under_a_strict_v2_contract_is_legacy(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    legacy = _grant()
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    assert legacy.verify(OBS) == TokenVerificationResult(False, "token_format_legacy", True)


def test_historical_verification_reports_a_signed_v1() -> None:
    assert _grant().verify_historical() == TokenVerificationResult(True, "historical_v1", True)


def test_issuer_mismatch_is_a_signed_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    grant = _grant()
    monkeypatch.setenv("REMORA_PDP_ISSUER", "pdp-b")
    assert grant.verify(OBS) == TokenVerificationResult(False, "issuer_mismatch", True)


def test_not_yet_valid_carries_the_signed_flag() -> None:
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert _grant(issued_at=future).verify(OBS) == TokenVerificationResult(
        False, "token_not_yet_valid", True)


def test_the_ttl_cap_is_inclusive() -> None:
    issued = datetime.now(UTC)
    at_cap = (issued + timedelta(seconds=MAX_TOKEN_TTL_SECONDS)).isoformat()
    assert _grant(issued_at=issued.isoformat(), expires_at=at_cap).expires_at == at_cap
    with pytest.raises(ValueError, match="token TTL must be in"):
        _grant(issued_at=issued.isoformat(),
               expires_at=(issued + timedelta(seconds=MAX_TOKEN_TTL_SECONDS + 1)).isoformat())


def test_an_unset_issuer_is_empty() -> None:
    assert _grant().issuer == ""


def test_an_unsigned_token_still_carries_every_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a key, issue() mints an unsigned token, but not a stripped one:
    the non-strict gate and the audit record read these fields."""
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KID", "k-7")
    monkeypatch.setenv("REMORA_PDP_ISSUER", "pdp-a")
    monkeypatch.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    token = PolicyDecisionToken.issue(
        action="accept", observation_hash=OBS, request_id="req-u",
        issued_at=_now(), audience="pep")
    assert token.is_signed is False and token.signature == ""
    assert (token.request_id, token.audience, token.kid, token.issuer, token.format) == (
        "req-u", "pep", "k-7", "pdp-a", "v2")
    assert len(token.jti) == 36


def test_the_context_hash_preimage_includes_execution_context_hash() -> None:
    """Pinned against an independent recomputation of the preimage."""
    ctx = AuthorizationContext(tenant="t", principal="p", execution_context_hash="e" * 64)
    expected = hashlib.sha256(json.dumps({
        "execution_context_hash": "e" * 64, "intent_authority_hash": "",
        "policy_bundle_hash": "", "principal": "p", "target_environment": "",
        "tenant": "t", "toolspec_hash": "",
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert ctx.hash() == expected
    assert ctx.hash() != dataclasses.replace(ctx, execution_context_hash="f" * 64).hash()


def test_observation_hashing_stringifies_non_json_values() -> None:
    when = datetime(2026, 10, 13, tzinfo=UTC)
    expected = hashlib.sha256(json.dumps(
        {"when": str(when)}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert _hash_observation({"when": when}) == expected


# ══ DurableNonceStore ══════════════════════════════════════════════════════


def test_the_placeholder_follows_the_backend_dialect(tmp_path: Path) -> None:
    assert DurableNonceStore(dsn="postgresql://x.invalid/db")._placeholder() == "%s"
    assert DurableNonceStore(db_path=str(tmp_path / "n.db"))._placeholder() == "?"


@pytest.mark.parametrize(("message", "duplicate"), [
    ("unique violation", True),
    ("UNIQUE constraint failed: lease_nonce_consumed.nonce", True),
    ("duplicate key value", True),
    ("primary key conflict", True),
    ("constraint failed", True),
    ("disk I/O error", False),
    ("connection reset", False),
])
def test_only_a_uniqueness_violation_reads_as_a_duplicate(
        tmp_path: Path, message: str, duplicate: bool) -> None:
    """Each marker suffices on its own; anything else is unknown (fail closed)."""
    store = DurableNonceStore(db_path=str(tmp_path / "n.db"))
    assert store._is_duplicate(RuntimeError(message)) is duplicate


def test_refusal_messages_name_what_is_missing(tmp_path: Path) -> None:
    store = DurableNonceStore(db_path=str(tmp_path / "n.db"))
    with pytest.raises(ValueError, match=r"^refusing to consume an empty nonce$"):
        store.try_consume("", tenant_id="acme")
    with pytest.raises(ValueError, match=r"^refusing to consume a nonce with no tenant scope$"):
        store.try_consume("n-1", tenant_id="")


def test_an_unreachable_store_names_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = DurableNonceStore(db_path=str(tmp_path / "n.db"))

    def boom() -> Any:
        raise OSError("socket gone")
    monkeypatch.setattr(store, "_connect", boom)
    with pytest.raises(NonceStoreUnavailable) as caught:
        store.try_consume("n-1", tenant_id="acme")
    assert str(caught.value) == "lease nonce store unreachable: socket gone"


def test_a_fresh_store_counts_and_reads_without_a_prior_write(tmp_path: Path) -> None:
    """The read paths create the schema themselves; a new store is empty, not broken."""
    assert DurableNonceStore(db_path=str(tmp_path / "a.db")).consumed_count(tenant_id="acme") == 0
    assert DurableNonceStore(db_path=str(tmp_path / "b.db")).consumed("n", tenant_id="acme") is False


def _d1_store(fake: SqliteD1, monkeypatch: pytest.MonkeyPatch) -> DurableNonceStore:
    monkeypatch.setenv(d1.ENDPOINT_ENV, ENDPOINT)
    return DurableNonceStore(state_endpoint=ENDPOINT)


def test_a_d1_replay_is_a_duplicate_not_an_outage(
        fake_d1: SqliteD1, monkeypatch: pytest.MonkeyPatch) -> None:
    """D1 buffers writes until commit, so the UNIQUE violation arrives at
    commit. The store must commit inside the duplicate handler: a replay
    returns False, it does not raise NonceStoreUnavailable."""
    store = _d1_store(fake_d1, monkeypatch)
    assert store.try_consume("n-1", tenant_id="acme") is True
    assert store.try_consume("n-1", tenant_id="acme") is False
    assert store.consumed("n-1", tenant_id="acme") is True
    assert store.consumed_count(tenant_id="acme") == 1


def test_the_d1_schema_is_created_once_per_store(
        fake_d1: SqliteD1, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every D1 statement is a network round trip; the DDL is sent once."""
    store = _d1_store(fake_d1, monkeypatch)
    store.try_consume("n-1", tenant_id="acme")
    store.consumed("n-1", tenant_id="acme")
    store.consumed_count(tenant_id="acme")
    assert sum(s.startswith("CREATE TABLE") for s in fake_d1.sql()) == 1


# ── third sweep (2026-10-13): survivors on lines the second round covered ──

def test_a_sqlite_peek_never_spends_the_grant(tmp_path: Path) -> None:
    """``allowed and consume`` guards the INSERT. Were it ``or``, a check without
    consume would spend the grant and the real redemption would be refused."""
    gate = EnforcementGate(strict=True, db_path=str(tmp_path / "pep.db"))
    grant = _grant()
    assert gate.check(grant).allowed is True
    assert gate.verify_ledger()["consumed_rows"] == 0
    assert (gate.check(grant, consume=True).allowed, gate.verify_ledger()["consumed_rows"]) == (True, 1)


def test_a_bad_signature_is_a_signed_refusal() -> None:
    """``signature_invalid`` reports is_signed=True: the token claims a signature
    that does not hold, which is a forgery signal, not an unsigned token."""
    forged = _hand_signed(key=b"another-key")
    assert forged.verify() == TokenVerificationResult(
        verified=False, reason="signature_invalid", is_signed=True)


def test_issue_defaults_to_no_audience_and_accepts_a_one_second_ttl() -> None:
    issued = datetime.now(UTC)
    one_second = (issued + timedelta(seconds=1)).isoformat()
    grant = _grant(issued_at=issued.isoformat(), expires_at=one_second)
    assert grant.audience == ""
    assert grant.expires_at == one_second


def _enforce_warning():
    gate = EnforcementGate(strict=True)
    with pytest.warns(DeprecationWarning) as caught:
        gate.enforce(_grant(), action_fn=lambda: None)
    (warning,) = [w for w in caught if w.category is DeprecationWarning]
    return warning


def test_the_deprecated_enforce_names_itself() -> None:
    assert str(_enforce_warning().message).startswith(
        "EnforcementGate.enforce() checks a token without its authorization context")


def test_the_deprecated_enforce_warning_names_its_caller() -> None:
    """Deselected inside the mutation sweep: mutmut's trampoline adds frames."""
    assert _enforce_warning().filename == __file__


def test_a_peek_at_a_spent_grant_reports_it_spent(tmp_path: Path, fake_d1: SqliteD1) -> None:
    """A check without consume still reads the ledger: a spent grant must not
    look redeemable to the caller who asks before redeeming (SQLite and D1)."""
    for gate in (EnforcementGate(strict=True, db_path=str(tmp_path / "pep.db")),
                 EnforcementGate(strict=True, state_endpoint=ENDPOINT)):
        grant = _grant()
        assert gate.check(grant, consume=True).allowed is True
        assert gate.check(grant) == EnforcementResult(
            allowed=False, action="accept", token_verified=True,
            reason="token_already_consumed", strict_mode=True)


# ── follow-up to #842: the count row is positional on every backend ──────


def test_the_count_is_read_positionally_and_carries_no_alias(
        fake_d1: SqliteD1, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``consumed_count`` reads ``row[0]``. sqlite3 and psycopg return tuples
    by default and ``D1Connection.fetchone()`` converts its dict rows, so a
    column alias would never be read by name: the query must not carry one,
    and the count must still be right on both local backends."""
    sqlite_store = DurableNonceStore(db_path=str(tmp_path / "count.db"))
    d1_store = _d1_store(fake_d1, monkeypatch)
    for store in (sqlite_store, d1_store):
        assert store.try_consume("n-1", tenant_id="acme") is True
        assert store.try_consume("n-2", tenant_id="acme") is True
        assert store.try_consume("n-3", tenant_id="globex") is True
        assert store.consumed_count(tenant_id="acme") == 2
        assert store.consumed_count(tenant_id="globex") == 1
        assert store.consumed_count(tenant_id="nobody") == 0
    # Case-insensitive on purpose: keyword case is not what this test pins,
    # and the sweep lists the statement's case-only mutants as equivalent.
    counts = [s.upper() for s in fake_d1.sql() if s.upper().startswith("SELECT COUNT")]
    assert counts, "the D1 fake saw no count query"
    assert all(" AS " not in s for s in counts)


# ── the gate spends inside the caller's transaction (atomic admission) ────────
#
# The 2026-11-04 sweep found EnforcementGate._spend_enlisted unpinned: the
# refusal of a gate that cannot join a transaction, its operational event, and
# the whole result of each branch. tests/test_atomic_admission.py drives it
# through AtomicAdmission and asserts reasons; this pins the gate's own contract.


def _tuple(r: EnforcementResult) -> tuple[bool, str, bool, str, bool]:
    return (r.allowed, r.action, r.token_verified, r.reason, r.strict_mode)


def test_an_in_process_gate_refuses_to_join_a_transaction_in_full(caplog: pytest.LogCaptureFixture) -> None:
    gate = EnforcementGate(strict=True)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = gate.check(_grant(), OBS, consume=True, connection=object())
    assert _tuple(result) == (False, "accept", True, "consumed_ledger_unavailable", True)
    [record] = [r for r in caplog.records if r.name == LOGGER
                and r.getMessage().startswith("grant.ledger_unavailable ")]
    payload = record.remora  # type: ignore[attr-defined]
    assert (payload["backend"], payload["error_class"]) == ("not_enlistable", "RuntimeError")
    assert payload["token_jti"] == _grant().jti or payload["token_jti"]  # a jti is logged


def test_a_sqlite_gate_spends_once_on_the_callers_connection(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    db = str(tmp_path / "enlisted.db")
    gate = EnforcementGate(strict=True, db_path=db)
    grant = _grant()
    with sqlite3.connect(db) as conn, caplog.at_level(logging.INFO, logger=LOGGER):
        assert _tuple(gate.check(grant, OBS, consume=False, connection=conn)) == (
            True, "accept", True, "accept", True)
        # The operational record says the check rode on the caller's transaction.
        [checked] = [r for r in caplog.records if r.getMessage().startswith("grant.checked ")]
        assert checked.remora["enlisted"] is True  # type: ignore[attr-defined]
        assert checked.remora["consumed"] is False  # type: ignore[attr-defined]
        caplog.clear()
        assert _tuple(gate.check(grant, OBS, consume=True, connection=conn)) == (
            True, "accept", True, "accept", True)
        # The spend is on the caller's transaction and visible to it before commit.
        assert conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone() == (1,)
        assert _tuple(gate.check(grant, OBS, consume=True, connection=conn)) == (
            False, "accept", True, "token_already_consumed", True)
        assert _tuple(gate.check(grant, OBS, consume=False, connection=conn)) == (
            False, "accept", True, "token_already_consumed", True)
        conn.commit()
    # Outside the transaction the ledger agrees, and the watermark counted one spend.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert _tuple(gate.check(grant, OBS, consume=True)) == (
            False, "accept", True, "token_already_consumed", True)
    [checked] = [r for r in caplog.records if r.getMessage().startswith("grant.checked ")]
    assert "enlisted" not in checked.remora  # type: ignore[attr-defined]
    assert gate.verify_ledger()["high_water_mark"] == 1


def test_a_refused_decision_on_the_callers_connection_spends_nothing(tmp_path: Path) -> None:
    db = str(tmp_path / "enlisted.db")
    gate = EnforcementGate(strict=True, db_path=db)
    with sqlite3.connect(db) as conn:
        assert _tuple(gate.check(_grant("reject"), OBS, consume=True, connection=conn)) == (
            False, "reject", True, "decision_reject_not_accept", True)
        assert conn.execute("SELECT COUNT(*) FROM pep_consumed").fetchone() == (0,)


def test_a_broken_callers_connection_is_the_named_refusal(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        def execute(self, *a: Any, **k: Any) -> Any:
            raise sqlite3.OperationalError("database is locked")

    gate = EnforcementGate(strict=True, db_path=str(tmp_path / "enlisted.db"))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = gate.check(_grant(), OBS, consume=True, connection=Broken())
    assert _tuple(result) == (False, "accept", True, "consumed_ledger_unavailable", True)
    [record] = [r for r in caplog.records if r.name == LOGGER
                and r.getMessage().startswith("grant.ledger_unavailable ")]
    payload = record.remora  # type: ignore[attr-defined]
    assert (payload["backend"], payload["error_class"]) == ("sqlite", "OperationalError")


def test_the_watermark_report_names_the_unaccounted_rows(tmp_path: Path) -> None:
    db = str(tmp_path / "l.db")
    gate = EnforcementGate(strict=True, db_path=db)
    assert gate.check(_grant(), consume=True).allowed
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO pep_consumed (jti) VALUES ('out-of-band-1'), ('out-of-band-2')")
    report = gate.verify_ledger()
    assert report["intact"] is False
    assert report["problems"][0].startswith(
        "ledger holds 3 consumed grants but its high-water mark records only 1: "
        "2 unaccounted rows.")
