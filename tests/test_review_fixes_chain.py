# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review findings: audit-chain signature stripping and sealed-copy fidelity."""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from remora.governance.audit_chain import GENESIS_HASH, RemoraAuditChain
from remora.governance.envelope import (
    AssessmentBlock,
    AuditBlock,
    DecisionEnvelope,
    EffectBlock,
    GateBlock,
    RequestBlock,
)
from remora.governance.tenant_chain import TenantAuditChain


def _env(rid: str = "r1", outcome: str = "refuse") -> DecisionEnvelope:
    return DecisionEnvelope(
        request=RequestBlock(
            request_id=rid, domain="d", risk_tier="low",
            proposed_action="x", action_type="read", target_environment="staging",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[], thermodynamic={}, evidence_quality={}, policy_triggers=[]
        ),
        gate=GateBlock(outcome=outcome, blocked_action=None, allowed_next_steps=[]),
        audit=AuditBlock(
            policy_version="v1", tenant_id="t1", actor_identity="a",
            policy_bundle_hash="b" * 64, tool_args_hash="c" * 64,
            timestamp_utc="2026-01-01T00:00:00+00:00",
        ),
        effect=EffectBlock(executed=True),
    )


def test_stripped_signatures_are_reported_on_keyed_chain() -> None:
    chain = RemoraAuditChain(secret_key=b"k" * 32)
    chain.append(_env("r1", "refuse"))
    chain.append(_env("r2", "accept"))
    assert chain.verify()[0]
    forged: list = []
    prev = GENESIS_HASH
    for e in chain._entries:
        h = RemoraAuditChain._compute_hash(prev, e.request_id, "accept", e.policy_version)
        forged.append(dataclasses.replace(
            e, gate_outcome="accept", previous_hash=prev, hash=h, signature=None))
        prev = h
    chain._entries[:] = forged
    ok, problems = chain.verify()
    assert not ok
    assert any("signature_missing" in p for p in problems)


def test_unkeyed_chain_without_signatures_still_verifies() -> None:
    chain = RemoraAuditChain()
    chain.append(_env())
    assert chain.verify() == (True, [])


def test_tenant_chain_stripped_signature_is_reported(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", "secret")
    tc = TenantAuditChain(now_fn=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    tc.append("t1", {"a": 1})
    assert tc.verify("t1")[0]
    tc._entries["t1"][0] = dataclasses.replace(tc._entries["t1"][0], signature="")
    ok, problems = tc.verify("t1")
    assert not ok
    assert any("signature_missing" in p for p in problems)


def test_append_sealed_copy_preserves_envelope_fields() -> None:
    sealed = RemoraAuditChain().append(_env())
    assert sealed.effect.executed is True
    a = sealed.audit
    assert a.tenant_id == "t1" and a.actor_identity == "a"
    assert a.policy_bundle_hash == "b" * 64 and a.tool_args_hash == "c" * 64
    assert a.timestamp_utc == "2026-01-01T00:00:00+00:00"
    assert a.hash and a.previous_hash == GENESIS_HASH
