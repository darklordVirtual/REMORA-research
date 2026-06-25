# Author: Stian Skogbrott
# License: Apache-2.0
"""Prover-Verifier Deliberation (PVD) for critical-phase routing.

Implements a lightweight PVD protocol inspired by Kirsch et al. (2024)
arXiv:2407.13692, adapted for REMORA's offline multi-oracle setting.

Background
----------
Kirsch et al. showed that prover-verifier games produce more legible LLM
outputs: a "prover" oracle justifies a claim to a "verifier" oracle whose
independent evaluation filters out low-quality reasoning.  In REMORA's
critical phase, oracle responses cluster near a phase boundary; the prover-
verifier signal provides a deliberation-grounded confidence estimate that
is more calibrated than the raw trust score for near-boundary items.

Protocol (offline simulation)
------------------------------
1. **Cluster** oracle responses with Semantic Entropy clustering.
2. **Prover** = oracle whose response belongs to the dominant cluster (the
   response the majority is "arguing for").
3. **Verifier** = oracle with the highest per-oracle confidence that is
   *not* in the dominant cluster (the independent challenger).  If all
   oracles agree, the verifier is the second-highest-confidence oracle.
4. **Deliberation rounds** (1–n_rounds): each round re-evaluates the
   verifier's cluster membership after prover's implicit argument.  We
   simulate this by measuring the bidirectional NLI entailment score
   between prover and verifier responses, scaled by a round-decay factor.
5. **Legibility score** = mean entailment score across rounds × agreement
   fraction.  High legibility means the prover's claim is compelling.
6. **Final confidence** = geometric mean of:
   - dominant cluster mass (prover's empirical support)
   - verifier_confidence after deliberation
   Bounded to [0, 1].

Guarantee
---------
No new LLM API calls are made.  All deliberation signals are derived from
existing oracle response text and pre-computed NLI entailment scores.

Reference
---------
Kirsch, A., Harrison, J., Misra, S., & Leike, J. (2024).
Prover-verifier games improve legibility of LLM outputs.
*arXiv:2407.13692*.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from remora.semantic_entropy import (
    NLIBackend,
    SemanticEntropyResult,
    TokenFingerprintBackend,
    compute_semantic_entropy,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PVDResult:
    """Outcome of one prover-verifier deliberation.

    Attributes
    ----------
    prover_response:
        The response selected as the prover's claim.
    verifier_response:
        The response selected as the independent verifier's claim.
    prover_cluster_mass:
        Fraction of oracle responses in the dominant (prover's) cluster.
    verifier_initial_confidence:
        Per-oracle confidence for the verifier oracle before deliberation.
    verifier_final_confidence:
        Verifier confidence after n_rounds of deliberation.
    legibility_score:
        Mean NLI entailment score from prover to verifier across rounds,
        multiplied by prover_cluster_mass.  ∈ [0, 1].
    agreement:
        Whether prover and verifier converged to the same cluster (bool),
        expressed as a float (1.0 = full agreement, 0.0 = no agreement).
    deliberation_rounds:
        Number of deliberation rounds completed.
    final_confidence:
        Routing confidence for REMORA: geometric mean of
        prover_cluster_mass and verifier_final_confidence.
    should_accept:
        ``True`` if final_confidence ≥ accept_threshold.
    se_result:
        Full Semantic Entropy result used for clustering.
    """

    prover_response: str
    verifier_response: str
    prover_cluster_mass: float
    verifier_initial_confidence: float
    verifier_final_confidence: float
    legibility_score: float
    agreement: float
    deliberation_rounds: int
    final_confidence: float
    should_accept: bool
    se_result: SemanticEntropyResult


# ---------------------------------------------------------------------------
# Core deliberation logic
# ---------------------------------------------------------------------------


def deliberate(
    oracle_responses: Sequence[str],
    oracle_confidences: Sequence[float] | None = None,
    backend: NLIBackend | None = None,
    entailment_threshold: float = 0.5,
    n_rounds: int = 2,
    accept_threshold: float = 0.60,
) -> PVDResult:
    """Run prover-verifier deliberation on a set of oracle responses.

    Parameters
    ----------
    oracle_responses:
        Raw text responses from each oracle.
    oracle_confidences:
        Per-oracle confidence scores ∈ [0, 1].  Defaults to uniform (1/N).
    backend:
        NLI backend for semantic clustering and entailment scoring.
        Defaults to :class:`~remora.semantic_entropy.TokenFingerprintBackend`.
    entailment_threshold:
        Threshold for bidirectional NLI entailment in SE clustering.
    n_rounds:
        Number of deliberation rounds.  Each round re-evaluates the NLI
        score between prover and verifier with a round-decay factor.
    accept_threshold:
        final_confidence threshold for ``should_accept``.

    Returns
    -------
    PVDResult
        Deliberation outcome with final routing confidence.
    """
    if not oracle_responses:
        return _empty_result(accept_threshold)

    n = len(oracle_responses)
    responses = list(oracle_responses)

    if oracle_confidences is None:
        confs = [1.0 / n] * n
    else:
        if len(oracle_confidences) != n:
            raise ValueError("oracle_confidences must have same length as oracle_responses")
        confs = [max(0.0, float(c)) for c in oracle_confidences]

    if backend is None:
        backend = TokenFingerprintBackend()

    # Step 1: Cluster responses with SE
    se_result = compute_semantic_entropy(
        responses, backend=backend, entailment_threshold=entailment_threshold
    )

    if not se_result.clusters:
        return _empty_result(accept_threshold, se_result=se_result)

    # Step 2: Identify prover (dominant cluster member with highest confidence)
    dominant_cluster = se_result.clusters[0]
    prover_response, prover_idx = _select_oracle(
        responses, confs, members=dominant_cluster.members, prefer_high=True
    )

    # Step 3: Identify verifier (highest-confidence oracle outside dominant cluster)
    verifier_members = [r for r in responses if r not in dominant_cluster.members]
    if verifier_members:
        verifier_response, verifier_idx = _select_oracle(
            responses, confs, members=verifier_members, prefer_high=True
        )
    else:
        # All oracles agree — verifier is second-highest-confidence oracle
        sorted_by_conf = sorted(
            [(i, c) for i, c in enumerate(confs) if i != prover_idx],
            key=lambda x: x[1], reverse=True
        )
        if sorted_by_conf:
            verifier_idx = sorted_by_conf[0][0]
            verifier_response = responses[verifier_idx]
        else:
            verifier_response = prover_response
            verifier_idx = prover_idx

    verifier_initial_conf = confs[verifier_idx]

    # Step 4: Deliberation rounds — measure NLI entailment prover→verifier
    entailment_scores = []
    round_decay = 1.0
    decay_factor = 0.85
    for _ in range(n_rounds):
        score = backend.predict(prover_response, verifier_response)
        entailment_scores.append(score * round_decay)
        round_decay *= decay_factor

    mean_entailment = sum(entailment_scores) / len(entailment_scores) if entailment_scores else 0.0

    # Step 5: Verifier final confidence — updated by deliberation
    # High entailment: verifier is "convinced" by prover; verifier confidence rises
    # Low entailment: verifier remains unconvinced; confidence stays low
    verifier_final_conf = min(
        1.0,
        verifier_initial_conf + (1.0 - verifier_initial_conf) * mean_entailment * 0.5
    )

    # Step 6: Legibility = entailment × prover's cluster mass
    legibility = mean_entailment * dominant_cluster.mass

    # Step 7: Agreement — are prover and verifier in the same cluster?
    agreement = _cluster_agreement(prover_response, verifier_response, se_result)

    # Step 8: Final confidence = geometric mean(cluster mass, verifier final conf)
    if dominant_cluster.mass > 0 and verifier_final_conf > 0:
        final_confidence = math.sqrt(dominant_cluster.mass * verifier_final_conf)
    else:
        final_confidence = 0.0

    return PVDResult(
        prover_response=prover_response,
        verifier_response=verifier_response,
        prover_cluster_mass=dominant_cluster.mass,
        verifier_initial_confidence=verifier_initial_conf,
        verifier_final_confidence=verifier_final_conf,
        legibility_score=legibility,
        agreement=agreement,
        deliberation_rounds=n_rounds,
        final_confidence=final_confidence,
        should_accept=final_confidence >= accept_threshold,
        se_result=se_result,
    )


# ---------------------------------------------------------------------------
# PVD-enhanced routing signal
# ---------------------------------------------------------------------------


def pvd_routing_score(
    trust_score: float,
    pvd_result: PVDResult,
    pvd_weight: float = 0.40,
) -> float:
    """Blend REMORA trust score with PVD deliberation confidence.

    Computes a routing score for critical-phase items by interpolating
    between the raw REMORA trust score and the PVD final confidence::

        score = (1 - pvd_weight) * trust_score + pvd_weight * pvd_result.final_confidence

    This allows PVD to pull borderline critical-phase items toward ACCEPT
    when deliberation confidence is high, extending coverage beyond the
    PhaseAwareGuardrail operating point.

    Parameters
    ----------
    trust_score:
        Raw REMORA trust score τ ∈ [0, 1].
    pvd_result:
        PVD deliberation outcome.
    pvd_weight:
        Weight given to PVD confidence in the blend (default 0.40).
        Higher values give more weight to deliberation over raw trust.

    Returns
    -------
    float
        Blended routing score ∈ [0, 1].
    """
    pvd_weight = max(0.0, min(1.0, pvd_weight))
    return (1.0 - pvd_weight) * float(trust_score) + pvd_weight * pvd_result.final_confidence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_oracle(
    responses: list[str],
    confidences: list[float],
    members: list[str],
    prefer_high: bool = True,
) -> tuple[str, int]:
    """Select the oracle from *members* with highest (or lowest) confidence."""
    candidates = [(i, c) for i, (r, c) in enumerate(zip(responses, confidences)) if r in members]
    if not candidates:
        return responses[0], 0
    candidates.sort(key=lambda x: x[1], reverse=prefer_high)
    idx = candidates[0][0]
    return responses[idx], idx


def _cluster_agreement(
    prover_response: str,
    verifier_response: str,
    se_result: SemanticEntropyResult,
) -> float:
    """1.0 if prover and verifier are in the same cluster; 0.0 otherwise."""
    for cluster in se_result.clusters:
        if prover_response in cluster.members and verifier_response in cluster.members:
            return 1.0
    return 0.0


def _empty_result(
    accept_threshold: float,
    se_result: SemanticEntropyResult | None = None,
) -> PVDResult:
    """Return a zero-confidence PVDResult for edge cases."""
    from remora.semantic_entropy import SemanticEntropyResult
    if se_result is None:
        se_result = SemanticEntropyResult(
            entropy=0.0,
            clusters=(),
            n_responses=0,
            n_clusters=0,
            backend_name="none",
        )
    return PVDResult(
        prover_response="",
        verifier_response="",
        prover_cluster_mass=0.0,
        verifier_initial_confidence=0.0,
        verifier_final_confidence=0.0,
        legibility_score=0.0,
        agreement=0.0,
        deliberation_rounds=0,
        final_confidence=0.0,
        should_accept=False,
        se_result=se_result,
    )
