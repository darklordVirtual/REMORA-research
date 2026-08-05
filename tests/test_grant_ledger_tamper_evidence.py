# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Deleting a consumed grant must be detectable, or replay is silently back.

Architect review of the AAE plan (2026-08-05): *"consumed_grants is a
security-critical table: if an attacker can delete a row, replay becomes
possible. The audit log is append-only; the grants ledger should have
equivalent protection — otherwise you have moved the tamper problem from
the log to the ledger."*

The ledger is what makes a one-time grant one-time. Nothing in the schema
stopped a row from disappearing, and a disappeared row does not fail
anything — it silently re-authorizes an execution that was already spent.
That is the quietest failure in the whole enforcement path.

This does not make deletion impossible; a database owner can always
delete. It makes deletion **evident**: the gate keeps a high-water mark
and reports when the ledger holds fewer grants than it has issued.
Legitimate pruning is still possible, but it must reset the mark
deliberately — the same discipline as an operator-authorized action
rather than a silent one.
"""
from __future__ import annotations

import sqlite3

import pytest

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.token import PolicyDecisionToken

SIGNING_KEY = "ledger-tamper-key"


def _token(jti_seed: str, monkeypatch) -> PolicyDecisionToken:
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", SIGNING_KEY)
    now = datetime.now(UTC)
    return PolicyDecisionToken.issue(
        action="accept",
        observation_hash="a" * 64,
        request_id=jti_seed,
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience="pep://test",
    )


@pytest.fixture()
def ledger_path(tmp_path):
    return str(tmp_path / "grants.db")


def _gate(ledger_path: str) -> EnforcementGate:
    return EnforcementGate(strict=True, audience="pep://test", db_path=ledger_path)


def test_untouched_ledger_verifies(ledger_path, monkeypatch) -> None:
    gate = _gate(ledger_path)
    for i in range(3):
        assert gate.check(_token(f"p-{i}", monkeypatch), "a" * 64,
                          consume=True).allowed

    report = gate.verify_ledger()
    assert report["intact"] is True
    assert report["consumed_rows"] == 3
    assert report["high_water_mark"] == 3
    assert report["problems"] == []


def test_deleted_grant_is_detected(ledger_path, monkeypatch) -> None:
    """The load-bearing case: a removed row re-opens a spent grant."""
    gate = _gate(ledger_path)
    tokens = [_token(f"p-{i}", monkeypatch) for i in range(3)]
    for token in tokens:
        assert gate.check(token, "a" * 64, consume=True).allowed

    # An attacker (or a careless cleanup script) removes one row.
    with sqlite3.connect(ledger_path) as conn:
        conn.execute("DELETE FROM pep_consumed WHERE jti = ?", (tokens[1].jti,))
        conn.commit()

    report = gate.verify_ledger()
    assert report["intact"] is False, (
        "a deleted grant that verifies clean means replay is silently back"
    )
    assert report["consumed_rows"] == 2
    assert report["high_water_mark"] == 3
    assert any("fewer" in p or "missing" in p for p in report["problems"]), (
        report["problems"]
    )


def test_detection_survives_a_new_gate_instance(ledger_path, monkeypatch) -> None:
    """The mark is durable, not process state — a restart must not amnesty
    a deletion that happened while the process was down."""
    gate = _gate(ledger_path)
    for i in range(2):
        gate.check(_token(f"p-{i}", monkeypatch), "a" * 64, consume=True)
    with sqlite3.connect(ledger_path) as conn:
        conn.execute("DELETE FROM pep_consumed")
        conn.commit()

    reopened = _gate(ledger_path)
    report = reopened.verify_ledger()
    assert report["intact"] is False
    assert report["consumed_rows"] == 0
    assert report["high_water_mark"] == 2


def test_deliberate_reset_is_possible_and_recorded(ledger_path, monkeypatch) -> None:
    """Legitimate pruning must remain possible — but as an explicit act."""
    gate = _gate(ledger_path)
    for i in range(2):
        gate.check(_token(f"p-{i}", monkeypatch), "a" * 64, consume=True)
    with sqlite3.connect(ledger_path) as conn:
        conn.execute("DELETE FROM pep_consumed")
        conn.commit()
    assert gate.verify_ledger()["intact"] is False

    gate.reset_ledger_watermark(reason="operator pruned expired grants")
    report = gate.verify_ledger()
    assert report["intact"] is True
    assert report["last_reset_reason"] == "operator pruned expired grants"


def test_in_process_ledger_reports_its_own_limitation() -> None:
    """Without a durable backend there is no ledger to protect, and saying
    'intact' would be a false comfort."""
    gate = EnforcementGate(strict=True, audience="pep://test")
    report = gate.verify_ledger()
    assert report["durable"] is False
    assert report["intact"] is None, (
        "an in-process ledger cannot be verified; None means unknown, not OK"
    )
