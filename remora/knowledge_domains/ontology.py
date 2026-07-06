# Author: Stian Skogbrott
# License: Apache-2.0
"""A domain ontology for claims, and a validator that a register conforms.

An assurance system needs a shared, machine-readable vocabulary: what evidence
levels exist and in what order, and what KINDS of claim there are (a capability
count is not a benchmark is not a machine-checked theorem). This module defines
that ontology and validates a register against it. The taxonomy is a PROPOSAL,
not a standard; conformance is checked over a committed fixture.
"""
from __future__ import annotations

EVIDENCE_LEVELS: tuple[str, ...] = (
    "theoretical",
    "measured",
    "benchmarked",
    "reproduced",
    "machine_checked",
    "externally_validated",
)

CLAIM_TYPES: tuple[str, ...] = (
    "theorem",
    "correctness",
    "capability",
    "benchmark",
    "roadmap",
)

# Committed fixture (one claim per type + a second capability -> 0 non-conforming).
FIXTURE: tuple[dict, ...] = (
    {"id": "T-1", "evidence_level": "machine_checked", "metrics": {"steps_verified": 5}},
    {"id": "C-1", "evidence_level": "benchmarked", "metrics": {"cases_total": 12, "cases_passing": 12}},
    {"id": "CAP-1", "evidence_level": "measured", "metrics": {"n_domains": 6}},
    {"id": "B-1", "evidence_level": "benchmarked", "metrics": {"overall_ratio": 8.0584}},
    {"id": "R-1", "evidence_level": "theoretical", "metrics": {}},
    {"id": "CAP-2", "evidence_level": "measured", "metrics": {"runtime_dependencies": 0}},
)


def classify(claim: dict) -> str | None:
    """First matching rule wins, so classification is a total function on claims."""
    level = claim.get("evidence_level")
    metrics = claim.get("metrics") or {}
    if level == "machine_checked":
        return "theorem"
    if any(k in metrics for k in ("cases_total", "cases_passing", "n_roundtrip_lossless")):
        return "correctness"
    if level == "theoretical":
        return "roadmap"
    if any(
        "ratio" in k or k.endswith("_f1") or k.endswith("_accuracy") or k == "savings_ratio"
        for k in metrics
    ):
        return "benchmark"
    if any(
        k.startswith("n_") or k.startswith("canon_") or k.startswith("chunks_") or k.endswith("_dependencies")
        for k in metrics
    ):
        return "capability"
    return None


def validate(claims: tuple[dict, ...]) -> dict[str, int]:
    nonconforming = 0
    for c in claims:
        level_ok = c.get("evidence_level") in EVIDENCE_LEVELS
        typed = classify(c) is not None
        if not (level_ok and typed):
            nonconforming += 1
    return {
        "n_levels": len(EVIDENCE_LEVELS),
        "n_claim_types": len(CLAIM_TYPES),
        "n_claims_checked": len(claims),
        "nonconforming": nonconforming,
    }
