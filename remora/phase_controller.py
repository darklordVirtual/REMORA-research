# Author: Stian Skogbrott
# License: Apache-2.0
"""Phase-aware consensus control built on the thermodynamic pre-sweep state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from remora.thermodynamics import ThermodynamicState


class ConsensusPhase(Enum):
    ORDERED = "ordered"
    CRITICAL = "critical"
    DISORDERED = "disordered"


@dataclass
class PhaseDecision:
    """Decision emitted by the phase-aware controller."""

    phase: ConsensusPhase
    action: str
    trust_score: float
    hallucination_bound: float
    max_iterations: int
    require_rag: bool
    explanation: str


def phase_decision(
    thermo_state: ThermodynamicState,
    genome_max_iterations: int = 4,
    trust_threshold_high: float = 0.75,
    trust_threshold_low: float = 0.30,
    halluc_threshold: float = 0.05,
    chi_escalate_threshold: float = 1.45,
) -> PhaseDecision:
    """Map a thermodynamic state to a concrete router action.

    Parameters
    ----------
    chi_escalate_threshold:
        Susceptibility (χ) upper bound for normal routing.  When
        ``thermo_state.susceptibility > chi_escalate_threshold`` the system
        is likely under adversarial or out-of-distribution (OOD) pressure:
        oracle responses are unusually sensitive to small perturbations,
        which is the correct use of the χ signal even though its AUC as a
        standalone difficulty predictor is below-chance (see
        NEGATIVE_RESULTS.md §1).  In this regime the controller forces
        action="escalate_adversarial" regardless of phase or trust score.

        The default threshold (1.45) was chosen empirically as the 97th
        percentile of χ on the N=302 benchmark; adjust per deployment.
    """
    phase = ConsensusPhase(thermo_state.phase)
    tau = thermo_state.trust_score
    halluc_bound = thermo_state.hallucination_bound
    chi = thermo_state.susceptibility

    # ------------------------------------------------------------------
    # OOD / adversarial detection gate (highest priority)
    # χ AUC = 0.39 as difficulty predictor but operates as a reliable
    # anomaly detector: extreme susceptibility signals that oracle verdicts
    # are unusually fragile to perturbations — a hallmark of adversarial
    # inputs and jailbreak attempts.  Escalate immediately.
    # ------------------------------------------------------------------
    if chi > chi_escalate_threshold:
        return PhaseDecision(
            phase=phase,
            action="escalate_adversarial",
            trust_score=tau,
            hallucination_bound=halluc_bound,
            max_iterations=0,
            require_rag=True,
            explanation=(
                f"χ={chi:.3f} exceeds escalation threshold {chi_escalate_threshold}: "
                "abnormally high susceptibility detected — possible adversarial or OOD input. "
                "Bypassing normal phase routing; human review required."
            ),
        )

    if phase == ConsensusPhase.ORDERED:
        if tau >= trust_threshold_high and halluc_bound < halluc_threshold:
            return PhaseDecision(
                phase=phase,
                action="trust",
                trust_score=tau,
                hallucination_bound=halluc_bound,
                max_iterations=0,
                require_rag=False,
                explanation="Ordered phase with stable trust; direct consensus is acceptable.",
            )
        return PhaseDecision(
            phase=phase,
            action="iterate_cautious",
            trust_score=tau,
            hallucination_bound=halluc_bound,
            max_iterations=max(1, genome_max_iterations // 2),
            require_rag=halluc_bound >= halluc_threshold,
            explanation="Ordered phase, but trust is below the direct-accept threshold.",
        )

    if phase == ConsensusPhase.CRITICAL:
        return PhaseDecision(
            phase=phase,
            action="iterate_cautious",
            trust_score=tau,
            hallucination_bound=halluc_bound,
            max_iterations=genome_max_iterations,
            require_rag=True,
            explanation="Critical phase with elevated fragility; iterate and require external evidence.",
        )

    if tau < trust_threshold_low:
        return PhaseDecision(
            phase=phase,
            action="refuse",
            trust_score=tau,
            hallucination_bound=halluc_bound,
            max_iterations=0,
            require_rag=True,
            explanation="Disordered phase with low trust; consensus should not be accepted directly.",
        )

    return PhaseDecision(
        phase=phase,
        action="demand_evidence",
        trust_score=tau,
        hallucination_bound=halluc_bound,
        max_iterations=genome_max_iterations,
        require_rag=True,
        explanation="Disordered phase with moderate trust; authoritative evidence is required.",
    )
