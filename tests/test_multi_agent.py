"""Tests for Multi-Agent Governance Protocol."""

from remora.governance.multi_agent import (
    AgentIdentity,
    AgentTrustRegistry,
    DelegationRequest,
    DelegationVerdict,
)


def _agent(aid: str, trust: str = "standard", max_risk: str = "medium") -> AgentIdentity:
    return AgentIdentity(agent_id=aid, agent_type="test", trust_tier=trust, max_risk_tier=max_risk)


def _req(from_a: AgentIdentity, to_a: AgentIdentity, risk: str = "low") -> DelegationRequest:
    return DelegationRequest(
        from_agent=from_a, to_agent=to_a,
        action="test_action", action_type="read", risk_tier=risk,
    )


class TestAgentTrustRegistry:
    def test_simple_delegation_allowed(self):
        reg = AgentTrustRegistry()
        a, b = _agent("a"), _agent("b")
        result = reg.evaluate_delegation(_req(a, b))
        assert result.verdict == DelegationVerdict.ALLOWED

    def test_self_delegation_blocked(self):
        reg = AgentTrustRegistry()
        a = _agent("a")
        result = reg.evaluate_delegation(_req(a, a))
        assert result.verdict == DelegationVerdict.BLOCKED
        assert "Self-delegation" in result.reason

    def test_explicit_block(self):
        reg = AgentTrustRegistry()
        reg.block_pair("a", "b")
        result = reg.evaluate_delegation(_req(_agent("a"), _agent("b")))
        assert result.verdict == DelegationVerdict.BLOCKED

    def test_risk_ceiling_enforced(self):
        reg = AgentTrustRegistry()
        a = _agent("a", max_risk="low")
        b = _agent("b", max_risk="low")
        result = reg.evaluate_delegation(_req(a, b, risk="critical"))
        assert result.verdict == DelegationVerdict.ESCALATED

    def test_delegation_laundering_detected(self):
        reg = AgentTrustRegistry()
        a = _agent("a", max_risk="low")
        b = _agent("b", max_risk="critical")
        result = reg.evaluate_delegation(_req(a, b, risk="high"))
        assert result.verdict == DelegationVerdict.ESCALATED
        assert "laundering" in result.reason.lower()

    def test_restricted_agent_blocked_for_write(self):
        reg = AgentTrustRegistry()
        a = _agent("a")
        b = _agent("b", trust="restricted")
        req = DelegationRequest(
            from_agent=a, to_agent=b,
            action="delete_data", action_type="delete", risk_tier="low",
        )
        result = reg.evaluate_delegation(req)
        assert result.verdict == DelegationVerdict.BLOCKED

    def test_chain_depth_limit(self):
        reg = AgentTrustRegistry(max_chain_depth=1)
        agents = [_agent(f"agent_{i}") for i in range(3)]
        # Build chain: 0->1 (depth 0 for agent_1, recorded)
        reg.evaluate_delegation(_req(agents[0], agents[1]))
        # 1->2: from_agent is agent_1 which has depth 1 in map, >= max 1
        result = reg.evaluate_delegation(_req(agents[1], agents[2]))
        assert result.verdict == DelegationVerdict.BLOCKED
        assert "depth" in result.reason.lower()

    def test_constrained_with_inherited_ceiling(self):
        reg = AgentTrustRegistry()
        a = _agent("a", max_risk="low")
        b = _agent("b", max_risk="high")
        result = reg.evaluate_delegation(_req(a, b, risk="low"))
        assert result.verdict in (DelegationVerdict.ALLOWED, DelegationVerdict.CONSTRAINED)
        assert result.effective_risk_ceiling == "low"

    def test_delegation_history_recorded(self):
        reg = AgentTrustRegistry()
        reg.evaluate_delegation(_req(_agent("a"), _agent("b")))
        assert len(reg.delegation_history) == 1

    def test_envelope_has_chain_hash(self):
        reg = AgentTrustRegistry()
        result = reg.evaluate_delegation(_req(_agent("a"), _agent("b")))
        assert result.chain_hash  # non-empty
        assert result.delegation_id  # non-empty
