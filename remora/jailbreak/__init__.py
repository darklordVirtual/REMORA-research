# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Jailbreak-rated model posture (docs/design/jailbreak-rated-model-posture-v1.md).

S1 provides the deterministic FMF-CYBER-JBR-1.0 scoring core (JBR-02..04).
Nothing in this package is on a decision path yet: posture caps arrive in S3
behind ``REMORA_JAILBREAK_POSTURE=1``. With the flag off, or before S3,
importing this package changes no decision.
"""
from remora.jailbreak.fmf_scoring import (
    DEFAULT_GUARDRAILS,
    FRAMEWORK_ID,
    MATRIX,
    Band,
    GuardrailPolicy,
    Score,
    ScoringRefused,
    combined_band,
    score,
)

__all__ = [
    "DEFAULT_GUARDRAILS",
    "FRAMEWORK_ID",
    "MATRIX",
    "Band",
    "GuardrailPolicy",
    "Score",
    "ScoringRefused",
    "combined_band",
    "score",
]
