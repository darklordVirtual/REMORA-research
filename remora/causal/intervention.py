"""PolicyIntervention — do(variable=value) for policy concepts.

Only actionable variables may be intervened upon.  Non-actionable signals
(trust_score, entropy, risk_tier, oracle disagreement) reflect system state
and cannot be directly fixed by an operator.  Attempting to intervene on
a non-actionable variable raises ValueError.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from remora.causal.schema import CausalDecisionModel


@dataclass(frozen=True)
class PolicyIntervention:
    """A single do(variable=value) intervention on an actionable policy concept.

    In Pearl's do-calculus notation: do(variable=value) cuts incoming edges
    to the variable and forces its value.  Here, "forcing" means applying the
    concept's signal_mapping to the PolicyObservation before policy evaluation.

    This is a policy-modelled counterfactual: it tells you what the policy
    engine would decide if the operational conditions described by the concept
    were in place.  It does NOT predict what would happen in the real world.
    """
    variable: str
    value: Any

    def __str__(self) -> str:
        return f"do({self.variable}={self.value!r})"


def validate_intervention(
    intervention: PolicyIntervention,
    model: CausalDecisionModel,
) -> None:
    """Raise ValueError if the intervention targets an undefined or non-actionable variable.

    Non-actionable variables include derived signals (trust_score, entropy,
    risk_tier, oracle disagreement, phase) that reflect computed system state
    rather than controllable operational conditions.  These cannot be
    "fixed" by an operator and must not appear in actionable requirements.
    """
    var = model.get_variable(intervention.variable)
    if var is None:
        available = [v.name for v in model.variables]
        raise ValueError(
            f"Variable '{intervention.variable}' is not defined in model "
            f"'{model.model_id}'. Available variables: {available}"
        )
    if not var.actionable:
        raise ValueError(
            f"Variable '{intervention.variable}' (type={var.type.value}, "
            f"intervenable={var.intervenable}, actionable={var.actionable}) "
            f"is not actionable and cannot be intervened upon. "
            f"Non-actionable signals such as trust_score, entropy, risk_tier, "
            f"and oracle disagreement reflect computed system state — they "
            f"cannot be directly set by an operator."
        )
