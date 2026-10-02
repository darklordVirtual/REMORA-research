# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Round-2 governance review findings: default-deny regressions.

Each test pins a case that previously failed open.
"""
from __future__ import annotations

import sqlite3

import pytest

from remora.governance.context_flow import (
    default_context_flow_registry,
)
from remora.governance.degradation import g4_refuses
from remora.governance.memory_layers import (
    MemoryLayerUpdate,
    default_memory_policy_registry,
)
from remora.governance.multi_agent import (
    AgentIdentity,
    AgentTrustRegistry,
    DelegationRequest,
    DelegationVerdict,
)
from remora.governance.nested_governance import (
    LayerUpdateRequest,
    default_nested_governance_model,
)
from remora.governance.tenant_chain import SQLiteTenantChain, TenantAuditChain
from remora.policy import decision_engine as _engine


# --- 1. G4 is an allowlist ---------------------------------------------------

@pytest.mark.parametrize(
    "action_type",
    ["wipe", "disable_security", "bulk_delete", "shell_execute",
     "execute_transfer", "unknown_tool", None, "", "  "],
)
def test_g4_refuses_unknown_or_missing_action_types_in_staging(action_type):
    assert g4_refuses(action_type, "staging")


@pytest.mark.parametrize(
    "action_type",
    sorted(_engine._READ_ONLY_TYPES | _engine._NON_ACTUATING_TYPES),
)
def test_g4_allows_engine_read_only_and_non_actuating_vocabulary(action_type):
    assert not g4_refuses(action_type, "staging")
    assert g4_refuses(action_type, "prod")


# --- 2. non-human actors cannot write agent-forbidden flows -------------------

@pytest.mark.parametrize("actor", ["claude-subagent", "bot", "Planner", " agent "])
def test_nested_governance_denies_unlisted_actor_on_agent_forbidden_layer(actor):
    model = default_nested_governance_model()
    layer = next(x for x in model.layers if not x.writable_by_agent)
    decision = model.evaluate_update(
        LayerUpdateRequest(layer_name=layer.name, actor=actor, update_type="x",
                           approved=True, append_only=True,
                           metadata={"audit_trace_id": "t"})
    )
    assert decision.action != "ACCEPT"


@pytest.mark.parametrize("actor", ["claude-subagent", "bot", "Planner"])
def test_context_flow_denies_unlisted_actor_on_agent_forbidden_flow(actor):
    reg = default_context_flow_registry()
    flow = next(f for f in reg.flows if not f.writable_by_agent)
    assert not flow.permits_actor(actor)


def test_context_flow_still_permits_human_and_service():
    reg = default_context_flow_registry()
    flow = next(f for f in reg.flows if not f.writable_by_agent)
    assert flow.permits_actor("human") and flow.permits_actor("service")


def test_memory_layers_unlisted_actor_denied_by_approved_writers():
    reg = default_memory_policy_registry()
    policy = next(p for p in reg.policies if not p.writable_by_agent)
    for actor in ("claude-subagent", "bot"):
        decision = reg.evaluate_update(
            MemoryLayerUpdate(layer=policy.layer, actor=actor, approved_by_human=True,
                              audit_trace_id="t")
        )
        assert decision.action != "ACCEPT"
        assert "writer_not_in_approved_set" in decision.reasons


# --- 3. multi-agent identity from registry, unknown = most restrictive ----------

def _req(frm, to, **kw):
    base = dict(action="a", action_type="read", risk_tier="low")
    base.update(kw)
    return DelegationRequest(from_agent=frm, to_agent=to, **base)


def test_forged_request_identity_is_replaced_by_registered_identity():
    reg = AgentTrustRegistry()
    reg.register(AgentIdentity("a", "x", "standard", "low"))
    reg.register(AgentIdentity("b", "x", "restricted", "low"))
    forged_b = AgentIdentity("b", "x", "trusted", "critical")
    env = reg.evaluate_delegation(
        _req(AgentIdentity("a", "x", "trusted", "critical"), forged_b,
             action_type="write", risk_tier="high")
    )
    assert env.verdict in (DelegationVerdict.BLOCKED, DelegationVerdict.ESCALATED)


def test_unknown_ceiling_is_most_restrictive():
    reg = AgentTrustRegistry()
    a = AgentIdentity("a", "x", "standard", "hgh")
    b = AgentIdentity("b", "x", "standard", "hgh")
    env = reg.evaluate_delegation(_req(a, b, risk_tier="critical"))
    assert env.verdict != DelegationVerdict.ALLOWED
    env = reg.evaluate_delegation(_req(a, b, risk_tier="low"))
    assert env.verdict != DelegationVerdict.ALLOWED


@pytest.mark.parametrize(
    "action_type",
    ["production_write", "shell_write", "permission_change", "shell_execute", "Write "],
)
def test_restricted_agent_blocked_for_all_mutating_types(action_type):
    reg = AgentTrustRegistry()
    a = AgentIdentity("a", "x", "trusted", "high")
    b = AgentIdentity("b", "x", "restricted", "high")
    env = reg.evaluate_delegation(_req(a, b, action_type=action_type, risk_tier="low"))
    assert env.verdict == DelegationVerdict.BLOCKED


def test_unknown_trust_tier_treated_as_restricted():
    reg = AgentTrustRegistry()
    a = AgentIdentity("a", "x", "trusted", "high")
    b = AgentIdentity("b", "x", "trustd", "high")
    env = reg.evaluate_delegation(_req(a, b, action_type="write", risk_tier="low"))
    assert env.verdict == DelegationVerdict.BLOCKED


# --- 4. tail truncation -------------------------------------------------------

def _fill(chain, n=5):
    return [chain.append("t", {"i": i}) for i in range(n)]


def test_sqlite_expected_head_detects_tail_truncation(tmp_path):
    db = str(tmp_path / "c.db")
    chain = SQLiteTenantChain(db)
    entries = _fill(chain)
    head = (entries[-1].sequence_no, entries[-1].entry_hash)
    assert chain.verify("t", expected_head=head) == (True, [])
    con = sqlite3.connect(db)
    con.execute("DELETE FROM tenant_chain_entry WHERE sequence_no >= 3")
    con.commit()
    con.close()
    assert chain.verify("t")[0] is True  # known limit without an anchor
    ok, problems = chain.verify("t", expected_head=head)
    assert not ok and any(p.startswith("head_mismatch") for p in problems)


def test_memory_chain_expected_head_detects_truncation():
    chain = TenantAuditChain()
    entries = _fill(chain)
    head = (entries[-1].sequence_no, entries[-1].entry_hash)
    assert chain.verify("t", expected_head=head) == (True, [])
    del chain._entries["t"][3:]
    ok, problems = chain.verify("t", expected_head=head)
    assert not ok and any(p.startswith("head_mismatch") for p in problems)


def test_expected_head_on_empty_chain_is_a_mismatch():
    ok, problems = TenantAuditChain().verify("t", expected_head=(0, "x" * 64))
    assert not ok and problems


def test_stored_head_row_is_compared_to_last_entry():
    from remora.governance import tenant_chain as tc

    base = TenantAuditChain()
    entries = _fill(base)

    class _PgLike:
        def entries(self, tenant_id):
            return tuple(entries[:3])

        def stored_head(self, tenant_id):
            return (entries[-1].sequence_no, entries[-1].entry_hash)

    ok, problems = tc._verify_generic(_PgLike(), "t")
    assert not ok and any(p.startswith("stored_head_mismatch") for p in problems)
