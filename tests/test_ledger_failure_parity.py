# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-015: every consumed-grant ledger backend fails the same way.

Before: the D1 path turned an outage into the named refusal
``consumed_ledger_unavailable``. Postgres and SQLite caught only the
uniqueness violation, so any other database error escaped the gate as an
exception: still fail closed, but with no ``grant.checked`` event and no
refusal record, so an operator could not tell an outage from a code fault.

After: the same outage on any backend refuses the grant with the same reason,
emits ``grant.ledger_unavailable`` naming the backend and error class, and
leaves the grant unspent, so it can still be redeemed exactly once when the
ledger is back.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import types
from datetime import UTC, datetime

import pytest

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken
from remora.persistence import d1_connection as d1


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "ledger-parity-key")


def _grant(label: str) -> PolicyDecisionToken:
    return PolicyDecisionToken.issue(
        action="accept", observation_hash="h" * 64, request_id=f"req-{label}",
        issued_at=datetime.now(UTC).isoformat(), audience="pep")


# -- a fake psycopg with the real exception hierarchy shape ------------------

def _fake_psycopg():
    mod = types.ModuleType("psycopg")

    class Error(Exception):
        pass

    class IntegrityError(Error):
        pass

    class OperationalError(Error):
        pass

    mod.Error, mod.IntegrityError, mod.OperationalError = Error, IntegrityError, OperationalError
    state = {"down": False, "spent": set()}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def transaction(self):
            return self

        def commit(self):
            pass

        def execute(self, sql, params=()):
            if sql.startswith("INSERT INTO pep_consumed"):
                if params[0] in state["spent"]:
                    raise IntegrityError("duplicate key")
                state["spent"].add(params[0])
            if sql.startswith("SELECT 1 FROM pep_consumed"):
                hit = params[0] in state["spent"]
                return types.SimpleNamespace(fetchone=lambda: (1,) if hit else None)
            return types.SimpleNamespace(fetchone=lambda: None)

    def connect(dsn):
        if state["down"]:
            raise OperationalError("connection refused")
        return _Conn()

    mod.connect = connect
    return mod, state


class _FakeD1:
    def __init__(self):
        self.down = False
        self.spent: set[str] = set()

    def post(self, statements, url=None):
        if self.down:
            raise d1.D1Unavailable("state store unreachable: injected outage")
        out = []
        for st in statements:
            sql, params = st["sql"], st.get("params") or []
            if sql.startswith("INSERT INTO pep_consumed"):
                if params[0] in self.spent:
                    raise d1.D1Unavailable("state store refused: UNIQUE constraint failed")
                self.spent.add(params[0])
            if sql.startswith("SELECT 1 FROM pep_consumed"):
                out.append([{"1": 1}] if params[0] in self.spent else [])
            else:
                out.append([])
        return out


@pytest.fixture(params=["sqlite", "postgres", "d1"])
def backend(request, tmp_path, monkeypatch):
    """(gate, take_down, bring_up) for one backend with an injectable outage."""
    if request.param == "sqlite":
        gate = EnforcementGate(strict=True, audience="pep", db_path=str(tmp_path / "ledger.db"))
        real = sqlite3.connect
        flag = {"down": False}

        def connect(*a, **k):
            if flag["down"]:
                raise sqlite3.OperationalError("unable to open database file")
            return real(*a, **k)

        monkeypatch.setattr(sqlite3, "connect", connect)
        return gate, lambda: flag.update(down=True), lambda: flag.update(down=False)
    if request.param == "postgres":
        mod, state = _fake_psycopg()
        monkeypatch.setitem(sys.modules, "psycopg", mod)
        gate = EnforcementGate(strict=True, audience="pep", dsn="postgresql://ledger.invalid/db")
        return gate, lambda: state.update(down=True), lambda: state.update(down=False)
    fake = _FakeD1()
    monkeypatch.setenv(d1.ENDPOINT_ENV, "http://state.invalid/query")
    monkeypatch.setattr(d1, "_post", fake.post)
    gate = EnforcementGate(strict=True, audience="pep", state_endpoint="http://state.invalid/query")
    return gate, lambda: setattr(fake, "down", True), lambda: setattr(fake, "down", False)


def test_an_outage_is_the_same_named_refusal_on_every_backend(backend, caplog) -> None:
    gate, take_down, _ = backend
    take_down()
    with caplog.at_level(logging.INFO):
        result = gate.check(_grant("outage"), consume=True)
    assert (result.allowed, result.reason) == (False, "consumed_ledger_unavailable")
    messages = [r.getMessage() for r in caplog.records]
    assert any("grant.ledger_unavailable" in m for m in messages), messages
    assert any("grant.checked" in m and "consumed_ledger_unavailable" in m for m in messages)


def test_an_outage_does_not_spend_the_grant(backend) -> None:
    gate, take_down, bring_up = backend
    grant = _grant("unspent")
    take_down()
    assert gate.check(grant, consume=True).allowed is False
    bring_up()
    assert gate.check(grant, consume=True).allowed is True
    replay = gate.check(grant, consume=True)
    assert (replay.allowed, replay.reason) == (False, "token_already_consumed")


def test_the_d1_transport_names_timeouts_and_malformed_answers(monkeypatch) -> None:
    import urllib.request

    def timeout(*a, **k):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    with pytest.raises(d1.D1Unavailable, match="unreachable"):
        d1._post([{"sql": "SELECT 1"}], url="http://state.invalid/query")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"<html>gateway error</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    with pytest.raises(d1.D1Unavailable, match="malformed"):
        d1._post([{"sql": "SELECT 1"}], url="http://state.invalid/query")
