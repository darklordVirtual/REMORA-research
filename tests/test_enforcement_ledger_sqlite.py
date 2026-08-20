# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SQLite-backed consumed-grant ledger: integrity reporting and re-baselining.

``enforcement/gate.py`` is the file that actually consumes a one-time grant,
and it was the least-covered file in the trusted computing base (73.6% with
branches). The Postgres branches are exercised by the dedicated Postgres
contract job; these tests cover the SQLite and in-process branches, the
error paths, and — most importantly — the property the ledger exists for:
a deleted row must be detectable.
"""
from __future__ import annotations

import sqlite3

import pytest

from remora.enforcement.gate import EnforcementGate


@pytest.fixture
def db(tmp_path) -> str:
    return str(tmp_path / "pep.db")


def _gate(db_path: str) -> EnforcementGate:
    return EnforcementGate(strict=True, audience="pep://test", db_path=db_path)


def test_in_process_ledger_reports_unknown_not_intact() -> None:
    """Without durability, integrity is unknown — never 'fine'."""
    report = EnforcementGate(strict=True, audience="pep://test").verify_ledger()
    assert report["durable"] is False
    assert report["intact"] is None
    assert report["high_water_mark"] is None
    assert any("in-process" in p for p in report["problems"])


def test_sqlite_ledger_starts_empty_and_intact(db: str) -> None:
    report = _gate(db).verify_ledger()
    assert report["durable"] is True
    assert report["consumed_rows"] == 0


def test_consumed_grants_are_counted_against_the_watermark(db: str) -> None:
    gate = _gate(db)
    with sqlite3.connect(db) as conn:
        for jti in ("a", "b", "c"):
            conn.execute("INSERT INTO pep_consumed (jti) VALUES (?)", (jti,))
        conn.execute(
            "INSERT INTO pep_ledger_watermark (id, issued_count) VALUES (1, 3) "
            "ON CONFLICT (id) DO UPDATE SET issued_count = 3"
        )
    report = gate.verify_ledger()
    assert report["consumed_rows"] == 3
    assert report["high_water_mark"] == 3
    assert report["intact"] is True


def test_a_deleted_row_is_detected(db: str) -> None:
    """The whole point of the high-water mark.

    Without it, deleting consumed-grant rows would silently re-enable every
    replay those rows were refusing.
    """
    gate = _gate(db)
    with sqlite3.connect(db) as conn:
        for jti in ("a", "b", "c"):
            conn.execute("INSERT INTO pep_consumed (jti) VALUES (?)", (jti,))
        conn.execute(
            "INSERT INTO pep_ledger_watermark (id, issued_count) VALUES (1, 3) "
            "ON CONFLICT (id) DO UPDATE SET issued_count = 3"
        )
        conn.execute("DELETE FROM pep_consumed WHERE jti = 'b'")
    report = gate.verify_ledger()
    assert report["intact"] is False
    assert report["consumed_rows"] == 2
    assert report["high_water_mark"] == 3
    assert report["problems"]


def test_re_baselining_requires_a_reason(db: str) -> None:
    gate = _gate(db)
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="reason"):
            gate.reset_ledger_watermark(reason=bad)


def test_re_baselining_records_the_reason(db: str) -> None:
    gate = _gate(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO pep_consumed (jti) VALUES ('a')")
    gate.reset_ledger_watermark(reason="restored from backup 2026-08-20")
    report = gate.verify_ledger()
    assert report["high_water_mark"] == 1
    assert report["intact"] is True
    assert report["last_reset_reason"] == "restored from backup 2026-08-20"


def test_re_baselining_an_in_process_ledger_is_refused() -> None:
    """There is no watermark to re-baseline, and pretending there is hides it."""
    gate = EnforcementGate(strict=True, audience="pep://test")
    with pytest.raises(RuntimeError, match="no durable ledger"):
        gate.reset_ledger_watermark(reason="anything")
