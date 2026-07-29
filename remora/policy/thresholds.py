# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Heuristic decision thresholds for the REMORA policy engine.

Extracted verbatim from ``remora/policy/decision_engine.py`` (2026-07-29) so
that the 1200-line engine module carries logic, not constant literals. The
VALUES are unchanged and are pinned by
``tests/test_policy_threshold_constants.py``; this module is part of the
hashed policy bundle (``remora/policy/versioning.py``), so an edit here still
changes the policy-bundle hash exactly as it did when the constants lived in
``decision_engine.py``.

CALIBRATED thresholds are NOT here. They are derived from committed result
artifacts and injected into the engine at construction, never hard-coded:
``temperature_threshold`` (in-sample optimum, remora/policy/calibration.py),
``conformal_trust_threshold`` / ``conformal_phase_thresholds`` (offline
conformal calibration). ``TRAP_ESCALATE/VERIFY_THRESHOLD``
(remora/policy/trap_classifier.py) and ``MINIMAX_ESCALATE_THRESHOLD``
(remora/credal.py) are calibrated and named at their own point of definition.

The HEURISTIC thresholds below are HAND-TUNED conservative constants. They are
NOT derived from any artifact and MUST NOT be cited as calibrated. Each errs
toward VERIFY/ESCALATE (more human review), consistent with the fail-closed
posture. ``decision_engine.py`` re-imports every name below into its own module
namespace so the ``_CONDITIONAL_GATES`` lambdas (which close over these as
engine-module globals) and ``de.<NAME>`` references keep resolving.
"""
from __future__ import annotations

# Minimum oracle votes before a decision is trusted. Fewer votes means the
# oracle pool may be degraded or partially compromised. If oracle consultation
# was attempted (valid_oracle_count > 0 or oracle_failures > 0) but fewer than
# this number of oracles responded, route to human review.
MIN_REQUIRED_ORACLE_VOTES: int = 2

# Trust bar for the ordered-phase high-trust ACCEPT and the evidence-supported
# ACCEPT (coincides with the AROMER-recommended value but is not artifact-fit).
ORDERED_HIGH_TRUST_MIN: float = 0.72
# Evidence-verifier confidence required before an evidence-supported ACCEPT.
EVIDENCE_CONFIDENCE_MIN: float = 0.7
# Trust below which a non-answer routes to ABSTAIN.
LOW_TRUST_ABSTAIN_MAX: float = 0.2
# Credal ambiguity width required (with minimax) before escalating — guards
# against escalating low-trust zero-H/D observations.
MINIMAX_AMBIGUITY_WIDTH_MIN: float = 0.15
# Production-env confidence below which a non-read action verifies.
ENV_CONFIDENCE_MIN: float = 0.80
# Classification-confidence below which a non-read action verifies.
CLASSIFICATION_CONFIDENCE_MIN: float = 0.60
# Model-misspecification risk above which a non-read action verifies.
MISSPECIFICATION_RISK_MAX: float = 0.60
# Session cumulative-risk above which the "boiling frog" gate verifies.
SESSION_CUMULATIVE_RISK_MAX: float = 0.80
# Session action-count above which the flood gate verifies.
SESSION_ACTION_COUNT_MAX: int = 100
# Fleet-scale policy-generalization risk above which the gate verifies.
POLICY_GENERALIZATION_RISK_MAX: float = 0.70
# Repeat-count of a similar action above which the flood gate verifies.
SIMILAR_ACTION_FLOOD_MAX: int = 50
