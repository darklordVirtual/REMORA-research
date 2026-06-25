# Author: Stian Skogbrott
# License: Apache-2.0
"""Genome: evolvable hyperparameter container for a REMORA instance."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class RouterMode(Enum):
    """Threshold strategy for the pre-sweep router gate.

    STRICT   — all N oracles must agree before skipping REMORA (safest, fewest skips)
    BALANCED — simple majority (>N/2) is enough to skip (recommended default)
    HYBRID   — majority + avg confidence >= router_confidence_min (adds calibration check)
    """
    STRICT = "strict"
    BALANCED = "balanced"
    HYBRID = "hybrid"


@dataclass
class Genome:
    """Evolvable hyperparameter bundle controlling a single REMORA run."""

    max_iterations: int = 4
    max_subquestions: int = 2
    converged_threshold: float = 0.75
    entropy_abort_ratio: float = 1.3
    negation_weight: float = 0.4
    thermo_lambda: float = 0.4
    divergent_boost: float = 0.5
    negation_ratio: float = 0.25
    decomposition_strategy: str = "simple"
    early_exit_on_convergence: bool = True
    # Router gate — disabled by default for backwards compatibility
    enable_routing: bool = False
    router_mode: RouterMode = RouterMode.BALANCED
    router_confidence_min: float = 0.80
    # Experimental thermodynamic pre-router control.
    enable_thermodynamic_control: bool = False
    trust_threshold_high: float = 0.45
    trust_threshold_low: float = 0.08
    hallucination_threshold: float = 0.05
    thermo_calibration_path: str | None = None
    # Anti-convergence — injects accumulated claims into each oracle's prompt
    # after the first iteration, instructing oracles to find non-overlapping angles.
    # Addresses the echo-chamber failure mode where correlated models reinforce each other.
    enable_anti_convergence: bool = False
    anti_convergence_max_context_claims: int = 3  # max prior claims to inject

    # Causal Stress Testing (Do-Calculus)
    enable_causal_stress_test: bool = False
    causal_stress_threshold: float = 0.80  # Triggers if consensus > this threshold

    # Topological Data Analysis (TDA)
    enable_topological_analysis: bool = False

    # Zero-Knowledge Assurance Proofs (ZKP)
    enable_zkp_assurance: bool = False

    # Integration flags (Priority 7)
    # Cascade multi-stage pipeline (v2)
    enable_cascade: bool = False
    cascade_fast_threshold: float = 0.90
    cascade_consensus_accept_threshold: float = 0.65
    cascade_consensus_abstain_threshold: float = 0.12
    cascade_verify_threshold: float = 0.70
    cascade_sc_samples: int = 7
    cascade_sc_threshold: float = 0.72
    cascade_max_stages: int = 4
    cascade_budget_oracle_calls: int | None = None
    cascade_critique_max_rounds: int = 2

    enable_conformal_guardrail: bool = False
    conformal_target_risk: float = 0.05
    enable_gainability_routing: bool = False
    enable_evidence_v2: bool = False
    evidence_v2_min_reliability: float = 0.5
    evidence_v2_min_support: int = 2
    enable_semantic_claim_graph: bool = False
    enable_assurance_trace: bool = False
    enable_counterfactual_v2: bool = False
    enable_parallel_fanout: bool = True

    def summary(self) -> str:
        """Return a compact one-line summary of the genome's key parameters."""
        router = f", router={self.router_mode.value}" if self.enable_routing else ""
        thermo = ", thermo=on" if self.enable_thermodynamic_control else ""
        return (
            f"Genome(iter={self.max_iterations}, sub_q={self.max_subquestions}, "
            f"conv={self.converged_threshold}, λ_lyap={self.negation_weight}, "
            f"λ_thermo={self.thermo_lambda}{router}{thermo})"
        )
