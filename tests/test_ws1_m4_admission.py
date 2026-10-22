# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""WS1-M4 M4.1c: atomic admission on the ACCEPT path (SDD §4, §5; topology ADR).

With ``REMORA_WS1_MAX_CLOCK_SKEW_MS`` declared under WS1 enforce, redeeming an
ACCEPT grant runs one transaction on the durable state backend. It reads the
database instant and the authority epochs under lock, re-checks the
re-gate's evidence receipts, consumes the grant on the same connection,
records the dispatch intent and enqueues the admission event, and commits
all of it or none of it.

These tests drive ``/v1/execution/execute-accepted`` against SQLite
(``REMORA_CHAIN_DB``) and, with ``REMORA_PG_DSN`` set, against Postgres, the
reference backend; the Postgres cases run in the coverage job's Postgres
pass (``-k postgres``). The database instant is injected through
``Ws1Admission.clock`` so a lapse can be placed exactly between the re-gate
and admission. Each refusal is shown to leave the grant unspent by a later
redemption of the same grant that executes.
"""
from __future__ import annotations

import dataclasses
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")

from remora.enforcement.gate import EnforcementGate  # noqa: E402
from remora.verification.resolvers import InMemorySource  # noqa: E402
from tests.test_ws1_execution_binding import _events, _install, _mint, _mod, _redeem  # noqa: E402
from tests.test_ws1_execution_binding import client as _route_client  # noqa: E402,F401
from tests.verification import ws1_deployment_fixture as fixture  # noqa: E402

SUBJECT = "source:asset-inventory"


PG_DSN = os.environ.get("REMORA_PG_DSN", "").strip()


class _Backend:
    """The state database the admission transaction runs on."""

    def __init__(self, kind: str, target: str) -> None:
        self.kind, self.target = kind, target

    def connect(self):
        if self.kind == "postgres":
            import psycopg
            return psycopg.connect(self.target, autocommit=True)
        return sqlite3.connect(self.target)

    def query(self, sql: str, *params):
        ph = "%s" if self.kind == "postgres" else "?"
        conn = self.connect()
        try:
            return conn.execute(sql.replace("?", ph), params).fetchone()
        except Exception:
            return None
        finally:
            conn.close()

    def consumed(self, jti: str) -> bool:
        return self.query("SELECT 1 FROM pep_consumed WHERE jti = ?", jti) is not None

    def intents(self, jti: str) -> int:
        row = self.query("SELECT COUNT(*) FROM execution_outbox WHERE grant_jti = ?", jti)
        return int(row[0]) if row else 0


@pytest.fixture(params=["sqlite", "postgres"])
def db(request, _route_client, monkeypatch, tmp_path):  # noqa: F811
    """The route client on a durable state backend, with admission on."""
    exec_mod = _mod()
    monkeypatch.delenv("REMORA_STATE_ENDPOINT", raising=False)
    if request.param == "postgres":
        if not PG_DSN:
            pytest.skip("REMORA_PG_DSN not set (runs in the Postgres pass)")
        backend = _Backend("postgres", PG_DSN)
        monkeypatch.setenv("REMORA_PG_DSN", PG_DSN)
        monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
        gate = EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE, dsn=PG_DSN)
        # Epochs are per database, and earlier cases advanced them.
        conn = backend.connect()
        try:
            conn.execute("DELETE FROM authority_revision WHERE tenant_id = 'acme'")
        except Exception:
            pass
        finally:
            conn.close()
    else:
        backend = _Backend("sqlite", str(tmp_path / "state.db"))
        monkeypatch.setenv("REMORA_CHAIN_DB", backend.target)
        monkeypatch.delenv("REMORA_PG_DSN", raising=False)
        gate = EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE,
                               db_path=backend.target)
    monkeypatch.setenv("REMORA_WS1_MAX_CLOCK_SKEW_MS", "0")
    monkeypatch.setattr(exec_mod, "_GATE", gate)
    monkeypatch.setattr(exec_mod, "_WS1_ADMISSION", None)
    exec_mod._reset_outbox()
    return {"client": _route_client, "backend": backend}


def _clock():
    return {"ms": time.time_ns() // 1_000_000}


def _setup(monkeypatch, *, ttl_s=60, db_offset_ms=0, **deployment):
    """Install the WS1 gate and admission sharing one controllable clock.

    ``db_offset_ms`` is how far the database instant runs ahead of the clock
    the re-gate's evidence was stamped with.
    """
    clock = _clock()
    gate = _install(monkeypatch, "enforce", clock_ms=lambda: clock["ms"], resolvers={
        "assets": InMemorySource("assets", "asset-inventory", fixture.ASSETS, ttl_s=ttl_s)},
        **deployment)
    exec_mod = _mod()
    admission = exec_mod._ws1_admission()
    assert admission is not None
    offset = {"ms": db_offset_ms}
    monkeypatch.setattr(exec_mod, "_WS1_ADMISSION", dataclasses.replace(
        admission, clock=lambda conn: clock["ms"] + offset["ms"]))
    return gate, clock, offset, admission


def _admitted_events(jti):
    _mod().drain_audit_outbox("acme")
    return [e for e in _events("execution_admitted") if e["grant_jti"] == jti]


def _grant(gate):
    """A fresh ACCEPT grant; a unique proposal keeps Postgres runs independent."""
    return _mint(gate, proposal_id=f"p-m4-{uuid4().hex}")


def _detail(r):
    return r.status_code, r.json().get("detail")


def test_an_admitted_grant_executes_and_records_its_admission(db, monkeypatch):
    gate, _, _, _ = _setup(monkeypatch)
    token = _grant(gate)
    r = _redeem(db["client"], token)
    assert r.status_code == 200, r.text
    assert r.json()["tool_execution"]["executed"] is True
    assert db["backend"].consumed(token["jti"])
    (event,) = _admitted_events(token["jti"])
    assert event["grant_jti"] == token["jti"] and event["receipt_count"] == 1
    assert event["authority_epochs"] == {SUBJECT: 0}


def test_m4_t02_evidence_lapsing_after_the_regate_refuses_unspent(db, monkeypatch):
    """Control 2b with admission on: the lapse is seen at the database
    instant, the call refuses, and the grant stays spendable."""
    gate, _, offset, _ = _setup(monkeypatch, ttl_s=1, db_offset_ms=5_000)
    token = _grant(gate)
    r = _redeem(db["client"], token)
    assert _detail(r) == (409, "evidence_expired_at_admission")
    assert not db["backend"].consumed(token["jti"]) and db["backend"].intents(token["jti"]) == 0
    assert not _events("execution_authorized")
    offset["ms"] = 0
    assert _redeem(db["client"], token).json()["tool_execution"]["executed"] is True


def test_m4_t10_equality_at_valid_until_is_expired(db, monkeypatch):
    gate, clock, offset, _ = _setup(monkeypatch, ttl_s=1)
    token = _grant(gate)
    # The resolver stamps whole seconds: valid_until = now_s + 1.
    offset["ms"] = ((clock["ms"] // 1000) + 1) * 1000 - clock["ms"]
    assert _detail(_redeem(db["client"], token)) == (409, "evidence_expired_at_admission")
    offset["ms"] -= 1
    assert _redeem(db["client"], token).status_code == 200


def test_a_declared_skew_shortens_validity(db, monkeypatch):
    gate, _, _, admission = _setup(monkeypatch, ttl_s=1)
    exec_mod = _mod()
    monkeypatch.setattr(exec_mod, "_WS1_ADMISSION", dataclasses.replace(
        exec_mod._WS1_ADMISSION, max_clock_skew_ms=1_000))
    assert _detail(_redeem(db["client"], _grant(gate))) == (409, "evidence_expired_at_admission")


@pytest.mark.parametrize(("revoked", "reason"), [(False, "authority_epoch_stale"),
                                                 (True, "authority_revoked")])
def test_m4_t04_an_epoch_advanced_during_the_regate_refuses(db, monkeypatch, revoked, reason):
    """The subject's epoch is read before the lookups; an advance committed
    before admission makes the receipt stale (INV-M4-02, revoke first)."""
    gate, _, _, admission = _setup(monkeypatch)
    token = _grant(gate)
    real = gate.evaluate

    def advance_during(**kwargs):
        outcome = real(**kwargs)
        admission.epochs.advance(SUBJECT, tenant_id="acme", revoked=revoked)
        return outcome

    monkeypatch.setattr(gate, "evaluate", advance_during)
    assert _detail(_redeem(db["client"], token)) == (409, reason)
    assert not db["backend"].consumed(token["jti"]) and db["backend"].intents(token["jti"]) == 0
    monkeypatch.setattr(gate, "evaluate", real)
    expected = 409 if revoked else 200  # a revoked subject stays revoked
    assert _redeem(db["client"], token).status_code == expected


def test_m4_t05_a_revocation_after_admission_does_not_unsend(db, monkeypatch):
    """Admit first: the call runs, and the later revocation is recorded at a
    higher epoch. INV-M4-02 orders the two; it does not undo a send."""
    gate, _, _, admission = _setup(monkeypatch)
    token = _grant(gate)
    assert _redeem(db["client"], token).status_code == 200
    assert admission.epochs.advance(SUBJECT, tenant_id="acme", revoked=True) == 1
    (event,) = _admitted_events(token["jti"])
    assert event["authority_epochs"] == {SUBJECT: 0}


def test_m4_t06_one_grant_redeemed_concurrently_admits_once(db, monkeypatch):
    gate, _, _, _ = _setup(monkeypatch)
    token = _grant(gate)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _redeem(db["client"], token), range(8)))
    executed = [r for r in results if r.status_code == 200
                and r.json()["tool_execution"]["executed"]]
    assert len(executed) == 1, [r.text for r in results]
    assert db["backend"].intents(token["jti"]) == 1 and len(_admitted_events(token["jti"])) == 1


def test_m4_t11_a_crash_between_consumption_and_commit_spends_nothing(db, monkeypatch):
    gate, _, _, _ = _setup(monkeypatch)
    token = _grant(gate)
    exec_mod = _mod()
    real = exec_mod._record_dispatch_intent

    def crash(**kwargs):
        raise RuntimeError("process died after the grant was consumed")

    monkeypatch.setattr(exec_mod, "_record_dispatch_intent", crash)
    assert _detail(_redeem(db["client"], token)) == (
        409, "admission_backend_unavailable:RuntimeError")
    assert not db["backend"].consumed(token["jti"]) and db["backend"].intents(token["jti"]) == 0
    monkeypatch.setattr(exec_mod, "_record_dispatch_intent", real)
    assert _redeem(db["client"], token).status_code == 200
    assert db["backend"].intents(token["jti"]) == 1


def test_m4_t12_an_audit_failure_rolls_the_admission_back(db, monkeypatch):
    gate, _, _, _ = _setup(monkeypatch)
    token = _grant(gate)
    exec_mod = _mod()
    real = exec_mod.chain_append_transactional

    def broken(*args, **kwargs):
        raise OSError("audit outbox unavailable")

    monkeypatch.setattr(exec_mod, "chain_append_transactional", broken)
    assert _detail(_redeem(db["client"], token)) == (409, "admission_backend_unavailable:OSError")
    assert not db["backend"].consumed(token["jti"]) and db["backend"].intents(token["jti"]) == 0
    monkeypatch.setattr(exec_mod, "chain_append_transactional", real)
    assert _redeem(db["client"], token).status_code == 200


def test_m4_t13_an_unreachable_epoch_store_refuses_before_any_lookup(db, monkeypatch, tmp_path):
    gate, _, _, _ = _setup(monkeypatch)
    token = _grant(gate)
    exec_mod = _mod()
    from remora.governance.authority_epochs import AuthorityEpochs

    unreachable = AuthorityEpochs(db_path=str(tmp_path / "missing" / "epochs.db"),
                                  connection_provider=exec_mod._ACTIVE_TX_CONNECTION.get)
    monkeypatch.setattr(exec_mod, "_WS1_ADMISSION", dataclasses.replace(
        exec_mod._WS1_ADMISSION, epochs=unreachable))
    assert _detail(_redeem(db["client"], token)) == (409, "authority_epochs_unavailable")
    assert not db["backend"].consumed(token["jti"])


def test_a_replayed_grant_is_refused_on_the_enlisted_ledger(db, monkeypatch):
    gate, _, _, _ = _setup(monkeypatch)
    token = _grant(gate)
    assert _redeem(db["client"], token).status_code == 200
    assert _detail(_redeem(db["client"], token)) == (409, "token_already_consumed")
    assert db["backend"].intents(token["jti"]) == 1


def test_without_a_declared_skew_the_residual_is_unchanged(db, monkeypatch):
    """Admission is opt-in outside the strict profile: no skew, no admission,
    and control 2b still runs (tests/test_ws1_gate_controls.py)."""
    monkeypatch.delenv("REMORA_WS1_MAX_CLOCK_SKEW_MS")
    _install(monkeypatch, "enforce")
    assert _mod()._ws1_admission() is None


def test_admission_refuses_a_d1_state_endpoint(db, monkeypatch):
    monkeypatch.setenv("REMORA_STATE_ENDPOINT", "https://state.example")
    _install(monkeypatch, "enforce")
    with pytest.raises(ValueError, match="D1"):
        _mod()._ws1_admission()


@pytest.mark.parametrize("raw", ["", "abc", "-1", "5001"])
def test_the_strict_profile_requires_a_declared_skew_under_ws1_enforce(monkeypatch, raw):
    from remora.profiles import RuntimeProfileError
    from remora.toolcall.runtime_profile import _check_ws1_admission

    monkeypatch.setenv("REMORA_WS1_MODE", "enforce")
    monkeypatch.setenv("REMORA_WS1_MAX_CLOCK_SKEW_MS", raw)
    with pytest.raises(RuntimeProfileError, match="REMORA_WS1_MAX_CLOCK_SKEW_MS"):
        _check_ws1_admission("review")
    monkeypatch.setenv("REMORA_WS1_MAX_CLOCK_SKEW_MS", "500")
    _check_ws1_admission("review")
    monkeypatch.setenv("REMORA_STATE_ENDPOINT", "https://state.example")
    with pytest.raises(RuntimeProfileError, match="D1"):
        _check_ws1_admission("review")


# ── the approved-review and async worker paths (owner decision: the grant
# is minted and consumed in the claim's admission transaction) ──────────

from tests.test_ws1_execution_binding import (  # noqa: E402
    WRITE_CALL,
    _as_role,
    _assess_write,
    _review_deployment,
    _reviewed_item,
)


def _execute(client, item_id):
    return client.post("/v1/execution/execute",
                       json={"item_id": item_id, "tool_call": WRITE_CALL})


def test_the_review_path_admits_in_the_claim_transaction(db, monkeypatch):
    _setup(monkeypatch)
    item_id = _reviewed_item(db["client"])
    r = _execute(db["client"], item_id)
    assert r.status_code == 200, r.text
    assert r.json()["tool_execution"]["executed"] is True
    jti = r.json()["execution_grant"]["jti"]
    assert db["backend"].consumed(jti)
    (event,) = _admitted_events(jti)
    assert event["outbox_id"] and event["receipt_count"] == 1


def test_the_review_path_refuses_a_lapse_after_its_regate_unspent(db, monkeypatch):
    """M4-T02 on the review path: the approval was honoured and the intent
    recorded, then the evidence lapsed before the claim. Nothing is spent,
    nothing runs, and the intent settles REFUSED under the admission reason."""
    _setup(monkeypatch, ttl_s=1, db_offset_ms=5_000)
    item_id = _reviewed_item(db["client"])
    r = _execute(db["client"], item_id)
    assert r.status_code == 200, r.text
    execution = r.json()["tool_execution"]
    assert execution["executed"] is False
    assert execution["refusal_reason"] == "evidence_expired_at_admission"
    assert not db["backend"].consumed(r.json()["execution_grant"]["jti"])
    assert not _admitted_events(r.json()["execution_grant"]["jti"])


def test_a_review_precondition_admits_under_its_role_epoch(db, monkeypatch):
    _setup(monkeypatch, **_review_deployment())
    item_id = _assess_write(db["client"])["review_item_id"]
    _as_role(monkeypatch, "change-manager")
    assert db["client"].post("/v1/execution/approve", json={"item_id": item_id}).status_code == 200
    r = _execute(db["client"], item_id)
    assert r.status_code == 200, r.text
    assert r.json()["tool_execution"]["executed"] is True
    (event,) = _admitted_events(r.json()["execution_grant"]["jti"])
    assert set(event["authority_epochs"]) == {SUBJECT, "review:change-manager"}


def test_revoking_the_review_role_refuses_the_approved_call(db, monkeypatch):
    _, _, _, admission = _setup(monkeypatch, **_review_deployment())
    item_id = _assess_write(db["client"])["review_item_id"]
    _as_role(monkeypatch, "change-manager")
    assert db["client"].post("/v1/execution/approve", json={"item_id": item_id}).status_code == 200
    gate = _mod()._ws1_gate()
    real = gate.evaluate

    def revoke_during(**kwargs):
        outcome = real(**kwargs)
        admission.epochs.advance("review:change-manager", tenant_id="acme", revoked=True)
        return outcome

    monkeypatch.setattr(gate, "evaluate", revoke_during)
    execution = _execute(db["client"], item_id).json()["tool_execution"]
    assert (execution["executed"], execution["refusal_reason"]) == (False, "authority_revoked")


def _pending(client, monkeypatch):
    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
    item_id = _reviewed_item(client)
    assert _execute(client, item_id).status_code in (200, 202)
    return item_id


def test_the_worker_admits_in_the_claim_transaction(db, monkeypatch):
    _setup(monkeypatch)
    _pending(db["client"], monkeypatch)
    (result,) = _mod().dispatch_pending_intents("acme", worker_id="w-1")
    assert result["tool_execution"]["executed"] is True
    jti = _events("execution_authorized")[-1]["grant_jti"]
    assert db["backend"].consumed(jti) and len(_admitted_events(jti)) == 1


def test_the_worker_refuses_a_lapse_and_settles_the_row(db, monkeypatch):
    _, _, offset, _ = _setup(monkeypatch, ttl_s=1)
    _pending(db["client"], monkeypatch)
    offset["ms"] = 5_000
    (result,) = _mod().dispatch_pending_intents("acme", worker_id="w-1")
    assert result["tool_execution"]["executed"] is False
    assert result["tool_execution"]["refusal_reason"] == "evidence_expired_at_admission"
    assert not _events("execution_authorized")
    assert _mod().dispatch_pending_intents("acme", worker_id="w-2") == []


def test_two_workers_claim_one_row_once(db, monkeypatch):
    _setup(monkeypatch)
    _pending(db["client"], monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda n: _mod().dispatch_pending_intents("acme", worker_id=f"w-{n}"), range(4)))
    executed = [r for batch in results for r in batch if r["tool_execution"]["executed"]]
    assert len(executed) == 1
    assert len(_events("execution_authorized")) == 1
