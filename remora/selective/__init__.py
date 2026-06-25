# Author: Stian Skogbrott
# License: Apache-2.0
"""Selective prediction and abstention helpers."""

from remora.selective.risk_coverage import (
    RouteDecision,
    SelectiveAction,
    SelectiveRouter,
    risk_coverage_curve,
)
from remora.selective.conformal import (
    UNATTAINABLE_THRESHOLD,
    conformal_threshold,
    coverage_at_threshold,
    split_calibration,
)
from remora.selective.guardrail import (
    ConformalPhaseGuardrail,
    GuardrailReport,
    MondrianPhaseGuardrail,
    MondrianPhaseGuardrailReport,
    PhaseAwareGuardrail,
)
from remora.selective.gainability import GainabilityClassifier, extract_features
from remora.selective.crc import (
    CRCReport,
    CovariateShiftCRC,
    crc_risk_bound,
    phase_importance_weights,
    weighted_conformal_threshold,
)
from remora.selective.pvd import (
    PVDResult,
    deliberate,
    pvd_routing_score,
)

__all__ = [
    "RouteDecision",
    "SelectiveAction",
    "SelectiveRouter",
    "risk_coverage_curve",
    "UNATTAINABLE_THRESHOLD",
    "conformal_threshold",
    "coverage_at_threshold",
    "split_calibration",
    "ConformalPhaseGuardrail",
    "GuardrailReport",
    "GainabilityClassifier",
    "extract_features",
    "MondrianPhaseGuardrail",
    "MondrianPhaseGuardrailReport",
    "PhaseAwareGuardrail",
    "CRCReport",
    "CovariateShiftCRC",
    "crc_risk_bound",
    "phase_importance_weights",
    "weighted_conformal_threshold",
    "PVDResult",
    "deliberate",
    "pvd_routing_score",
]


