# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The governed path's one reading of the current time (remora.timebase).

Unset, it is the system clock, as before. ``REMORA_TIME_SOURCE_MODULE`` lets a
host that embeds REMORA (a simulator, a replay) supply the time instead, so
expiry and freshness are judged on the host's clock. The setting is refused in
production, and a source that answers with anything but an aware datetime is
refused rather than coerced.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta, timezone

import pytest

from remora import timebase

FIXED = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(timebase.TIME_SOURCE_ENV, raising=False)
    monkeypatch.delenv("REMORA_ENV", raising=False)
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "timebase-test-key")
    timebase.reset_time_source()
    yield
    timebase.reset_time_source()


def _host(monkeypatch, name: str, **attrs: object) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv(timebase.TIME_SOURCE_ENV, name)
    timebase.reset_time_source()


def test_unset_reads_the_system_clock() -> None:
    before = datetime.now(UTC)
    now = timebase.utc_now()
    after = datetime.now(UTC)
    assert before <= now <= after
    assert now.tzinfo is UTC
    assert timebase.host_time_source() is None


def test_host_module_supplies_the_time(monkeypatch) -> None:
    _host(monkeypatch, "host_clock_fixed", utc_now=lambda: FIXED)
    assert timebase.utc_now() == FIXED
    assert timebase.unix_now() == FIXED.timestamp()
    assert timebase.host_time_source() == "host_clock_fixed"


def test_host_time_is_read_on_every_call(monkeypatch) -> None:
    state = {"now": FIXED}
    _host(monkeypatch, "host_clock_moving", utc_now=lambda: state["now"])
    assert timebase.utc_now() == FIXED
    state["now"] = FIXED + timedelta(minutes=10)
    assert timebase.utc_now() == FIXED + timedelta(minutes=10)


def test_host_time_in_another_zone_is_returned_in_utc(monkeypatch) -> None:
    oslo = timezone(timedelta(hours=1))
    _host(monkeypatch, "host_clock_zone", utc_now=lambda: FIXED.astimezone(oslo))
    now = timebase.utc_now()
    assert now == FIXED and now.tzinfo is UTC


@pytest.mark.parametrize("answer", [FIXED.replace(tzinfo=None), FIXED.timestamp(), None, "2030"])
def test_answer_that_is_not_an_aware_datetime_is_refused(monkeypatch, answer) -> None:
    _host(monkeypatch, "host_clock_bad", utc_now=lambda: answer)
    with pytest.raises(timebase.TimeSourceError, match="timezone-aware datetime"):
        timebase.utc_now()


def test_source_that_raises_is_refused_not_replaced_by_the_system_clock(monkeypatch) -> None:
    def broken() -> datetime:
        raise RuntimeError("clock unavailable")

    _host(monkeypatch, "host_clock_raises", utc_now=broken)
    with pytest.raises(timebase.TimeSourceError, match="clock unavailable"):
        timebase.utc_now()


def test_module_without_utc_now_is_refused(monkeypatch) -> None:
    _host(monkeypatch, "host_clock_empty")
    with pytest.raises(timebase.TimeSourceError, match="utc_now"):
        timebase.utc_now()


def test_module_that_cannot_be_imported_is_refused(monkeypatch) -> None:
    monkeypatch.setenv(timebase.TIME_SOURCE_ENV, "no_such_host_clock_module")
    timebase.reset_time_source()
    with pytest.raises(timebase.TimeSourceError, match="no_such_host_clock_module"):
        timebase.utc_now()


@pytest.mark.parametrize("env", ["production", "prod"])
def test_host_time_source_is_refused_in_production(monkeypatch, env) -> None:
    _host(monkeypatch, "host_clock_prod", utc_now=lambda: FIXED)
    monkeypatch.setenv("REMORA_ENV", env)
    timebase.reset_time_source()
    with pytest.raises(timebase.TimeSourceError, match="production"):
        timebase.utc_now()


def test_refusal_is_not_cached_as_no_source(monkeypatch) -> None:
    _host(monkeypatch, "host_clock_empty_again")
    with pytest.raises(timebase.TimeSourceError):
        timebase.utc_now()
    with pytest.raises(timebase.TimeSourceError):
        timebase.utc_now()


def test_token_expiry_follows_the_host_clock(monkeypatch) -> None:
    """The reason the seam exists: a token's lifetime is judged on host time."""
    from remora.enforcement.token import PolicyDecisionToken

    state = {"now": FIXED}
    _host(monkeypatch, "host_clock_token", utc_now=lambda: state["now"])
    token = PolicyDecisionToken.issue(
        "accept", "hash1", "req-1", FIXED.isoformat(),
        expires_at=(FIXED + timedelta(seconds=60)).isoformat())

    assert token.verify().verified is True
    state["now"] = FIXED + timedelta(seconds=61)
    assert token.verify().reason == "token_expired"


def test_token_issued_on_host_time_is_live_whatever_the_system_clock_says(monkeypatch) -> None:
    """Host time years away from the system clock: without the seam the token is
    either expired on arrival or not yet valid."""
    from remora.enforcement.token import PolicyDecisionToken

    for host_now in (datetime(2001, 1, 1, tzinfo=UTC), datetime(2090, 1, 1, tzinfo=UTC)):
        _host(monkeypatch, "host_clock_far", utc_now=lambda at=host_now: at)
        token = PolicyDecisionToken.issue("accept", "hash1", "req-1", host_now.isoformat())
        assert token.verify().verified is True
