"""Causal schema for REMORA policy explanations.

All types are bounded to the policy model (decision_scope="policy_only").
Nothing here establishes real-world causal effect.

Reference: Bjøru (2026), §3 — externally causal XAI uses a concept-based
explanation vocabulary; internally causal XAI focuses on direct feature effects.
REMORA's causal module is externally causal: it operates over high-level
operational concepts, not raw PolicyObservation fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VariableType(str, Enum):
    OBSERVED = "observed"    # measured from the environment; cannot be set
    CONCEPT = "concept"      # high-level operational concept; may be actionable
    DECISION = "decision"    # the policy gate output (ACCEPT/VERIFY/ABSTAIN/ESCALATE)
    OUTCOME = "outcome"      # downstream of the decision; cannot be set


class VariableProvenance(str, Enum):
    POLICY = "policy"        # asserted by the policy engine
    TOOL = "tool"            # declared by the calling tool
    EVIDENCE = "evidence"    # from the evidence pipeline
    HUMAN = "human"          # attested by a human operator
    TELEMETRY = "telemetry"  # from runtime telemetry
    MODEL = "model"          # inferred by a classification model


@dataclass
class CausalVariable:
    """One node in the causal decision model.

    Parameters
    ----------
    name:
        Stable identifier used in signal_mapping keys and intervention targets.
    label:
        Human-readable label for display in explanations.
    type:
        Ontological type (observed / concept / decision / outcome).
    intervenable:
        Whether the variable can in principle be set by any means.
    actionable:
        Whether an operator can set this variable through a concrete operational
        step. Must be True before a PolicyIntervention is allowed.
        Non-actionable signals (trust_score, entropy, risk_tier, oracle
        disagreement) reflect system state and cannot be directly set.
    provenance:
        How this variable is populated.
    signal_mapping:
        Maps PolicyObservation field names to override values when this concept
        is intervened upon (do(concept=True)).  Empty for non-actionable variables.
    """
    name: str
    label: str
    type: VariableType
    intervenable: bool
    actionable: bool
    provenance: VariableProvenance
    signal_mapping: dict[str, Any] = field(default_factory=dict)


@dataclass
class CausalEdge:
    """Directed edge in the causal graph."""
    source: str
    target: str
    relation: str   # e.g. "enables", "constrains", "context", "overrides"


@dataclass
class CausalDecisionModel:
    """Partially specified causal model for a policy decision domain.

    Following Bjøru (2026) §5, this is a partially specified causal model:
    full SCM specification is not required.  The model captures the concepts
    and their approximate policy-level consequences, not complete real-world
    causal structure.

    Parameters
    ----------
    model_id:   Stable identifier (e.g. "network_change_management_v1").
    version:    Semantic version string.
    domain:     Domain label.
    variables:  All causal variables (observed, concept, decision, outcome).
    edges:      Directed edges in the causal graph.
    assumptions:
        Explicit assumptions bounding this model's validity.  Must be included
        in every generated CausalExplanation via the assumptions field.
    """
    model_id: str
    version: str
    domain: str
    variables: list[CausalVariable]
    edges: list[CausalEdge]
    assumptions: list[str]

    def get_variable(self, name: str) -> CausalVariable | None:
        return next((v for v in self.variables if v.name == name), None)

    def actionable_variables(self) -> list[CausalVariable]:
        return [v for v in self.variables if v.actionable]
