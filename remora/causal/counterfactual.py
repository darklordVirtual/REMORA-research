"""Counterfactual policy replay for REMORA.

Implements policy-only counterfactual analysis: given an original
PolicyObservation and a set of PolicyInterventions, rerun the engine with
the interventions applied and report what changed.

This is NOT a prediction of real-world outcomes.  It answers the question:
"What would the policy engine decide if the operational conditions described
by these concept interventions were in place?"

The replay is deterministic: same observation + same interventions always
produces the same result.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from remora.causal.intervention import PolicyIntervention, validate_intervention
from remora.causal.schema import CausalDecisionModel
from remora.policy.observation import PolicyObservation

if TYPE_CHECKING:
    from remora.policy.decision_engine import RemoraDecisionEngine


@dataclass
class CounterfactualResult:
    """Result of one counterfactual policy replay.

    Parameters
    ----------
    factual_verdict:
        The policy verdict for the original, unmodified observation.
    counterfactual_verdict:
        The policy verdict after applying the interventions.
    changed_concepts:
        Names of concepts whose signal_mapping was applied.
    remaining_blockers:
        Human-readable labels of DecisionReasons that still fire after
        the interventions.  Empty means the counterfactual reached ACCEPT.
    interventions_applied:
        The full list of interventions used in this replay.
    is_deterministic:
        Always True — the RemoraDecisionEngine is a deterministic rule tree.
    """
    factual_verdict: str
    counterfactual_verdict: str
    changed_concepts: list[str]
    remaining_blockers: list[str]
    interventions_applied: list[PolicyIntervention]
    is_deterministic: bool = True


class CounterfactualReplay:
    """Applies concept interventions to a PolicyObservation and reruns the engine.

    Parameters
    ----------
    engine:
        A RemoraDecisionEngine instance.  The engine is not modified.
    model:
        The CausalDecisionModel defining which concepts are actionable and
        how each concept maps to PolicyObservation field overrides.
    """

    def __init__(
        self,
        engine: "RemoraDecisionEngine",
        model: CausalDecisionModel,
    ) -> None:
        self._engine = engine
        self._model = model

    def apply_interventions(
        self,
        obs: PolicyObservation,
        interventions: list[PolicyIntervention],
    ) -> PolicyObservation:
        """Return a modified PolicyObservation with signal_mappings applied.

        For each intervention where value is truthy, merges the concept's
        signal_mapping into the observation via dataclasses.replace().
        The original observation is unchanged.
        """
        overrides: dict[str, Any] = {}
        for iv in interventions:
            var = self._model.get_variable(iv.variable)
            if var is None:
                continue
            if iv.value and var.signal_mapping:
                overrides.update(var.signal_mapping)
        if not overrides:
            return obs
        return dataclasses.replace(obs, **overrides)

    def replay(
        self,
        obs: PolicyObservation,
        interventions: list[PolicyIntervention],
    ) -> CounterfactualResult:
        """Run counterfactual policy replay.

        Parameters
        ----------
        obs:
            The original PolicyObservation for the factual decision.
        interventions:
            One or more PolicyInterventions to apply.  All must target
            actionable variables in this model.

        Returns
        -------
        CounterfactualResult with factual and counterfactual verdicts,
        changed concepts, and remaining blockers.

        Raises
        ------
        ValueError
            If any intervention targets a non-actionable variable.
        """
        for iv in interventions:
            validate_intervention(iv, self._model)

        factual_report = self._engine.decide(obs)
        cf_obs = self.apply_interventions(obs, interventions)
        cf_report = self._engine.decide(cf_obs)

        changed_concepts = [
            iv.variable
            for iv in interventions
            if iv.value and self._model.get_variable(iv.variable) is not None
        ]

        # Remaining blockers: reason labels from the counterfactual report
        from remora.causal.explanation import _REASON_TO_LABEL
        remaining_blockers = [
            _REASON_TO_LABEL.get(r.value, r.value)
            for r in cf_report.reasons
            if cf_report.action.value != "accept"
        ]

        return CounterfactualResult(
            factual_verdict=factual_report.action.value,
            counterfactual_verdict=cf_report.action.value,
            changed_concepts=changed_concepts,
            remaining_blockers=remaining_blockers,
            interventions_applied=list(interventions),
            is_deterministic=True,
        )
