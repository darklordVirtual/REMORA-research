# Author: Stian Skogbrott
# License: Apache-2.0
"""Epistemic vs. aleatoric uncertainty decomposition for REMORA oracle pools.

Background
----------
Classical uncertainty quantification distinguishes two orthogonal sources:

**Epistemic uncertainty** (model uncertainty / reducible)
    Arises from insufficient data or model capacity.  Adding more diverse
    oracles reduces epistemic uncertainty.  It is measured as the variance
    of the per-oracle polarity probabilities across the pool.

**Aleatoric uncertainty** (data uncertainty / irreducible)
    Inherent ambiguity in the question itself.  No amount of additional
    oracles can resolve it.  It is measured as the average within-oracle
    confidence spread (how close each oracle's probability is to 0.5).

REMORA application
------------------
The decomposition drives the escalation policy:

  - High epistemic + Low aleatoric  → add more diverse oracles (the
    consensus is unstable but the question has a deterministic answer)
  - Low epistemic + High aleatoric  → escalate to human review (oracles
    agree that the answer is uncertain)
  - High epistemic + High aleatoric → escalate to human (worst case)
  - Low epistemic + Low aleatoric   → accept the consensus answer

This is a principled improvement over the current single-threshold
``ABSTAIN`` decision in ConsensusGate, which cannot distinguish between
"the oracles disagree on something clear" and "even one oracle is
uncertain because the question is genuinely ambiguous."

Mathematical formulation
------------------------
Given K oracle polarity probabilities p_1 ... p_K (probability that the
answer is True), the estimators are:

    μ̄   = (1/K) Σ p_i                            # mean oracle probability
    Var_ep = (1/(K-1)) Σ (p_i − μ̄)²              # epistemic: inter-oracle variance
    Var_al = (1/K) Σ p_i(1 − p_i)                # aleatoric: mean Bernoulli variance

Total variance decomposition (bias-variance):
    Var_total = Var_ep + Var_al   (law of total variance for mixture models)

Normalisation: both quantities live in [0, 0.25] (maximum at p=0.5).
We normalise to [0, 1] by dividing by 0.25.

References
----------
Der Kiureghian & Ditlevsen (2009). Aleatory or epistemic? Does it matter?
Structural Safety, 31(2), 105–112.

Kendall & Gal (2017). What Uncertainties Do We Need in Bayesian Deep Learning
for Computer Vision? NeurIPS 2017.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Core decomposition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UncertaintyEstimate:
    """Decomposed uncertainty for a single oracle-pool query.

    Attributes
    ----------
    epistemic:
        Normalised inter-oracle variance in [0, 1].  High value → oracles
        disagree → adding diverse oracles may help.
    aleatoric:
        Normalised mean Bernoulli variance in [0, 1].  High value → each
        oracle is individually uncertain → question is genuinely ambiguous.
    total:
        epistemic + aleatoric (bounded to [0, 1] to handle floating-point noise).
    mean_prob:
        Mean polarity probability across oracles.
    n_oracles:
        Number of oracles contributing to the estimate.
    action:
        Recommended action based on thresholds: "accept", "add_oracles",
        "escalate_human", or "escalate_adversarial".
    """

    epistemic: float
    aleatoric: float
    total: float
    mean_prob: float
    n_oracles: int
    action: str


def decompose(
    oracle_probs: list[float],
    epistemic_threshold: float = 0.35,
    aleatoric_threshold: float = 0.50,
) -> UncertaintyEstimate:
    """Decompose oracle pool uncertainty into epistemic and aleatoric components.

    Parameters
    ----------
    oracle_probs:
        Per-oracle probability that the answer is True, each in [0, 1].
        These can be derived from raw oracle confidence scores:
            - If the oracle says True with confidence 0.8 → p = 0.8
            - If the oracle says False with confidence 0.8 → p = 0.2
            - If the oracle abstains → p = 0.5 (maximum entropy)
    epistemic_threshold:
        Normalised epistemic variance above which we recommend adding oracles.
        Default 0.35 corresponds to std ≈ 0.3 in probability space.
    aleatoric_threshold:
        Normalised aleatoric variance above which we recommend human escalation.
        Default 0.50 corresponds to mean oracle confidence near 0.5.

    Returns
    -------
    UncertaintyEstimate
    """
    if not oracle_probs:
        return UncertaintyEstimate(
            epistemic=1.0, aleatoric=1.0, total=1.0,
            mean_prob=0.5, n_oracles=0, action="escalate_human"
        )

    # Clip to valid range
    probs = [max(0.0, min(1.0, p)) for p in oracle_probs]
    k = len(probs)

    # Mean polarity probability
    mu = sum(probs) / k

    # Epistemic: inter-oracle variance (Bessel-corrected for k >= 2)
    if k >= 2:
        var_ep_raw = sum((p - mu) ** 2 for p in probs) / (k - 1)
    else:
        # Single oracle — epistemic uncertainty is maximal (we don't know)
        var_ep_raw = 0.25

    # Aleatoric: mean Bernoulli variance p_i(1 − p_i)
    var_al_raw = sum(p * (1.0 - p) for p in probs) / k

    # Normalise: maximum possible value for each is 0.25 (achieved at p=0.5)
    epistemic = min(1.0, var_ep_raw / 0.25)
    aleatoric = min(1.0, var_al_raw / 0.25)
    total = min(1.0, epistemic + aleatoric)

    # ------------------------------------------------------------------
    # Action recommendation
    # ------------------------------------------------------------------
    action = _recommend_action(
        epistemic=epistemic,
        aleatoric=aleatoric,
        epistemic_threshold=epistemic_threshold,
        aleatoric_threshold=aleatoric_threshold,
    )

    return UncertaintyEstimate(
        epistemic=round(epistemic, 6),
        aleatoric=round(aleatoric, 6),
        total=round(total, 6),
        mean_prob=round(mu, 6),
        n_oracles=k,
        action=action,
    )


def _recommend_action(
    epistemic: float,
    aleatoric: float,
    epistemic_threshold: float,
    aleatoric_threshold: float,
) -> str:
    """Map decomposed uncertainty onto a cascade action recommendation."""
    high_ep = epistemic > epistemic_threshold
    high_al = aleatoric > aleatoric_threshold

    if not high_ep and not high_al:
        return "accept"
    if high_ep and not high_al:
        # Oracles disagree on something that likely has a deterministic answer
        return "add_oracles"
    if not high_ep and high_al:
        # Oracles agree they don't know — question is genuinely ambiguous
        return "escalate_human"
    # Both high — worst case: disagreement + individual uncertainty
    return "escalate_adversarial"


# ---------------------------------------------------------------------------
# Convenience: convert oracle responses to polarity probabilities
# ---------------------------------------------------------------------------

def oracle_responses_to_probs(
    oracle_answers: list[bool | None],
    oracle_confidences: list[float],
) -> list[float]:
    """Convert raw oracle (answer, confidence) pairs to polarity probabilities.

    Parameters
    ----------
    oracle_answers:
        Boolean answer from each oracle (True/False/None for abstain).
    oracle_confidences:
        Calibrated confidence in [0, 1] for each oracle's answer.

    Returns
    -------
    list[float]
        Per-oracle probability that the answer is True.
    """
    if len(oracle_answers) != len(oracle_confidences):
        raise ValueError("oracle_answers and oracle_confidences must have the same length")

    probs = []
    for answer, conf in zip(oracle_answers, oracle_confidences):
        conf = max(0.0, min(1.0, float(conf)))
        if answer is None:
            probs.append(0.5)  # abstain → maximum entropy
        elif answer:
            probs.append(conf)
        else:
            probs.append(1.0 - conf)
    return probs


# ---------------------------------------------------------------------------
# Phase-correlated uncertainty classification
# ---------------------------------------------------------------------------

def uncertainty_phase(
    estimate: UncertaintyEstimate,
) -> Literal["confident", "epistemically_uncertain", "aleatorically_uncertain", "maximally_uncertain"]:
    """Map a decomposed estimate to a qualitative phase label.

    Useful for routing decisions and observability dashboards.
    """
    action = estimate.action
    if action == "accept":
        return "confident"
    if action == "add_oracles":
        return "epistemically_uncertain"
    if action == "escalate_human":
        return "aleatorically_uncertain"
    return "maximally_uncertain"
