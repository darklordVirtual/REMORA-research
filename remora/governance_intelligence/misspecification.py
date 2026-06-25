# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic misspecification-risk inference.

Compares caller-supplied labels against deterministically inferred semantics
and surfaces disagreement as explicit risk. No LLM calls; every rule is a
visible, testable heuristic.

Core invariants (see tests/governance_intelligence/test_misspecification_inference.py):

- supplied "read"/"low" vs inferred destructive/high → risk >= 0.8
- unknown environment + production signals in text → environment_mismatch_detected
- ambiguous objective + mutating action → objective_ambiguity >= 0.5
- destructive action + unknown rollback → state_transition_uncertain
"""
from __future__ import annotations

import re
from typing import Any

from remora.governance_intelligence.action_semantics import DANGEROUS_ARGUMENT_KEYS
from remora.governance_intelligence.normalization import (
    MUTATING_ACTION_TYPES,
    READ_ONLY_ACTION_TYPES,
    UNKNOWN,
)
from remora.governance_intelligence.types import (
    RISK_TIER_RANK,
    ActionSemantics,
    MisspecificationAssessment,
    NormalizedMetadata,
)

# Ambiguous-objective verbs: each maps to a deterministic list of plausible
# objectives so reviewers can see *why* the objective is considered ambiguous.
_AMBIGUOUS_OBJECTIVES: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...] = (
    ("clean_up", re.compile(r"\bclean\s*up\b|\btidy\b", re.IGNORECASE),
     ("archive stale records", "deactivate unused entries", "permanently delete data")),
    ("optimize", re.compile(r"\boptimi[sz]e\b", re.IGNORECASE),
     ("re-tune configuration", "remove records considered redundant", "restructure live resources")),
    ("fix", re.compile(r"\bfix\b|\brepair\b", re.IGNORECASE),
     ("correct a known defect", "overwrite current state", "change permissions or configuration")),
    ("sync", re.compile(r"\bsync(?:hroni[sz]e)?\b", re.IGNORECASE),
     ("copy data one way", "merge bidirectionally", "overwrite the destination")),
    ("sort_out", re.compile(r"\bsort\s+out\b|\bdeal\s+with\b", re.IGNORECASE),
     ("investigate only", "modify state", "remove the offending items")),
)


def _tier_rank(tier: str | None) -> int | None:
    if tier is None:
        return None
    return RISK_TIER_RANK.get(tier)


def assess_misspecification(
    normalized: NormalizedMetadata,
    semantics: ActionSemantics,
    *,
    tool_arguments: dict[str, Any] | None = None,
    rollback_available: bool | None = None,
    text: str = "",
) -> MisspecificationAssessment:
    """Infer misspecification risk from label/semantics disagreement.

    Parameters
    ----------
    normalized:
        Fail-closed normalisation of the caller-supplied labels.
    semantics:
        Deterministic semantics extracted from the action text.
    tool_arguments:
        Raw tool arguments (scanned for dangerous keys; values are not logged).
    rollback_available:
        Caller-supplied rollback knowledge; ``None`` means unknown.
    text:
        The action text (used only for ambiguous-objective matching).
    """
    reasons: list[str] = []
    alternatives: list[dict[str, Any]] = []
    risk = 0.05 if normalized.metadata_complete else 0.30
    # Confidence in the *classification of this action*: when the caller
    # supplied a recognised action type, start from a solid prior and let the
    # mismatch rules below pull it down. When the caller supplied nothing, the
    # classification rests entirely on semantic extraction confidence.
    classification_confidence = (
        0.85 if normalized.action_type != UNKNOWN else semantics.confidence
    )
    environment_confidence = 0.90
    environment_mismatch = False

    supplied_action = normalized.action_type
    inferred_action = semantics.inferred_action_type
    supplied_rank = _tier_rank(normalized.risk_tier)
    inferred_rank = _tier_rank(semantics.inferred_risk_tier)

    if not normalized.metadata_complete:
        reasons.append(
            "metadata incomplete: " + ", ".join(normalized.metadata_unknown_fields)
        )

    # ── Action-type mismatch ────────────────────────────────────────────────
    inferred_mutating = semantics.mutating or inferred_action in MUTATING_ACTION_TYPES
    supplied_read_like = supplied_action in READ_ONLY_ACTION_TYPES
    if supplied_read_like and semantics.destructive:
        risk = max(risk, 0.85)
        classification_confidence = min(classification_confidence, 0.30)
        reasons.append(
            f"supplied action_type '{supplied_action}' but semantics indicate "
            f"destructive '{inferred_action}'"
        )
        alternatives.append(
            {"action_type": inferred_action, "confidence": semantics.confidence,
             "source": "action_semantics"}
        )
    elif supplied_read_like and inferred_mutating:
        risk = max(risk, 0.70)
        classification_confidence = min(classification_confidence, 0.40)
        reasons.append(
            f"supplied action_type '{supplied_action}' but semantics indicate "
            f"mutating '{inferred_action}'"
        )
        alternatives.append(
            {"action_type": inferred_action, "confidence": semantics.confidence,
             "source": "action_semantics"}
        )
    elif (
        supplied_action not in (UNKNOWN, inferred_action)
        and inferred_action != UNKNOWN
        and semantics.destructive
        and not normalized.destructive_or_irreversible
    ):
        # Supplied a non-destructive label, semantics say destructive.
        risk = max(risk, 0.80)
        classification_confidence = min(classification_confidence, 0.35)
        reasons.append(
            f"supplied action_type '{supplied_action}' conflicts with "
            f"destructive semantics '{inferred_action}'"
        )
        alternatives.append(
            {"action_type": inferred_action, "confidence": semantics.confidence,
             "source": "action_semantics"}
        )

    # ── Risk-tier mismatch ──────────────────────────────────────────────────
    if supplied_rank is not None and inferred_rank is not None and inferred_rank > supplied_rank:
        gap = inferred_rank - supplied_rank
        risk = max(risk, 0.80 if gap >= 2 else 0.65)
        reasons.append(
            f"supplied risk_tier '{normalized.risk_tier}' below inferred "
            f"'{semantics.inferred_risk_tier}'"
        )
        if gap >= 2:
            classification_confidence = min(classification_confidence, 0.40)

    # ── Environment ─────────────────────────────────────────────────────────
    if semantics.production_signal and normalized.target_environment in ("dev", "staging"):
        environment_mismatch = True
        environment_confidence = 0.30
        risk = max(risk, 0.75)
        reasons.append(
            f"supplied environment '{normalized.target_environment}' but text "
            "carries production signals"
        )
    elif semantics.production_signal and normalized.target_environment == UNKNOWN:
        environment_mismatch = True
        environment_confidence = 0.30
        risk = max(risk, 0.70)
        reasons.append("environment unknown but text carries production signals")
    elif normalized.target_environment == UNKNOWN and (normalized.mutating_action or inferred_mutating):
        environment_confidence = 0.50
        risk = max(risk, 0.65)
        reasons.append("environment unknown for a mutating action")

    # ── Tool-name vs declared action type ───────────────────────────────────
    if (
        normalized.tool_name
        and supplied_read_like
        and any(k in normalized.tool_name for k in
                ("delete", "drop", "write", "update", "create", "remove",
                 "exec", "deploy", "transfer", "grant", "revoke"))
    ):
        risk = max(risk, 0.75)
        classification_confidence = min(classification_confidence, 0.40)
        reasons.append(
            f"tool name '{normalized.tool_name}' implies mutation but "
            f"action_type is '{supplied_action}'"
        )

    # ── Dangerous argument keys ─────────────────────────────────────────────
    if tool_arguments:
        dangerous = sorted(
            k for k in tool_arguments
            if str(k).strip().lower().lstrip("-") in DANGEROUS_ARGUMENT_KEYS
        )
        if dangerous:
            risk = max(risk, 0.50)
            reasons.append(
                "tool arguments contain force/destructive keys: " + ", ".join(dangerous)
            )

    # ── Objective ambiguity ─────────────────────────────────────────────────
    objective_ambiguity = 0.0
    possible_objectives: list[str] = []
    for name, rx, objectives in _AMBIGUOUS_OBJECTIVES:
        if rx.search(text):
            possible_objectives.extend(objectives)
            if normalized.mutating_action or inferred_mutating:
                objective_ambiguity = max(objective_ambiguity, 0.60)
                reasons.append(f"ambiguous objective '{name}' on a mutating action")
            else:
                objective_ambiguity = max(objective_ambiguity, 0.30)
    if objective_ambiguity >= 0.50:
        # Ambiguous objective on a mutating action is genuine misspecification
        # risk: 0.65 clears the engine's misspecification-verify gate (> 0.60).
        risk = max(risk, 0.65)

    # ── Rollback / state transition ─────────────────────────────────────────
    state_transition_uncertain = False
    if semantics.destructive and rollback_available is None:
        state_transition_uncertain = True
        reasons.append("destructive action with unknown rollback availability")
    if rollback_available is None and (normalized.mutating_action or inferred_mutating) \
            and normalized.production_like_environment:
        state_transition_uncertain = True
        if "mutating production action with unknown rollback" not in reasons:
            reasons.append("mutating production action with unknown rollback")

    return MisspecificationAssessment(
        classification_confidence=round(max(0.05, classification_confidence), 4),
        model_misspecification_risk=round(min(1.0, risk), 4),
        classification_alternatives=tuple(alternatives),
        environment_confidence=round(environment_confidence, 4),
        environment_mismatch_detected=environment_mismatch,
        objective_ambiguity=round(objective_ambiguity, 4),
        possible_objectives=tuple(dict.fromkeys(possible_objectives)),
        state_transition_uncertain=state_transition_uncertain,
        rollback_available=rollback_available,
        reasons=tuple(reasons),
    )
