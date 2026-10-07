# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-007: an audit verification says which checks it ran.

Before: TenantAuditChain.verify compared signatures only when the verifying
process held REMORA_AUDIT_SIGNING_KEY. Probe at b9ade2b: a history re-chained
with its signatures stripped verified as (True, []) without the key, and
GET /v1/execution/audit/verify reported only ``valid: true``. The
control-plane GET /v1/audit/chain/verify checks linkage only and said so
nowhere in its answer.

After: both answers carry the scope of the check. ``hash_chain_status`` and
``signature_status`` are independent, and ``valid`` can no longer be read as
"intact and authentic" by a client that ignores what was not checked.
"""
from __future__ import annotations

import dataclasses

import pytest

from remora.governance.tenant_chain import (
    SIGNATURE_CHECKED,
    SIGNATURE_NOT_CHECKED_NO_KEY,
    SIGNATURE_UNSIGNED,
    TenantAuditChain,
    compute_entry_hash,
    verification_statuses,
)


def _chain(n: int = 3) -> TenantAuditChain:
    chain = TenantAuditChain()
    for i in range(n):
        chain.append("t", {"event": "assessed", "i": i})
    return chain


def _rechain_without_signatures(chain: TenantAuditChain) -> None:
    """What a writer without the key can do: rewrite and re-link the history."""
    entries = list(chain.entries("t"))
    previous = entries[0].previous_hash
    rebuilt = []
    for e in entries:
        payload = dict(e.payload, tampered=True)
        h = compute_entry_hash(previous, payload, e.tenant_id, e.sequence_no, e.timestamp)
        rebuilt.append(dataclasses.replace(e, payload=payload, previous_hash=previous,
                                           entry_hash=h, signature=""))
        previous = h
    chain._entries["t"] = rebuilt


def test_without_a_key_a_rechained_history_is_not_reported_as_signed_and_checked(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", "audit-key")
    chain = _chain()
    _rechain_without_signatures(chain)
    monkeypatch.delenv("REMORA_AUDIT_SIGNING_KEY")
    ok, problems = chain.verify("t")
    status = verification_statuses(chain.entries("t"), problems)
    assert ok is True  # the hash links are intact; that is all this verifier can see
    assert status == {"hash_chain_status": "INTACT", "signature_status": SIGNATURE_UNSIGNED,
                      "signature_format": "none"}


def test_with_the_key_the_same_history_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", "audit-key")
    chain = _chain()
    _rechain_without_signatures(chain)
    ok, problems = chain.verify("t")
    status = verification_statuses(chain.entries("t"), problems)
    assert ok is False and any(p.startswith("signature_missing_at") for p in problems)
    assert status == {"hash_chain_status": "INTACT", "signature_status": SIGNATURE_CHECKED,
                      "signature_format": "none"}


def test_signed_entries_verified_without_the_key_are_not_checked(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", "audit-key")
    chain = _chain()
    monkeypatch.delenv("REMORA_AUDIT_SIGNING_KEY")
    ok, problems = chain.verify("t")
    assert verification_statuses(chain.entries("t"), problems)["signature_status"] == (
        SIGNATURE_NOT_CHECKED_NO_KEY)


def test_a_broken_hash_link_is_broken_whatever_the_signature_status(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_AUDIT_SIGNING_KEY", raising=False)
    chain = _chain()
    entries = list(chain.entries("t"))
    entries[1] = dataclasses.replace(entries[1], payload={"event": "edited"})
    chain._entries["t"] = entries
    ok, problems = chain.verify("t")
    assert ok is False
    assert verification_statuses(chain.entries("t"), problems)["hash_chain_status"] == "BROKEN"


@pytest.fixture()
def exec_client(monkeypatch):
    from fastapi.testclient import TestClient

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("t", "operator"))
    monkeypatch.setattr(exec_mod, "_CHAIN", _chain())
    return TestClient(api_mod.app)


def test_the_execution_endpoint_reports_both_statuses(exec_client, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_AUDIT_SIGNING_KEY", raising=False)
    body = exec_client.get("/v1/execution/audit/verify").json()
    assert body["valid"] is True
    assert body["hash_chain_status"] == "INTACT"
    assert body["signature_status"] == SIGNATURE_UNSIGNED


def test_the_control_plane_endpoint_states_its_linkage_only_scope(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import servers.api as api_mod

    class _Store:
        def list_audit_records_for_tenant(self, tenant_id):
            return []

    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("t", "operator"))
    monkeypatch.setattr(api_mod, "_CONTROL_PLANE_STORE", _Store())
    body = TestClient(api_mod.app).get("/v1/audit/chain/verify").json()
    assert body["verification_scope"] == "linkage_only"
    assert body["signature_status"] == "NOT_CHECKED"
