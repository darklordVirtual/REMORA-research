# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The PEP's consumed-jti ledger over the D1 state endpoint.

Found by reading decision-os-min's HB-1 write-up against this gate: it knew
REMORA_PG_DSN and REMORA_CHAIN_DB but not REMORA_STATE_ENDPOINT, so the
Cloudflare deployment — which the durability guard admits on the endpoint —
silently fell to the in-memory set. A captured ACCEPT execution token could
be redeemed again after a container restart, inside its age window: the exact
replay class the durable ledger exists to close, reintroduced by a backend
the guard accepted but the gate never learned to use.

The store the one-time property lives in must also fail CLOSED: unreachable
never means unspent.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement.gate import EnforcementGate  # noqa: E402
from remora.enforcement.token import PolicyDecisionToken  # noqa: E402
from remora.persistence import d1_connection as d1  # noqa: E402

ENDPOINT = "http://state.internal/query"
ISSUED = datetime.now(UTC).isoformat()


class FakeD1:
    """A D1 endpoint with a real UNIQUE constraint and a kill switch."""

    def __init__(self) -> None:
        self.spent: set[str] = set()
        self.watermark = 0
        self.down = False

    def post(self, statements):
        if self.down:
            raise d1.D1Unavailable("state store unreachable: injected outage")
        results = []
        for statement in statements:
            sql = statement["sql"]
            params = statement.get("params") or []
            if sql.startswith("INSERT INTO pep_consumed"):
                jti = params[0]
                if jti in self.spent:
                    raise d1.D1Unavailable(
                        "state store refused: UNIQUE constraint failed: "
                        "pep_consumed.jti")
                self.spent.add(jti)
                results.append([])
            elif sql.startswith("SELECT 1 FROM pep_consumed"):
                results.append([{"1": 1}] if params[0] in self.spent else [])
            elif "pep_ledger_watermark" in sql and sql.startswith("INSERT"):
                self.watermark += 1
                results.append([])
            elif sql.startswith("SELECT COUNT(*) FROM pep_consumed"):
                results.append([{"n": len(self.spent)}])
            elif "SELECT issued_count" in sql:
                results.append([{"issued_count": self.watermark,
                                 "last_reset_reason": None}])
            else:  # CREATE TABLE and friends
                results.append([])
        return results


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """Signed tokens in strict mode — the production path, not a relaxed one."""
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "ledger-test-key")


@pytest.fixture()
def store(monkeypatch):
    fake = FakeD1()
    monkeypatch.setenv(d1.ENDPOINT_ENV, ENDPOINT)
    monkeypatch.setattr(d1, "_post", fake.post)
    return fake


@pytest.fixture()
def gate(store):
    return EnforcementGate(strict=True, audience="pep",
                           state_endpoint=ENDPOINT)


def _token(label: str) -> PolicyDecisionToken:
    """One signed grant, with the kernel-minted jti left intact.

    The replay tests re-present the SAME token object rather than minting a
    second one: a captured grant is the same bytes, and jti is inside the
    signed payload, so rewriting it would only produce an invalid signature
    the gate rejects for the wrong reason.
    """
    return PolicyDecisionToken.issue(
        action="accept", observation_hash="h" * 64,
        request_id=f"req-{label}", issued_at=ISSUED, audience="pep")


def test_a_grant_consumes_exactly_once(gate, store):
    grant = _token("once")
    first = gate.check(grant, consume=True)
    assert first.allowed is True
    assert grant.jti in store.spent
    assert store.watermark == 1, "the consumption is counted for the watermark"

    replay = gate.check(grant, consume=True)
    assert replay.allowed is False
    assert replay.reason == "token_already_consumed"


def test_the_ledger_survives_a_new_gate_instance(gate, store):
    """The restart scenario: a fresh process, the same durable store.

    This is the whole point. With the in-memory fallback the second gate
    starts empty and the captured token is good again.
    """
    captured = _token("restart")
    assert gate.check(captured, consume=True).allowed is True

    fresh = EnforcementGate(strict=True, audience="pep",
                            state_endpoint=ENDPOINT)
    replay = fresh.check(captured, consume=True)
    assert replay.allowed is False
    assert replay.reason == "token_already_consumed"


def test_an_unreachable_store_fails_closed(gate, store):
    """Unreachable never means unspent — assuming so IS the double-spend."""
    grant = _token("outage")
    store.down = True
    result = gate.check(grant, consume=True)
    assert result.allowed is False
    assert result.reason == "consumed_ledger_unavailable"

    store.down = False
    assert grant.jti not in store.spent, "nothing recorded during the outage"


def test_a_recovered_store_still_admits_the_grant(gate, store):
    """Failing closed must not burn the grant it could not record.

    An outage that silently consumed the token would turn a transient fault
    into a permanently unusable authorization.
    """
    grant = _token("recovered")
    store.down = True
    assert gate.check(grant, consume=True).allowed is False
    store.down = False
    assert gate.check(grant, consume=True).allowed is True


def test_verify_ledger_reports_the_durable_counts(gate, store):
    gate.check(_token("verify"), consume=True)
    report = gate.verify_ledger()
    assert report["durable"] is True
    assert report["consumed_rows"] == len(store.spent)
    assert report["intact"] is True


def test_the_gate_reads_every_backend_the_guard_admits():
    """The defect class, pinned.

    servers/api.py accepts three durable backends. A gate that knows fewer
    passes the guard and then quietly uses the in-memory set — which is how
    this was introduced. If a fourth backend is ever added to the guard, this
    test is where it must also be given to the gate.
    """
    import inspect

    from servers import api as api_module

    source = inspect.getsource(api_module._execution_state_dsn)
    admitted = {name for name in
                ("REMORA_PG_DSN", "REMORA_STATE_ENDPOINT", "REMORA_CHAIN_DB")
                if name in source}

    gate_source = inspect.getsource(EnforcementGate.__init__)
    for backend, attribute in (("REMORA_PG_DSN", "_dsn"),
                               ("REMORA_STATE_ENDPOINT", "_state_endpoint"),
                               ("REMORA_CHAIN_DB", "_db_path")):
        if backend in admitted:
            assert attribute in gate_source, (
                f"the durability guard admits {backend} but the gate has no "
                f"{attribute} — the jti ledger would fall to the in-memory set"
            )
