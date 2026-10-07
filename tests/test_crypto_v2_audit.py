# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-011 (C3): the tenant audit chain moves to v2 without re-signing.

Before: every entry is signed HMAC(key, entry_hash), untagged, whatever the
contract. Probe at c8cc91d: under ``review/v2`` new entries are still v1.

After: v1 entries are never re-signed. The first v2 append writes an
``AUDIT_VERSION_TRANSITION`` record that names the final v1 head
(``previous_chain_head``) and the new domain, and from that record on every
entry is signed ``v2:`` + HMAC(key, ``REMORA/AUDIT/v2 || 0x00 || entry_hash``).
A chain never goes back to v1. The verifier reads the era from the chain's
structure, not from what an entry claims, so v1 history stays verifiable as
it was signed, and a v1 signature after the transition is a finding.
"""
from __future__ import annotations

import hashlib
import hmac
import os

import pytest

from remora.crypto import SignatureDomain, preimage
from remora.governance.audit_signing import TRANSITION_EVENT
from remora.governance.tenant_chain import (
    SQLiteTenantChain,
    TenantAuditChain,
    verification_statuses,
)

KEY = "audit-test-key"


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def chain(request, tmp_path, monkeypatch):
    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", KEY)
    for name in ("REMORA_RUNTIME_PROFILE", "REMORA_SIGNATURE_FORMAT"):
        monkeypatch.delenv(name, raising=False)
    if request.param == "memory":
        return TenantAuditChain()
    if request.param == "sqlite":
        return SQLiteTenantChain(str(tmp_path / "chain.db"))
    dsn = os.environ.get("REMORA_PG_DSN", "").strip()
    if not dsn:
        pytest.skip("REMORA_PG_DSN not set")
    psycopg = pytest.importorskip("psycopg")
    from remora.governance.tenant_chain import PostgresTenantChain

    pg = PostgresTenantChain(dsn)
    with psycopg.connect(dsn) as conn:
        for table in ("tenant_chain_entry", "tenant_chain_head", "tenant_chain_idempotency"):
            conn.execute(f"DELETE FROM {table} WHERE tenant_id = 't'")  # noqa: S608 - fixed names
        conn.commit()
    return pg


def _v2(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_SIGNATURE_FORMAT", "v2")


def _v1_signature(entry_hash: str) -> str:
    return hmac.new(KEY.encode(), entry_hash.encode(), hashlib.sha256).hexdigest()


def _v2_signature(entry_hash: str) -> str:
    return "v2:" + hmac.new(KEY.encode(), preimage(SignatureDomain.AUDIT, entry_hash.encode()),
                            hashlib.sha256).hexdigest()


def test_v1_appends_are_unchanged(chain) -> None:
    entry = chain.append("t", {"event": "assessed"})
    assert entry.signature == _v1_signature(entry.entry_hash)
    assert chain.verify("t") == (True, [])


def test_the_first_v2_append_writes_the_transition_record(chain, monkeypatch) -> None:
    v1 = [chain.append("t", {"event": f"e{i}"}) for i in range(2)]
    _v2(monkeypatch)
    entry = chain.append("t", {"event": "executed"})
    entries = chain.entries("t")
    transition = entries[2]
    assert transition.payload == {
        "event": TRANSITION_EVENT, "from": "v1", "to": "v2",
        "previous_chain_head": v1[-1].entry_hash,
        "new_domain": "REMORA/AUDIT/v2",
    }
    assert transition.previous_hash == v1[-1].entry_hash
    assert transition.signature == _v2_signature(transition.entry_hash)
    assert entry.sequence_no == 3 and entry.signature == _v2_signature(entry.entry_hash)
    assert chain.verify("t") == (True, [])


def test_historical_entries_are_never_re_signed(chain, monkeypatch) -> None:
    before = [chain.append("t", {"event": f"e{i}"}) for i in range(2)]
    _v2(monkeypatch)
    chain.append("t", {"event": "executed"})
    assert list(chain.entries("t")[:2]) == before


def test_exactly_one_transition_per_chain(chain, monkeypatch) -> None:
    chain.append("t", {"event": "assessed"})
    _v2(monkeypatch)
    for i in range(3):
        chain.append("t", {"event": f"v2-{i}"})
    events = [e.payload.get("event") for e in chain.entries("t")]
    assert events.count(TRANSITION_EVENT) == 1


def test_a_new_chain_starts_v2_with_a_transition_from_none(chain, monkeypatch) -> None:
    _v2(monkeypatch)
    chain.append("t", {"event": "assessed"})
    first = chain.entries("t")[0]
    assert first.payload["event"] == TRANSITION_EVENT and first.payload["from"] == "none"
    assert first.payload["previous_chain_head"] == "0" * 64
    assert chain.verify("t") == (True, [])


def test_a_v2_chain_stays_v2_under_a_v1_process(chain, monkeypatch) -> None:
    """Never back: a v1 process appending to a v2 chain signs v2."""
    _v2(monkeypatch)
    chain.append("t", {"event": "assessed"})
    monkeypatch.delenv("REMORA_SIGNATURE_FORMAT")
    entry = chain.append("t", {"event": "executed"})
    assert entry.signature.startswith("v2:")
    assert chain.verify("t") == (True, [])


def test_append_once_writes_the_transition_in_the_same_unit(chain, monkeypatch) -> None:
    chain.append("t", {"event": "assessed"})
    _v2(monkeypatch)
    assert chain.append_once("t", "k1", {"event": "executed"}) is not None
    assert chain.append_once("t", "k1", {"event": "executed"}) is None
    events = [e.payload.get("event") for e in chain.entries("t")]
    assert events == ["assessed", TRANSITION_EVENT, "executed"]
    assert chain.verify("t") == (True, [])


def test_unsigned_chains_need_no_transition(chain, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_AUDIT_SIGNING_KEY")
    _v2(monkeypatch)
    chain.append("t", {"event": "assessed"})
    assert [e.payload["event"] for e in chain.entries("t")] == ["assessed"]


def test_the_statuses_name_the_signature_formats(chain, monkeypatch) -> None:
    chain.append("t", {"event": "assessed"})
    assert verification_statuses(chain.entries("t"), [])["signature_format"] == "v1"
    _v2(monkeypatch)
    chain.append("t", {"event": "executed"})
    assert verification_statuses(chain.entries("t"), [])["signature_format"] == "v1+v2"


# -- the verifier reads the era from the structure -----------------------------------

def _forge(chain, index: int, **changes):
    """Rewrite one stored entry's fields (tamper simulation)."""
    import dataclasses

    entries = list(chain.entries("t"))
    entries[index] = dataclasses.replace(entries[index], **changes)
    e = entries[index]
    if isinstance(chain, TenantAuditChain):
        chain._entries["t"] = entries
    elif isinstance(chain, SQLiteTenantChain):
        chain._conn().execute("UPDATE tenant_chain_entry SET signature=? WHERE tenant_id=? AND "
                              "sequence_no=?", (e.signature, "t", e.sequence_no))
    else:
        import psycopg

        with psycopg.connect(os.environ["REMORA_PG_DSN"]) as conn:
            conn.execute("UPDATE tenant_chain_entry SET signature=%s WHERE tenant_id=%s AND "
                         "sequence_no=%s", (e.signature, "t", e.sequence_no))
            conn.commit()


def test_a_v1_signature_after_the_transition_is_a_finding(chain, monkeypatch) -> None:
    chain.append("t", {"event": "assessed"})
    _v2(monkeypatch)
    entry = chain.append("t", {"event": "executed"})
    _forge(chain, entry.sequence_no, signature=_v1_signature(entry.entry_hash))
    ok, problems = chain.verify("t")
    assert not ok and f"audit_v1_after_transition_at:{entry.sequence_no}" in problems


def test_a_v2_signature_before_any_transition_is_a_finding(chain) -> None:
    entry = chain.append("t", {"event": "assessed"})
    _forge(chain, 0, signature=_v2_signature(entry.entry_hash))
    ok, problems = chain.verify("t")
    assert not ok and "audit_v2_before_transition_at:0" in problems


def test_the_era_checks_need_no_key(chain, monkeypatch) -> None:
    """Structure is checkable by anyone; signatures only with the key."""
    chain.append("t", {"event": "assessed"})
    _v2(monkeypatch)
    entry = chain.append("t", {"event": "executed"})
    _forge(chain, entry.sequence_no, signature=_v1_signature(entry.entry_hash))
    monkeypatch.delenv("REMORA_AUDIT_SIGNING_KEY")
    ok, problems = chain.verify("t")
    assert f"audit_v1_after_transition_at:{entry.sequence_no}" in problems


def test_a_v2_signature_does_not_verify_as_v1(chain, monkeypatch) -> None:
    """Strip the prefix: the bytes are a v2 MAC, not a v1 one."""
    chain.append("t", {"event": "assessed"})
    _v2(monkeypatch)
    entry = chain.append("t", {"event": "executed"})
    assert entry.signature[3:] != _v1_signature(entry.entry_hash)


def test_a_malformed_transition_is_a_finding() -> None:
    from remora.governance.audit_signing import signature_problems
    from remora.governance.tenant_chain import ChainEntry, compute_entry_hash

    payload = {"event": TRANSITION_EVENT, "from": "v1", "to": "v3",
               "previous_chain_head": "0" * 64, "new_domain": "REMORA/AUDIT/v2"}
    entry_hash = compute_entry_hash("0" * 64, payload, "t", 0, "2026-10-07T00:00:00+00:00")
    entry = ChainEntry("t", 0, "2026-10-07T00:00:00+00:00", payload, "0" * 64, entry_hash,
                       _v2_signature(entry_hash))
    assert "audit_transition_malformed_at:0" in signature_problems([entry], KEY.encode())


def test_a_second_transition_is_a_finding() -> None:
    from remora.governance.audit_signing import signature_problems, transition_payload
    from remora.governance.tenant_chain import ChainEntry, compute_entry_hash

    entries, previous = [], "0" * 64
    for i in range(2):
        payload = transition_payload(previous, first=(i == 0))
        ts = f"2026-10-07T00:00:0{i}+00:00"
        h = compute_entry_hash(previous, payload, "t", i, ts)
        entries.append(ChainEntry("t", i, ts, payload, previous, h, _v2_signature(h)))
        previous = h
    assert "audit_transition_repeated_at:1" in signature_problems(entries, KEY.encode())
