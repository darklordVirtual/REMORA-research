# SPDX-License-Identifier: BUSL-1.1
"""Machine-readable reason vocabulary for evidence admission.

Frozen tuple, pinned by tests. Additive only: a code is never renamed or
removed once published, because a consumer may branch on it. This is a local
vocabulary for the admission layer, not a published wire contract — promoting
it to one is a separate versioning decision.
"""
from __future__ import annotations

REASON_CODES: tuple[str, ...] = (
    # processing axis
    "malformed_evidence",
    "unsupported_evidence_schema",
    "acquisition_failed",
    "verifier_failed",
    # provenance / source
    "evidence_source_unaccepted",
    "producer_visibility_not_established",
    "producer_capability_self_declared",
    "producer_scope_mismatch",
    # coverage
    "coverage_incomplete",
    "coverage_unknown",
    "coverage_scope_mismatch",
    # observation content
    "effect_observation_not_supplied",
    # vantage / independence
    "observation_vantage_not_independent",
    "observation_vantage_not_established",
    "self_report_not_independent",
    # binding
    "invocation_binding_not_established",
    "tool_call_hash_mismatch",
    "binding_scope_mismatch",
    # prior commitment
    "prior_commitment_missing",
    "prior_commitment_unaccepted",
    "prior_commitment_postdates_execution",
    "prior_commitment_scope_mismatch",
    # temporal
    "observation_before_window",
    "observation_after_window",
    "commitment_expired",
)
