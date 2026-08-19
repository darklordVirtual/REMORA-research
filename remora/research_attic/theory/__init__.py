# SPDX-License-Identifier: BUSL-1.1
"""Formal theoretical foundations for REMORA's online learning system."""

from remora.research_attic.theory.joint_convergence import CoupledConvergenceResult, JointConvergenceTheorem
from remora.research_attic.theory.maxent_grounding import MaxEntropyGrounding
from remora.research_attic.theory.scaling_analysis import ScalingAnalysis

__all__ = [
    "CoupledConvergenceResult",
    "JointConvergenceTheorem",
    "MaxEntropyGrounding",
    "ScalingAnalysis",
]
