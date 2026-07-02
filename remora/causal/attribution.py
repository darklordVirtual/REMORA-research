"""Global concept attribution over observation logs.

Implements the global explanation framework from Bjøru (2026) Paper IV §4.2.1:
the query P(ŷ^{do(¯z=¯z')} = ŷ' | ẑs, ŷ) is estimated by averaging
per-instance PS and PN scores (from `search.score_concepts`) over a log of
observations with blocking verdicts.

This answers the governance question:
  "Across our action log, which concept — if established — would most often
   have changed a blocking verdict?"

and the dual question:
  "Which concept is most load-bearing in the fully-remediated state?"
   (i.e., its absence alone causes the block to return)

References
----------
Bjøru, A. R. (2026). Causal Post-hoc Explainable AI. NTNU PhD thesis.
  Paper IV §4.2.1: Global explanations via dataset averaging.
  Paper IV §4.2.3: Concept attributions as mean PS scores.
Pearl, J. (2009). Causality (2nd ed.). Cambridge University Press.
  §9: PS and PN definitions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from remora.causal.schema import CausalDecisionModel
from remora.causal.search import score_concepts
from remora.policy.observation import PolicyObservation

if TYPE_CHECKING:
    from remora.policy.decision_engine import RemoraDecisionEngine


@dataclass
class ConceptAttributionResult:
    """Global concept attribution scores over a set of observations.

    Attributes
    ----------
    concept_name:
        Name of the actionable concept variable.
    label:
        Human-readable label.
    mean_ps:
        Mean Probability of Sufficiency across blocking observations.
        = fraction of blocking cases where do(concept=True) alone changes the verdict.
        Range [0.0, 1.0] (Bjøru 2026, Paper IV §4.2.3; Pearl 2009 §9.2.1).
    mean_pn:
        Mean Probability of Necessity across blocking observations.
        = fraction of blocking cases where this concept is load-bearing in the
        fully-remediated state.
        Range [0.0, 1.0] (Pearl 2009 §9.2.2).
    n_blocking:
        Number of observations with a blocking verdict included in the aggregation.
    n_sufficient:
        Number of blocking observations where this concept alone was sufficient
        to change the verdict (PS = 1).
    n_necessary:
        Number of blocking observations where this concept was necessary in the
        fully-remediated state (PN = 1).
    """
    concept_name: str
    label: str
    mean_ps: float
    mean_pn: float
    n_blocking: int
    n_sufficient: int
    n_necessary: int


def compute_concept_attribution(
    observations: list[PolicyObservation],
    engine: "RemoraDecisionEngine",
    model: CausalDecisionModel,
    blocking_verdicts: frozenset[str] | None = None,
) -> list[ConceptAttributionResult]:
    """Compute global concept attribution scores over a set of observations.

    For each actionable concept, aggregates per-observation PS and PN scores
    (from `score_concepts`) over all observations with a blocking verdict.

    Implements the global subgroup explanation from Bjøru (2026) Paper IV §4.2.1:
    the dataset D' = {observations with blocking verdict} forms the explanation
    context, and per-observation counterfactual results are averaged.

    Parameters
    ----------
    observations:
        Log of PolicyObservation instances (e.g. from a shadow-replay run).
    engine:
        The RemoraDecisionEngine.
    model:
        The CausalDecisionModel.
    blocking_verdicts:
        Set of verdict strings treated as "blocking". Defaults to
        {"verify", "abstain", "escalate"}.

    Returns
    -------
    List of ConceptAttributionResult sorted by mean_ps descending,
    mean_pn descending, concept_name ascending.  Returns one entry per
    actionable concept even if n_blocking = 0 (all scores = 0.0).
    """
    if blocking_verdicts is None:
        blocking_verdicts = frozenset({"verify", "abstain", "escalate"})

    ps_sums: dict[str, float] = {}
    pn_sums: dict[str, float] = {}
    n_sufficient: dict[str, int] = {}
    n_necessary: dict[str, int] = {}
    labels: dict[str, str] = {}
    n_blocking = 0

    for obs in observations:
        verdict = engine.decide(obs).action.value
        if verdict not in blocking_verdicts:
            continue
        n_blocking += 1
        for sc in score_concepts(obs, engine, model):
            name = sc.concept_name
            labels[name] = sc.label
            ps_sums[name] = ps_sums.get(name, 0.0) + sc.ps
            pn_sums[name] = pn_sums.get(name, 0.0) + sc.pn
            n_sufficient[name] = n_sufficient.get(name, 0) + (1 if sc.ps == 1.0 else 0)
            n_necessary[name] = n_necessary.get(name, 0) + (1 if sc.pn == 1.0 else 0)

    results: list[ConceptAttributionResult] = []
    for var in model.actionable_variables():
        name = var.name
        label = labels.get(name, var.label)
        if n_blocking == 0:
            results.append(ConceptAttributionResult(
                concept_name=name,
                label=label,
                mean_ps=0.0,
                mean_pn=0.0,
                n_blocking=0,
                n_sufficient=0,
                n_necessary=0,
            ))
        else:
            results.append(ConceptAttributionResult(
                concept_name=name,
                label=label,
                mean_ps=ps_sums.get(name, 0.0) / n_blocking,
                mean_pn=pn_sums.get(name, 0.0) / n_blocking,
                n_blocking=n_blocking,
                n_sufficient=n_sufficient.get(name, 0),
                n_necessary=n_necessary.get(name, 0),
            ))

    return sorted(
        results,
        key=lambda r: (-r.mean_ps, -r.mean_pn, r.concept_name),
    )
