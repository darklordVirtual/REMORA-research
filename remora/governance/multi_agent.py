"""Multi-Agent Governance Protocol for REMORA.

When Agent A delegates a tool call or sub-task to Agent B, REMORA must:
1. Gate the delegation itself (is A allowed to delegate to B?)
2. Track cross-agent decision provenance (B's envelope references A's)
3. Enforce transitive policy constraints (B inherits A's risk ceiling)
4. Detect delegation laundering (A escalates to B to bypass its own restrictions)

This module implements the DelegationEnvelope and AgentTrustRegistry.

Threat model
------------
- Agent A may delegate to Agent B to circumvent A's policy restrictions
- Agent B may have broader permissions than intended when acting on A's behalf
- Long delegation chains obscure accountability
- Circular delegations create infinite loops

All of these are detected and blocked.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class DelegationVerdict(str, Enum):
    """Outcome of a delegation governance check."""

    ALLOWED = "ALLOWED"
    CONSTRAINED = "CONSTRAINED"  # allowed but with tightened policy
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True)
class AgentIdentity:
    """Identity of an agent in the governance graph."""

    agent_id: str
    agent_type: str  # e.g. "openai_assistant", "langchain", "crewai", "mcp"
    trust_tier: str = "standard"  # "trusted", "standard", "restricted"
    max_risk_tier: str = "medium"  # max risk tier this agent can autonomously handle
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DelegationRequest:
    """A request from one agent to delegate work to another."""

    from_agent: AgentIdentity
    to_agent: AgentIdentity
    action: str
    action_type: str
    risk_tier: str
    context: dict[str, Any] = field(default_factory=dict)
    parent_envelope_hash: str | None = None  # hash of the originating DecisionEnvelope


@dataclass(frozen=True)
class DelegationEnvelope:
    """Governance record for an agent-to-agent delegation.

    References the parent DecisionEnvelope and adds delegation-specific
    metadata for cross-agent audit.
    """

    delegation_id: str
    request: DelegationRequest
    verdict: DelegationVerdict
    effective_risk_ceiling: str  # the tighter of from/to agent ceilings
    policy_constraints_applied: list[str] = field(default_factory=list)
    chain_depth: int = 0  # how many delegation hops deep
    chain_hash: str = ""  # Merkle hash of the delegation chain
    timestamp: float = field(default_factory=time.time)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Risk tier ordering
# ---------------------------------------------------------------------------

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _risk_level(tier: str) -> int:
    return _RISK_ORDER.get(tier.lower(), 99)


def _tighter_risk(a: str, b: str) -> str:
    """Return the more restrictive of two risk tiers."""
    return a if _risk_level(a) <= _risk_level(b) else b


# ---------------------------------------------------------------------------
# Agent Trust Registry
# ---------------------------------------------------------------------------

class AgentTrustRegistry:
    """Registry of agent identities and their trust relationships.

    Tracks which agents can delegate to which, enforces delegation depth
    limits, and detects delegation laundering patterns.
    """

    def __init__(
        self,
        *,
        max_chain_depth: int = 5,
        allow_self_delegation: bool = False,
    ) -> None:
        self._agents: dict[str, AgentIdentity] = {}
        self._delegation_history: list[DelegationEnvelope] = []
        self._blocked_pairs: set[tuple[str, str]] = set()
        self._max_chain_depth = max_chain_depth
        self._allow_self_delegation = allow_self_delegation

    def register(self, agent: AgentIdentity) -> None:
        """Register an agent identity."""
        self._agents[agent.agent_id] = agent

    def block_pair(self, from_id: str, to_id: str) -> None:
        """Explicitly block delegation between two agents."""
        self._blocked_pairs.add((from_id, to_id))

    def get_agent(self, agent_id: str) -> AgentIdentity | None:
        return self._agents.get(agent_id)

    @property
    def delegation_history(self) -> list[DelegationEnvelope]:
        return list(self._delegation_history)

    def _chain_depth(self, from_id: str, to_id: str) -> int:
        """Count active delegation depth ending at to_id via from_id."""
        # Walk backward through delegation history to find the longest chain
        # ending at from_id (which becomes to_id's depth + 1)
        depth_map: dict[str, int] = {}
        for env in self._delegation_history:
            tid = env.request.to_agent.agent_id
            depth_map[tid] = env.chain_depth + 1
        return depth_map.get(from_id, 0)

    def _detect_circular(self, from_id: str, to_id: str) -> bool:
        """Detect circular delegation chains."""
        visited = {from_id}
        frontier = [to_id]
        for env in reversed(self._delegation_history[-100:]):
            if env.request.from_agent.agent_id in frontier:
                if env.request.to_agent.agent_id in visited:
                    return True
                visited.add(env.request.from_agent.agent_id)
                frontier.append(env.request.to_agent.agent_id)
        return False

    def _detect_laundering(self, request: DelegationRequest) -> bool:
        """Detect delegation laundering: A delegates to B to bypass A's risk ceiling.

        Pattern: A's max_risk_tier < action risk, but B's max_risk_tier >= action risk.
        """
        action_risk = _risk_level(request.risk_tier)
        from_ceiling = _risk_level(request.from_agent.max_risk_tier)
        to_ceiling = _risk_level(request.to_agent.max_risk_tier)
        return action_risk > from_ceiling and action_risk <= to_ceiling

    def _chain_hash(self, request: DelegationRequest, depth: int) -> str:
        """Compute Merkle hash of delegation chain."""
        content = json.dumps({
            "from": request.from_agent.agent_id,
            "to": request.to_agent.agent_id,
            "action": request.action,
            "depth": depth,
            "parent": request.parent_envelope_hash or "",
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()

    def evaluate_delegation(self, request: DelegationRequest) -> DelegationEnvelope:
        """Evaluate whether a delegation should be allowed.

        Returns a DelegationEnvelope with the verdict and constraints.
        """
        constraints: list[str] = []

        # 1. Self-delegation check
        if request.from_agent.agent_id == request.to_agent.agent_id and not self._allow_self_delegation:
            return self._envelope(request, DelegationVerdict.BLOCKED, [], 0, "Self-delegation not allowed")

        # 2. Explicit block check
        if (request.from_agent.agent_id, request.to_agent.agent_id) in self._blocked_pairs:
            return self._envelope(request, DelegationVerdict.BLOCKED, [], 0, "Delegation pair explicitly blocked")

        # 3. Chain depth check
        depth = self._chain_depth(request.from_agent.agent_id, request.to_agent.agent_id)
        if depth >= self._max_chain_depth:
            return self._envelope(request, DelegationVerdict.BLOCKED, [], depth, f"Chain depth {depth} exceeds max {self._max_chain_depth}")

        # 4. Circular delegation check
        if self._detect_circular(request.from_agent.agent_id, request.to_agent.agent_id):
            return self._envelope(request, DelegationVerdict.BLOCKED, [], depth, "Circular delegation detected")

        # 5. Delegation laundering check
        if self._detect_laundering(request):
            return self._envelope(
                request, DelegationVerdict.ESCALATED, ["laundering_detected"], depth,
                f"Delegation laundering: {request.from_agent.agent_id} (max={request.from_agent.max_risk_tier}) "
                f"delegates {request.risk_tier}-risk action to {request.to_agent.agent_id} (max={request.to_agent.max_risk_tier})",
            )

        # 6. Risk ceiling enforcement
        effective_ceiling = _tighter_risk(request.from_agent.max_risk_tier, request.to_agent.max_risk_tier)
        action_risk = _risk_level(request.risk_tier)

        if action_risk > _risk_level(effective_ceiling):
            return self._envelope(
                request, DelegationVerdict.ESCALATED, [f"risk_exceeds_ceiling:{effective_ceiling}"], depth,
                f"Action risk {request.risk_tier} exceeds effective ceiling {effective_ceiling}",
            )

        # 7. Trust tier constraints
        if request.to_agent.trust_tier == "restricted":
            constraints.append("restricted_agent:read_only")
            if request.action_type in ("write", "delete", "execute"):
                return self._envelope(request, DelegationVerdict.BLOCKED, constraints, depth, "Restricted agent cannot perform write/delete/execute")

        # 8. Constrained pass-through
        if effective_ceiling != request.to_agent.max_risk_tier:
            constraints.append(f"inherited_ceiling:{effective_ceiling}")

        verdict = DelegationVerdict.CONSTRAINED if constraints else DelegationVerdict.ALLOWED
        envelope = self._envelope(request, verdict, constraints, depth, "Delegation approved" + (f" with constraints: {constraints}" if constraints else ""))
        self._delegation_history.append(envelope)
        return envelope

    def _envelope(
        self,
        request: DelegationRequest,
        verdict: DelegationVerdict,
        constraints: list[str],
        depth: int,
        reason: str,
    ) -> DelegationEnvelope:
        effective_ceiling = _tighter_risk(request.from_agent.max_risk_tier, request.to_agent.max_risk_tier)
        delegation_id = hashlib.sha256(
            f"{request.from_agent.agent_id}:{request.to_agent.agent_id}:{time.time()}".encode()
        ).hexdigest()[:16]
        return DelegationEnvelope(
            delegation_id=delegation_id,
            request=request,
            verdict=verdict,
            effective_risk_ceiling=effective_ceiling,
            policy_constraints_applied=constraints,
            chain_depth=depth,
            chain_hash=self._chain_hash(request, depth),
            reason=reason,
        )
