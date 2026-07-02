"""Causal intervention search: minimal contrastive explanations and concept scores.

Implements two algorithms from Bjøru (2026) Paper IV:

§4.2.3 — Concept attributions (per-concept PS and PN scores):
    For each actionable concept, compute how often it alone is sufficient to
    change the blocking verdict (PS), and whether it is necessary in the
    fully-remediated state (PN).

§4.2.4 — Contrastive explanation search (BFS over concept power sets):
    Find the MINIMAL set of concepts that, if applied together, achieves
    PS = 1 (i.e., changes the policy verdict).  Similarity = |¯z| (number of
    concepts); we minimise |¯z|.  This is the operationalised contrastive
    explanation form from Bjøru (2026) Paper IV §4.2.4 and Galhotra et al. (2021).

References
----------
Bjøru, A. R. (2026). Causal Post-hoc Explainable AI. NTNU PhD thesis.
  Paper IV §4.2.2: Probability of Sufficiency (PS).
  Paper IV §4.2.3: Concept attributions via PS aggregation.
  Paper IV §4.2.4: Contrastive explanation search.
Pearl, J. (2009). Causality (2nd ed.). Cambridge University Press.
  §9: PS and PN definitions (Definitions 9.2.1, 9.2.2).
Galhotra, S., Pradhan, R., & Salimi, B. (2021). SIGMOD 2021.
  Contrastive explanation form using PS and necessity.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING

from remora.causal.counterfactual import CounterfactualReplay
from remora.causal.intervention import PolicyIntervention
from remora.causal.schema import CausalDecisionModel
from remora.policy.observation import PolicyObservation

if TYPE_CHECKING:
    from remora.policy.decision_engine import RemoraDecisionEngine

_VERDICT_RANK: dict[str, int] = {
    "accept": 0,
    "verify": 1,
    "abstain": 2,
    "escalate": 3,
}


def _rank(verdict: str) -> int:
    return _VERDICT_RANK.get(verdict, 1)


@dataclass
class InterventionScore:
    """PS and PN scores for a single actionable concept.

    Attributes
    ----------
    concept_name:
        Name of the concept variable.
    label:
        Human-readable label from the CausalDecisionModel.
    ps:
        Probability of Sufficiency (Pearl 2009 §9.2.1; Bjøru 2026 Paper IV §4.2.2).
        P(ŷ' ≠ ŷ | do(concept=True), current obs).
        In REMORA's deterministic setting: PS ∈ {0.0, 1.0}.
        PS = 1.0: applying this concept alone changes the policy verdict.
    pn:
        Probability of Necessity (Pearl 2009 §9.2.2).
        Computed as: does removing this concept from the fully-remediated baseline
        worsen the policy verdict?
        PN = 1.0: this concept is load-bearing in the fully-remediated state.
        PN = 0.0: other concepts already cover this one; it is redundant.
    factual_verdict:
        The verdict on the original (unmodified) observation.
    ps_verdict:
        The verdict after applying do(concept=True) to the original observation.
    pn_verdict:
        The verdict after removing this concept from the fully-remediated state.
    """
    concept_name: str
    label: str
    ps: float
    pn: float
    factual_verdict: str
    ps_verdict: str
    pn_verdict: str


@dataclass
class MinimalSufficientInterventions:
    """All minimal concept sets that change the policy verdict (PS = 1).

    Contrastive explanation form (Bjøru 2026, Paper IV §4.2.4):
    "The verdict would be '{target_verdict}' if concepts {minimal_set} were applied."

    Attributes
    ----------
    factual_verdict:
        The original policy verdict.
    target_verdict:
        The verdict reached by the minimal intervention set(s), or None if none found.
    minimal_sets:
        All concept-name sets of cardinality `minimum_size` that achieve PS = 1.
        Empty if no sufficient set was found within max_size.
    minimum_size:
        Cardinality of the minimal sets.  0 means verdict is already ACCEPT.
        -1 means no sufficient set found within max_size.
    all_sets_exhausted:
        True iff the search covered all power-set subsets up to len(actionable).
        False if truncated by max_size before finding or exhausting solutions.
    """
    factual_verdict: str
    target_verdict: str | None
    minimal_sets: list[list[str]]
    minimum_size: int
    all_sets_exhausted: bool


def score_concepts(
    obs: PolicyObservation,
    engine: "RemoraDecisionEngine",
    model: CausalDecisionModel,
) -> list[InterventionScore]:
    """Compute per-concept PS and PN scores for a single observation.

    **Probability of Sufficiency (PS)**:
    For each actionable concept, test do(concept=True) on the current observation.
    PS = 1.0 iff the verdict changes (Bjøru 2026, Paper IV §4.2.2; Pearl 2009 §9.2.1).

    **Probability of Necessity (PN)**:
    Compute a "fully-remediated" baseline by applying all actionable concepts
    simultaneously, then remove each concept in turn. PN = 1.0 iff removing
    the concept from the fully-remediated state worsens the verdict (Pearl 2009 §9.2.2).

    Returns scores sorted by PS descending, PN descending, concept_name ascending.
    """
    replay = CounterfactualReplay(engine, model)
    factual_report = engine.decide(obs)
    factual_verdict = factual_report.action.value

    actionable = model.actionable_variables()

    # Build fully-remediated baseline: apply ALL actionable concepts
    all_on = [PolicyIntervention(v.name, True) for v in actionable]
    remediated_obs = replay.apply_interventions(obs, all_on)
    remediated_verdict = engine.decide(remediated_obs).action.value

    scores: list[InterventionScore] = []
    for var in actionable:
        # PS: does do(concept=True) alone change the verdict?
        ps_obs = replay.apply_interventions(obs, [PolicyIntervention(var.name, True)])
        ps_verdict = engine.decide(ps_obs).action.value
        ps = 1.0 if ps_verdict != factual_verdict else 0.0

        # PN: from fully-remediated baseline, does removing this concept worsen verdict?
        without_this = [PolicyIntervention(v.name, True) for v in actionable if v.name != var.name]
        pn_obs = replay.apply_interventions(obs, without_this) if without_this else obs
        pn_verdict = engine.decide(pn_obs).action.value
        pn = 1.0 if _rank(pn_verdict) > _rank(remediated_verdict) else 0.0

        scores.append(InterventionScore(
            concept_name=var.name,
            label=var.label,
            ps=ps,
            pn=pn,
            factual_verdict=factual_verdict,
            ps_verdict=ps_verdict,
            pn_verdict=pn_verdict,
        ))

    return sorted(scores, key=lambda s: (-s.ps, -s.pn, s.concept_name))


def find_minimal_sufficient_interventions(
    obs: PolicyObservation,
    engine: "RemoraDecisionEngine",
    model: CausalDecisionModel,
    max_size: int = 6,
) -> MinimalSufficientInterventions:
    """Find all minimal concept sets that change the policy verdict (BFS).

    Implements the contrastive explanation search from Bjøru (2026) Paper IV §4.2.4:
    the minimal contrastive explanation is the smallest set ¯z of concept
    interventions such that the local PS query returns 1.  Similarity is
    measured as |¯z|, and we minimise it.

    Algorithm: breadth-first search over power sets of actionable concepts,
    increasing cardinality from 1 to max_size.  All sets of the same minimum
    cardinality are returned (there may be multiple minimal explanations).

    For REMORA's current domains (≤6 actionable concepts) the worst case is
    2^6 = 64 engine calls — negligible.

    Parameters
    ----------
    obs:
        The observation to explain.
    engine:
        The RemoraDecisionEngine.
    model:
        The CausalDecisionModel.
    max_size:
        Maximum concept set cardinality to search. Defaults to 6.

    Returns
    -------
    MinimalSufficientInterventions.
    """
    replay = CounterfactualReplay(engine, model)
    factual_verdict = engine.decide(obs).action.value

    if factual_verdict == "accept":
        return MinimalSufficientInterventions(
            factual_verdict=factual_verdict,
            target_verdict="accept",
            minimal_sets=[],
            minimum_size=0,
            all_sets_exhausted=True,
        )

    actionable_names = [v.name for v in model.actionable_variables()]
    if not actionable_names:
        return MinimalSufficientInterventions(
            factual_verdict=factual_verdict,
            target_verdict=None,
            minimal_sets=[],
            minimum_size=-1,
            all_sets_exhausted=True,
        )

    cap = min(max_size, len(actionable_names))
    found: list[list[str]] = []
    target_verdict: str | None = None

    for size in range(1, cap + 1):
        for combo in combinations(actionable_names, size):
            ivs = [PolicyIntervention(name, True) for name in combo]
            cf_obs = replay.apply_interventions(obs, ivs)
            cf_verdict = engine.decide(cf_obs).action.value
            if cf_verdict != factual_verdict:
                found.append(list(combo))
                if target_verdict is None:
                    target_verdict = cf_verdict

        if found:
            return MinimalSufficientInterventions(
                factual_verdict=factual_verdict,
                target_verdict=target_verdict,
                minimal_sets=found,
                minimum_size=size,
                all_sets_exhausted=(size == len(actionable_names)),
            )

    return MinimalSufficientInterventions(
        factual_verdict=factual_verdict,
        target_verdict=None,
        minimal_sets=[],
        minimum_size=-1,
        all_sets_exhausted=(cap == len(actionable_names)),
    )
