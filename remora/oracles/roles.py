# Author: Stian Skogbrott
# License: Apache-2.0
"""
Role-differentiated oracle wrappers for REMORA.

Epistemically distinct oracle roles prevent the echo-chamber failure mode
observed when identical agents with identical prompts produce correlated
outputs. Each role instructs the underlying model to approach the question
from a fundamentally different epistemic angle, ensuring genuine diversity
in the reasoning process rather than surface-level model diversity.

Theoretical basis
-----------------
Multi-agent debate literature (Du et al., 2023) shows that role separation
produces higher factual accuracy than same-role agent populations. REMORA
extends this finding by integrating role separation with Lyapunov-controlled
consensus: roles are not debating toward a fixed answer, but contributing
independent signals to an entropy-minimising aggregation function.

Role taxonomy
-------------
    SourceOracle      — retrieves and cites primary evidence
    SkepticOracle     — searches for counter-evidence and weaknesses
    DomainOracle      — applies domain-specific technical reasoning
    VerifierOracle    — tests the claim against retrieved sources only
    AdversarialOracle — attempts to falsify the emerging consensus
    JudgeOracle       — synthesises all signals into a final verdict

Each wrapper preserves the underlying Oracle ABC interface so roles are
transparent to REMORA's correlation matrix and Lyapunov controller.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from remora.core import Oracle


class OracleRole(Enum):
    """Epistemic role assigned to an oracle node."""
    SOURCE     = "source"
    SKEPTIC    = "skeptic"
    DOMAIN     = "domain"
    VERIFIER   = "verifier"
    ADVERSARIAL = "adversarial"
    JUDGE      = "judge"


# Role-specific system instructions injected before the main question.
# Each instruction is designed to push the model into a genuinely different
# epistemic posture, not just surface phrasing variation.
_ROLE_INSTRUCTIONS: dict[OracleRole, str] = {

    OracleRole.SOURCE: (
        "You are a EVIDENCE RETRIEVAL SPECIALIST. Your only job is to identify "
        "what primary evidence supports or refutes the claim. "
        "Cite specific facts, statistics, named sources, or mechanisms. "
        "Do NOT speculate beyond what the evidence directly shows. "
        "If you cannot find clear supporting evidence, say so explicitly. "
        "Return your judgment based on the evidence you can cite."
    ),

    OracleRole.SKEPTIC: (
        "You are a CRITICAL SKEPTIC. Your job is to challenge the claim. "
        "Actively search for exceptions, counter-examples, conditions under which "
        "the claim fails, known errors in common belief, or ways the question "
        "may be misleading. Do NOT accept the claim at face value. "
        "If after critical analysis the claim still holds, you may confirm it — "
        "but only after genuinely attempting to falsify it."
    ),

    OracleRole.DOMAIN: (
        "You are a DOMAIN EXPERT with deep technical knowledge. "
        "Apply your specialised knowledge to assess the technical accuracy, "
        "nuance, and caveats of the claim. Consider edge cases, domain-specific "
        "definitions, and whether the claim holds across all relevant contexts. "
        "Flag any technically imprecise formulations even if the core claim is correct."
    ),

    OracleRole.VERIFIER: (
        "You are an INDEPENDENT VERIFIER. You may ONLY use facts that are "
        "universally established and directly relevant. You MUST NOT rely on "
        "training-data associations or surface patterns. "
        "For each element of the claim, explicitly check: "
        "(1) Is this verifiable from primary sources? "
        "(2) Is this definition consistent with authoritative usage? "
        "(3) Is the logical structure of the claim sound? "
        "If any element fails verification, the overall claim should not be confirmed."
    ),

    OracleRole.ADVERSARIAL: (
        "You are an ADVERSARIAL EXAMINER. Your explicit goal is to find any "
        "reason why the claim might be wrong, misleading, incomplete, or "
        "context-dependent. Assume the claim is probably incorrect and look "
        "for evidence to support that assumption. Consider: "
        "ambiguous definitions, historical counterexamples, regional variations, "
        "recent updates that contradict established knowledge, or ways the claim "
        "could be true in one sense but false in another. "
        "Only confirm the claim if you genuinely cannot find a serious weakness."
    ),

    OracleRole.JUDGE: (
        "You are a FINAL ARBITRATOR. You have seen multiple perspectives on this "
        "question. Your job is to weigh all available evidence and reasoning, "
        "identify the most defensible answer, and quantify your confidence honestly. "
        "Do NOT anchor on the most common answer if the evidence is weak. "
        "A confident 'null' (insufficient evidence) is more valuable than a "
        "confident wrong answer. Provide your most calibrated judgment."
    ),
}


@dataclass(frozen=True)
class RoleOracleConfig:
    """Configuration for a role-differentiated oracle."""
    role: OracleRole
    base_oracle: Oracle
    anti_convergence_context: Optional[str] = None


class RoleOracle(Oracle):
    """
    Wraps any Oracle with an epistemically distinct role instruction.

    The role system prompt is prepended to every query, steering the
    underlying model toward a specific reasoning approach without changing
    the model architecture or weights.

    Parameters
    ----------
    base_oracle : Oracle
        The underlying oracle to wrap (Groq, OpenRouter, RAG, etc.).
    role : OracleRole
        The epistemic role to assign.
    anti_convergence_context : str or None
        If provided, a summary of claims already made by other oracles in
        this round, instructing this oracle to find non-overlapping angles.
    """

    def __init__(
        self,
        base_oracle: Oracle,
        role: OracleRole,
        anti_convergence_context: Optional[str] = None,
    ) -> None:
        self._base = base_oracle
        self._role = role
        self._anti_ctx = anti_convergence_context

    @property
    def name(self) -> str:
        return f"{self._base.name}[{self._role.value}]"

    @property
    def role(self) -> OracleRole:
        return self._role

    def _call(self, prompt: str) -> tuple[str, float, float]:
        """Inject role instruction before the main prompt."""
        role_prefix = _ROLE_INSTRUCTIONS[self._role]

        anti_block = ""
        if self._anti_ctx:
            anti_block = (
                f"\n\nOther oracles in this round have already noted:\n"
                f"{self._anti_ctx}\n"
                f"You MUST approach the question from a DIFFERENT angle than "
                f"the notes above. Do not simply restate what has been said."
            )

        full_prompt = f"[ROLE: {self._role.value.upper()}]\n{role_prefix}{anti_block}\n\n{prompt}"
        return self._base._call(full_prompt)


def make_role_swarm(
    base_oracles: list[Oracle],
    roles: Optional[list[OracleRole]] = None,
) -> list[RoleOracle]:
    """
    Build a role-differentiated oracle swarm from a list of base oracles.

    If fewer roles than oracles are provided, roles are cycled.
    If more roles than oracles are provided, oracles are cycled.

    Default role assignment for a three-oracle swarm:
        Oracle 0 → SOURCE
        Oracle 1 → SKEPTIC
        Oracle 2 → DOMAIN

    For a six-oracle swarm:
        Oracle 0 → SOURCE
        Oracle 1 → SKEPTIC
        Oracle 2 → DOMAIN
        Oracle 3 → VERIFIER
        Oracle 4 → ADVERSARIAL
        Oracle 5 → JUDGE

    Parameters
    ----------
    base_oracles : list[Oracle]
        Underlying oracle instances.
    roles : list[OracleRole] or None
        Roles to assign. If None, uses the default ordered taxonomy.

    Returns
    -------
    list[RoleOracle]
        Role-wrapped oracles ready for use in a Remora engine.
    """
    if roles is None:
        roles = list(OracleRole)  # SOURCE, SKEPTIC, DOMAIN, VERIFIER, ADVERSARIAL, JUDGE

    return [
        RoleOracle(
            base_oracle=base_oracles[i % len(base_oracles)],
            role=roles[i % len(roles)],
        )
        for i in range(max(len(base_oracles), len(roles)))
    ]
