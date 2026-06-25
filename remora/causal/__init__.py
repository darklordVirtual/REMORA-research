"""REMORA causal explanation module.

Provides policy-only counterfactual analysis: explains why a governance
decision was made and what actionable operational changes would produce a
different policy outcome.

Scope: decision_scope="policy_only"
This module does NOT establish real-world causal effects or safety guarantees.

Quick start
-----------
>>> from remora.causal import generate_explanation, PolicyIntervention
>>> from remora.causal.domains import load_domain
>>> from remora.policy.decision_engine import RemoraDecisionEngine
>>> from remora.policy.observation import PolicyObservation
>>>
>>> engine = RemoraDecisionEngine()
>>> model = load_domain("network_change_management_v1")
>>> obs = PolicyObservation(
...     question="Deploy BGP route change to core router",
...     risk_tier="critical",
...     action_type="network_change",
...     target_environment="prod",
...     rollback_available=False,
...     argument_tainted=True,
... )
>>> explanation = generate_explanation(obs, engine, model, interventions=[
...     PolicyIntervention("approved_change_window", True),
...     PolicyIntervention("dual_control_verified", True),
...     PolicyIntervention("rollback_plan_verified", True),
... ])
>>> print(explanation.original_verdict)       # "escalate"
>>> print(explanation.counterfactual_verdict)  # "verify"
>>> print(explanation.remaining_blockers)      # ["Action arguments derive from untrusted source..."]
"""
from remora.causal.counterfactual import CounterfactualReplay, CounterfactualResult
from remora.causal.explanation import CausalExplanation, generate_explanation
from remora.causal.intervention import PolicyIntervention, validate_intervention
from remora.causal.schema import (
    CausalDecisionModel,
    CausalEdge,
    CausalVariable,
    VariableProvenance,
    VariableType,
)

__all__ = [
    "CausalDecisionModel",
    "CausalEdge",
    "CausalExplanation",
    "CausalVariable",
    "CounterfactualReplay",
    "CounterfactualResult",
    "PolicyIntervention",
    "VariableProvenance",
    "VariableType",
    "generate_explanation",
    "validate_intervention",
]
