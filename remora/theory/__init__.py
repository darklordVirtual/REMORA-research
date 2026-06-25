"""Formal theoretical foundations for REMORA's online learning system."""

from remora.theory.joint_convergence import CoupledConvergenceResult, JointConvergenceTheorem
from remora.theory.maxent_grounding import MaxEntropyGrounding
from remora.theory.scaling_analysis import ScalingAnalysis

__all__ = [
    "CoupledConvergenceResult",
    "JointConvergenceTheorem",
    "MaxEntropyGrounding",
    "ScalingAnalysis",
]
